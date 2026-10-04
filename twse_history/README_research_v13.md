# 台股選股研究 v13

v13 新增 `dividend_evidence_v13.csv`、`paid_rights_evidence_v13.csv`、`raw_replay_v13.py`、兩項專項測試及 `output_research_v13/`。以前版本與原始資料在同一封存檔，研究決策與來源詳見 `research_report_2025_v13.md`，總規格見根目錄 `taiwan_stock_ml_v1_spec.md`。

在解壓縮根目錄安裝 `twse_history/requirements_research_v4.txt` 後執行：

```bash
python3 -m twse_history.raw_replay_v13
python3 -m unittest discover -s . -p 'test_*.py'
```

輸出 `summary.json`、`held_action_audit.csv`、`raw_order_diagnostics.csv` 與 `daily_accounting_status.csv`。首次未解持股事件後的委託僅是診斷，帳本不提供全年模型淨值。
