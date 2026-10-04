# 台股選股研究 v17

新增 `dividend_evidence_v17.csv`、`dividend_revisions_v17.csv`、`paid_rights_evidence_v17.csv`、`raw_replay_v17.py`、測試與 `output_research_v17/`。逐筆公告來源、Tasks 和下一步在 `research_report_2025_v17.md`；根目錄規格檔保留歷版進度。

解壓縮後安裝 `twse_history/requirements_research_v4.txt`，在根目錄執行：

```bash
python3 -m twse_history.raw_replay_v17
python3 -m unittest discover -s . -p 'test_*.py'
```

6024 採明確的放棄付費認購情境；1786 使用除息前修正的每股現金率。首次未解持股事件之後不產出有效 NAV，後續成交僅供條件式診斷。
