# 台股選股研究 v15

新增 `dividend_evidence_v15.csv`、`dividend_revisions_v15.csv`、`paid_rights_evidence_v15.csv`、`raw_replay_v15.py`、`paid_subscription_scenario_v15.py`、測試及 `output_research_v15/`。逐筆來源與 Tasks 見 `research_report_2025_v15.md`；根目錄規格檔保存歷版進度。

解壓縮後安裝 `twse_history/requirements_research_v4.txt`，在根目錄執行：

```bash
python3 -m twse_history.raw_replay_v15
python3 -m unittest discover -s . -p 'test_*.py'
```

`output_research_v15/summary.json` 記首個缺口與輸入雜湊。付費認購試算與四組合帳本隔離，尚未找到交付日期的權利只回報待交付狀態，不能用於 NAV。
