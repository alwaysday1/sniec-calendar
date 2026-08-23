#!/usr/bin/env python3
"""Generate an iCalendar subscription feed from the official SNIEC schedule."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


SOURCE_TEMPLATE = "https://www.sniec.net/cn/visit_exhibition.php?month={month}"
LOCATION = "上海新国际博览中心（SNIEC），上海市浦东新区龙阳路2345号"
USER_AGENT = "sniec-calendar/1.0 (public calendar generator; low-frequency fetch)"
DATE_RANGE_RE = re.compile(
    r"(?P<start>20\d{2}/\d{2}/\d{2})\s*-\s*(?P<end>20\d{2}/\d{2}/\d{2})"
)
ORGANIZER_RE = re.compile(
    r"主办(?:方|单位)?\s*[：:]?\s*(.*?)"
    r"(?=(?:主办(?:方|单位)?|电话|传真|邮箱|网址|网站|APP)\s*[：:]?|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Exhibition:
    title: str
    start: date
    end: date
    organizer: str
    website: str | None
    details: str
    source_url: str

    def identity(self) -> str:
        """Identity stays stable when an event moves within the same year."""
        normalized = re.sub(r"\s+", "", self.title).casefold()
        return f"{self.start.year}|{normalized}"


@dataclass
class _RawEvent:
    title_parts: list[str]
    body_parts: list[str]
    links: list[str]


class _ScheduleParser(HTMLParser):
    """Collect each H2 and its following detail block from the schedule list."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[_RawEvent] = []
        self.current: _RawEvent | None = None
        self.in_title = False
        self.div_depth = 0
        self.event_div_depth: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "div":
            self.div_depth += 1
            if dict(attrs).get("id") == "second":
                self.event_div_depth = self.div_depth

        if tag == "h2":
            self._finish_current()
            self.current = _RawEvent([], [], [])
            self.in_title = True
            return

        if self.current is None:
            return

        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.current.links.append(href)
        elif tag == "br":
            self.current.body_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self.in_title = False
        elif tag == "div":
            if self.current and self.event_div_depth == self.div_depth:
                self._finish_current()
                self.event_div_depth = None
            self.div_depth = max(0, self.div_depth - 1)

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        if self.in_title:
            self.current.title_parts.append(data)
        else:
            self.current.body_parts.append(data)

    def finish(self) -> list[_RawEvent]:
        self._finish_current()
        return self.events

    def _finish_current(self) -> None:
        if self.current and _clean_text(" ".join(self.current.title_parts)):
            self.events.append(self.current)
        self.current = None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _schedule_region(page: str) -> str:
    start = re.search(r"<ul\b[^>]*\bid\s*=\s*['\"]upcom['\"][^>]*>", page, re.I)
    if not start:
        raise ValueError("SNIEC 页面结构异常：未找到 #upcom 展会列表")
    end = page.find("<!--分页", start.end())
    if end < 0:
        raise ValueError("SNIEC 页面结构异常：未找到展会列表结束标记")
    return page[start.end() : end]


def _normalize_url(href: str) -> str | None:
    value = urllib.parse.unquote(href).strip()
    if value.startswith("//"):
        value = "https:" + value
    elif value.lower().startswith("www."):
        value = "https://" + value

    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.netloc.lower().removeprefix("www.") == "sniec.net":
        return None
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def parse_schedule(page: str, source_url: str) -> list[Exhibition]:
    parser = _ScheduleParser()
    parser.feed(_schedule_region(page))

    parsed: list[Exhibition] = []
    for raw in parser.finish():
        title = _clean_text(" ".join(raw.title_parts))
        body = _clean_text(" ".join(raw.body_parts))
        match = DATE_RANGE_RE.search(body)
        if not match:
            continue

        start = datetime.strptime(match.group("start"), "%Y/%m/%d").date()
        end = datetime.strptime(match.group("end"), "%Y/%m/%d").date()
        if end < start:
            raise ValueError(f"展会结束日期早于开始日期：{title}")

        details = _clean_text(body[match.end() :])
        organizers = [_clean_text(item) for item in ORGANIZER_RE.findall(details)]
        organizer = "；".join(dict.fromkeys(item for item in organizers if item))
        websites = [url for href in raw.links if (url := _normalize_url(href))]

        parsed.append(
            Exhibition(
                title=title,
                start=start,
                end=end,
                organizer=organizer,
                website=websites[0] if websites else None,
                details=details,
                source_url=source_url,
            )
        )
    return parsed


def add_months(value: date, delta: int) -> date:
    index = value.year * 12 + value.month - 1 + delta
    return date(index // 12, index % 12 + 1, 1)


def month_range(anchor: date, months_back: int, months_ahead: int) -> list[str]:
    first = date(anchor.year, anchor.month, 1)
    return [
        add_months(first, offset).strftime("%Y-%m")
        for offset in range(-months_back, months_ahead + 1)
    ]


def fetch_page(url: str, timeout: float, retries: int = 3) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="strict")
        except (urllib.error.URLError, TimeoutError, UnicodeError) as error:
            last_error = error
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"抓取失败：{url}: {last_error}") from last_error


