# 台股選股研究 v16

新增 `dividend_evidence_v16.csv`、`paid_rights_evidence_v16.csv`、`raw_replay_v16.py`、測試及 `output_research_v16/`。逐筆來源、Tasks 和下一步見 `research_report_2025_v16.md`；根目錄規格檔保存歷版進度。

解壓縮後安裝 `twse_history/requirements_research_v4.txt`，在根目錄執行：

```bash
python3 -m twse_history.raw_replay_v16
python3 -m unittest discover -s . -p 'test_*.py'
```

2547 採放棄認購、每千股比率空值的明確研究情境。首個未解持有事件後停止產出有效 NAV；條件式後續成交不可視為可比較的全年績效。
