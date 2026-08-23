# sniec-calendar

把上海新国际博览中心（SNIEC，龙阳路）的官方展会日程转换成 Apple 日历、Google Calendar 和 Outlook 可订阅的 iCalendar feed。

> 非官方社区项目，与上海新国际博览中心及各展会主办方无隶属或合作关系。

## 功能

- 从 [SNIEC 官方展会日程](https://www.sniec.net/cn/visit_exhibition.php)按月读取活动；
- 生成标准 `.ics` 全天事件，正确处理 iCalendar 排他性结束日期；
- 展会改期时尽量保持 UID 不变，跨月活动自动去重；
- 收录主办方、展会网站、官方来源和更新时间；
- 纯 Python 标准库，无第三方依赖；
- GitHub Actions 每 12 小时刷新，GitHub Pages 提供固定订阅 URL；
- 同步生成 `events.json`，方便二次开发。

## 本地运行

需要 Python 3.10 或更高版本：

```bash
python3 sniec_calendar.py
```

默认读取上个月到未来 12 个月，生成 `sniec.ics`。也可以指定输出：

```bash
python3 sniec_calendar.py \
  --months-back 0 \
  --months-ahead 6 \
  --out public/sniec.ics \
  --json-out public/events.json
```

## 部署为订阅日历

1. 在 GitHub 新建仓库，把本项目推送进去。
2. 打开仓库的 **Settings → Pages**，将 Source 设为 **GitHub Actions**。
3. 在 **Actions** 页面手动运行一次 `Refresh SNIEC calendar`。
4. 订阅地址为：

   ```text
   https://<你的用户名>.github.io/<仓库名>/sniec.ics
   ```

部署后的首页提供一键订阅、复制地址和下载 `.ics`。

### Apple 日历

在 iPhone/iPad 中进入“日历 → 日历 → 添加日历 → 添加订阅日历”，粘贴 HTTPS 地址并选择 iCloud 账户。Mac 可使用“文件 → 新建日历订阅”。

Google Calendar 和 Outlook 也支持通过 URL 订阅 ICS。不同客户端的刷新时间由客户端控制，不保证官网更新后立即显示。

## 数据与更新策略

```text
SNIEC HTML → 定时抓取 → 解析与去重 → sniec.ics / events.json → GitHub Pages
```

- 默认只低频读取公开页面，每个月份请求之间保留礼貌间隔。
- 任一页面结构异常、网络失败或最终零事件时，生成任务失败；GitHub Pages 会继续保留上一次成功版本，避免发布空日历。
- 官网通常只提供展期，日历因此使用全天事件。开放时间、展馆号、门票和观众登记请点击事件中的展会官网确认。
- UID 由“展会年份 + 标准化名称”生成，同一年内改期不会制造重复事件；同名多场活动会自动加入日期消歧。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖页面解析、页面结构异常、跨月去重、稳定 UID、全天事件结束日期以及 UTF-8 ICS 行折叠。

## 使用边界

本项目仅提供公开信息的技术转换，不保证信息完整、实时或准确。请以 [SNIEC 官网](https://www.sniec.net/)及主办方公告为准。

如果公开运营或商业化日历服务，请自行确认场馆网站条款、数据转载授权和当地法律要求。请勿提高抓取频率或绕过来源网站的访问限制。

## 致谢

部署形态参考了 [alwaysday1/weather-ics](https://github.com/alwaysday1/weather-ics)：使用零依赖 Python 生成 ICS，并通过 GitHub Actions + GitHub Pages 提供稳定订阅地址。本项目的展会解析、去重、测试和页面实现为独立代码。

## License

[MIT](LICENSE)
