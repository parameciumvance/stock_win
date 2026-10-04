# 台股選股研究 v14

本版新增 `dividend_evidence_v14.csv`、`dividend_revisions_v14.csv`、`raw_replay_v14.py`、專項測試及 `output_research_v14/`。四筆持股純除息處理和下一步任務見 `research_report_2025_v14.md`，根目錄 `taiwan_stock_ml_v1_spec.md` 保存歷版進度。封存檔含歷史原始資料、腳本及 v13、v14 輸出。

在解壓縮根目錄安裝 `twse_history/requirements_research_v4.txt` 後執行：

```bash
python3 -m twse_history.raw_replay_v14
python3 -m unittest discover -s . -p 'test_*.py'
```

摘要見 `output_research_v14/summary.json`。首次未解持股事件後的委託僅為診斷，四個模型帳本均未提供 2025 全年有效淨值。
