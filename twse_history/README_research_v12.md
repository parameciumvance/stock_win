# 台股 ML 選股研究 v12

1316 與 6854 現金增資認購條件加入來源及當時可得日期；沿用 v11 明確不認購情境。6854 每千股率在公告中屬暫定，記錄於稽核欄，不入新股。其餘缺權益後的重播仍只是條件路徑。

```bash
python -m twse_history.raw_replay_v12
python -m unittest discover -s twse_history -t . -p 'test_*.py'
```

Tasks、來源和下一步見 `twse_history/research_report_2025_v12.md`；輸出與輸入 SHA-256 見 `twse_history/output_research_v12/`。
