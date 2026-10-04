# 台股選股研究 v24

延續原全市場股票池與封存訊號，新增 12 筆當時可得的現金除息、1519／2250 複合股利及 2364 免費配股。請先讀 `research_report_2025_v24.md` 的 Tasks、來源和未解權益；`output_research_v24/summary.json` 記錄輸入 SHA-256 與回放邊界。

解壓後依 `twse_history/requirements_research_v4.txt` 安裝套件，從根目錄執行：

```bash
python3 -m twse_history.raw_replay_v24
python3 -W ignore::ResourceWarning -m unittest discover -s . -p 'test_*.py' -q
```

本研究帳允許規格化小數股，不代表券商交付、每戶股利捨入或競價排隊。權利證書的獨立行情尚未齊全，全年四組合 NAV 和 Alpha 仍未產出。
