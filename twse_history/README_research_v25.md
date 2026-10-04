# 台股選股研究 v25

本版由已持久保存的 v24 恢復，重核 25 筆現金股利。先讀 `research_report_2025_v25.md` 的 Tasks 和恢復邊界；`output_research_v25/summary.json` 記錄輸入 SHA-256。

解壓後依 `twse_history/requirements_research_v4.txt` 安裝套件，從根目錄執行：

```bash
python3 -m twse_history.raw_replay_v25
python3 -m twse_history.raw_replay_v22
python3 -W ignore::ResourceWarning -m unittest discover -s . -p 'test_*.py' -q
```

v22 輸出需重算是因 v24 封存包未含該結果目錄，測試會用它。後段股息來源齊全仍不代表中段及權利證書缺口已解；本版沒有全年實股績效。
