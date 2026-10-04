# 台股選股研究 v19

新增 `paid_rights_evidence_v19.csv`、`dividend_evidence_v19.csv`、`dividend_revisions_v19.csv`、`raw_replay_v19.py`、測試與 `output_research_v19/`。進度、來源及下一步見 `research_report_2025_v19.md`；根目錄規格檔保留全部歷版。

解壓縮後安裝 `twse_history/requirements_research_v4.txt`，在根目錄執行：

```bash
python3 -m twse_history.raw_replay_v19
python3 -m unittest discover -s . -p 'test_*.py'
```

4557 基準帳採放棄付費認購，6768 使用除息前修正比率。四組合首次未解持股事件後不產出有效 NAV。
