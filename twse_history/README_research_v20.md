# 台股選股研究 v20

本版加入 `paid_rights_evidence_v20.csv`、`dividend_evidence_v20.csv`、`dividend_revisions_v20.csv`、`raw_replay_v20.py`、測試及 `output_research_v20/`。進度、Tasks、來源和下一步見 `research_report_2025_v20.md`；根目錄規格檔保留歷版。

解壓縮並安裝 `twse_history/requirements_research_v4.txt` 後，在根目錄執行：

```bash
python3 -m twse_history.raw_replay_v20
python3 -m unittest discover -s . -p 'test_*.py'
```

6625 採放棄付費認購情境，其他三筆依公告記現金應收。首次未解持股事件後不產出有效 NAV。