def fetch_exhibitions(
    months: Iterable[str], timeout: float = 20, pause: float = 0.25
) -> list[Exhibition]:
    months = list(months)
    events: list[Exhibition] = []
    for index, month in enumerate(months):
        url = SOURCE_TEMPLATE.format(month=month)
        page = fetch_page(url, timeout=timeout)
        events.extend(parse_schedule(page, url))
        if pause and index + 1 < len(months):
            time.sleep(pause)
    return deduplicate(events)


def deduplicate(events: Iterable[Exhibition]) -> list[Exhibition]:
    unique: dict[tuple[str, date, date], Exhibition] = {}
    for event in events:
        key = (re.sub(r"\s+", "", event.title).casefold(), event.start, event.end)
        existing = unique.get(key)
        if existing is None or (not existing.website and event.website):
            unique[key] = event
    return sorted(unique.values(), key=lambda item: (item.start, item.title))


def escape_ical_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


def fold_ical_line(line: str) -> list[str]:
    """Fold an iCalendar content line to at most 75 UTF-8 octets."""
    folded: list[str] = []
    current = ""
    prefix = ""
    for char in line:
        candidate = prefix + current + char
        if current and len(candidate.encode("utf-8")) > 75:
            folded.append(prefix + current)
            prefix = " "
            current = char
        else:
            current += char
    folded.append(prefix + current)
    return folded


def _uid(event: Exhibition, duplicate_identities: set[str]) -> str:
    identity = event.identity()
    if identity in duplicate_identities:
        identity += "|" + event.start.isoformat()
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"sniec-{event.start.year}-{digest}@sniec-calendar.local"


def build_ics(events: Iterable[Exhibition], generated_at: datetime | None = None) -> str:
    items = deduplicate(events)
    generated_at = generated_at or datetime.now(timezone.utc)
    stamp = generated_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    identity_counts: dict[str, int] = {}
    for event in items:
        identity_counts[event.identity()] = identity_counts.get(event.identity(), 0) + 1
    duplicate_identities = {key for key, count in identity_counts.items() if count > 1}

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//sniec-calendar//SNIEC Exhibition Calendar//ZH-CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ical_text('上海新国际博览中心展会日历')}",
        f"X-WR-CALDESC:{escape_ical_text('SNIEC 官方展会日程的非官方订阅日历')}",
        "X-WR-TIMEZONE:Asia/Shanghai",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]

    for event in items:
        description_parts = []
        if event.details:
            description_parts.append(event.details)
        elif event.organizer:
            description_parts.append(f"主办：{event.organizer}")
        description_parts.extend(["", f"数据来源：{event.source_url}", f"更新时间：{stamp}"])

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{_uid(event, duplicate_identities)}",
                f"DTSTAMP:{stamp}",
                f"LAST-MODIFIED:{stamp}",
                f"DTSTART;VALUE=DATE:{event.start.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(event.end + timedelta(days=1)).strftime('%Y%m%d')}",
                f"SUMMARY:{escape_ical_text(event.title)}",
                f"LOCATION:{escape_ical_text(LOCATION)}",
                f"DESCRIPTION:{escape_ical_text(chr(10).join(description_parts))}",
                "CATEGORIES:展览,上海,SNIEC",
                "TRANSP:TRANSPARENT",
            ]
        )
        if event.website:
            lines.append(f"URL:{event.website}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in fold_ical_line(line)) + "\r\n"


def write_json(events: Iterable[Exhibition], output: Path, generated_at: datetime) -> None:
    payload = {
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "source": "https://www.sniec.net/cn/visit_exhibition.php",
        "events": [
            {
                **asdict(event),
                "start": event.start.isoformat(),
                "end": event.end.isoformat(),
            }
            for event in deduplicate(events)
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从 SNIEC 官方展会日程生成 Apple/Google/Outlook 可订阅的 ICS 日历"
    )
    parser.add_argument("--months-back", type=int, default=1, help="包含过去几个月（默认 1）")
    parser.add_argument("--months-ahead", type=int, default=12, help="抓取未来几个月（默认 12）")
    parser.add_argument("--timeout", type=float, default=20, help="单次请求超时秒数")
    parser.add_argument("--pause", type=float, default=0.25, help="月份请求之间的礼貌间隔")
    parser.add_argument("--out", default="sniec.ics", help="ICS 输出路径")
    parser.add_argument("--json-out", help="可选的 JSON 输出路径")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.months_back < 0 or args.months_ahead < 0:
        print("months-back 和 months-ahead 不能为负数", file=sys.stderr)
        return 2

    months = month_range(date.today(), args.months_back, args.months_ahead)
    try:
        events = fetch_exhibitions(months, timeout=args.timeout, pause=args.pause)
    except (RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    if not events:
        print("没有解析到任何展会，保留上一次部署并终止本次生成", file=sys.stderr)
        return 1

    generated_at = datetime.now(timezone.utc)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(build_ics(events, generated_at).encode("utf-8"))
    if args.json_out:
        write_json(events, Path(args.json_out), generated_at)

    print(f"已生成 {output}：{len(events)} 场展会，覆盖 {months[0]} 至 {months[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
