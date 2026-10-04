# 台股選股研究 v18

本版新增 `paid_rights_evidence_v18.csv`、`dividend_evidence_v18.csv`、`raw_replay_v18.py`、測試及 `output_research_v18/`。來源、Tasks 與下一步在 `research_report_2025_v18.md`；根目錄規格檔保留歷版進度。

解壓縮後安裝 `twse_history/requirements_research_v4.txt`，在根目錄執行：

```bash
python3 -m twse_history.raw_replay_v18
python3 -m unittest discover -s . -p 'test_*.py'
```

6806 採放棄付費認購情境；四組合首次未解持股事件後不產出有效 NAV。
