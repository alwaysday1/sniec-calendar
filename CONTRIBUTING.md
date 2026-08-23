# 参与贡献

欢迎提交 Issue 和 Pull Request，尤其是以下改进：

- 修复 SNIEC 官方页面结构变化导致的解析问题；
- 改善展会改名、改期和跨月去重；
- 增加不依赖私有密钥的数据源交叉校验；
- 改善 Apple、Google、Outlook 的兼容性。

提交前请运行：

```bash
python -m unittest discover -s tests -v
python sniec_calendar.py --months-back 0 --months-ahead 1 --out /tmp/sniec.ics
```

测试 fixture 应使用虚构或最小化数据，不要大段复制官方网页。
