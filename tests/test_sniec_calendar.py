from __future__ import annotations

import re
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from sniec_calendar import (
    Exhibition,
    build_ics,
    deduplicate,
    fold_ical_line,
    month_range,
    parse_schedule,
)


FIXTURE = Path(__file__).parent / "fixtures" / "schedule.html"
SOURCE = "https://www.sniec.net/cn/visit_exhibition.php?month=2026-08"


class ParseScheduleTests(unittest.TestCase):
    def test_parses_official_schedule_shape(self) -> None:
        events = parse_schedule(FIXTURE.read_text(encoding="utf-8"), SOURCE)

        self.assertEqual(3, len(events))
        self.assertEqual("人工智能产业大会暨展览会", events[0].title)
        self.assertEqual(date(2026, 8, 12), events[0].start)
        self.assertEqual(date(2026, 8, 14), events[0].end)
        self.assertEqual("测试展览（上海）有限公司", events[0].organizer)
        self.assertEqual("https://example.com/ai", events[0].website)
        self.assertNotIn("跨月测试展", events[0].details)
        self.assertEqual("https://www.example.org/expo", events[1].website)
        self.assertIsNone(events[2].website)

    def test_rejects_changed_page_shape(self) -> None:
        with self.assertRaisesRegex(ValueError, "#upcom"):
            parse_schedule("<html><body>empty</body></html>", SOURCE)


class CalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.event = Exhibition(
            title="一场很长的中文展览会，包含人工智能、机器人与创新技术",
            start=date(2026, 8, 12),
            end=date(2026, 8, 14),
            organizer="测试主办方",
            website="https://example.com/register",
            details="主办：测试主办方 电话：021-12345678",
            source_url=SOURCE,
        )
        self.generated_at = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)

    def test_generates_all_day_event_with_exclusive_end(self) -> None:
        ics = build_ics([self.event], self.generated_at)

        self.assertIn("DTSTART;VALUE=DATE:20260812", ics)
        self.assertIn("DTEND;VALUE=DATE:20260815", ics)
        self.assertIn("URL:https://example.com/register", ics)
        self.assertTrue(ics.endswith("\r\n"))

    def test_uid_survives_move_within_same_year(self) -> None:
        moved = Exhibition(
            **{
                **self.event.__dict__,
                "start": date(2026, 9, 2),
                "end": date(2026, 9, 4),
            }
        )
        first_uid = re.search(r"^UID:(.+)$", build_ics([self.event]), re.M)
        moved_uid = re.search(r"^UID:(.+)$", build_ics([moved]), re.M)

        self.assertIsNotNone(first_uid)
        self.assertIsNotNone(moved_uid)
        self.assertEqual(first_uid.group(1), moved_uid.group(1))

    def test_content_lines_do_not_exceed_75_utf8_octets(self) -> None:
        ics = build_ics([self.event], self.generated_at)
        for line in ics.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, line)

    def test_fold_line_preserves_content(self) -> None:
        original = "SUMMARY:" + "展览" * 50
        folded = fold_ical_line(original)
        reconstructed = folded[0] + "".join(part[1:] for part in folded[1:])
        self.assertEqual(original, reconstructed)

    def test_deduplicates_same_cross_month_event(self) -> None:
        duplicate = Exhibition(**self.event.__dict__)
        self.assertEqual([self.event], deduplicate([self.event, duplicate]))

    def test_month_range_crosses_year_boundary(self) -> None:
        self.assertEqual(
            ["2026-11", "2026-12", "2027-01", "2027-02"],
            month_range(date(2026, 12, 8), months_back=1, months_ahead=2),
        )


if __name__ == "__main__":
    unittest.main()
