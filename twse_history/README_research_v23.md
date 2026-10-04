# 台股選股研究 v23

本版在 2025 封存訊號上增加 3665 美元股利事前匯率估值、3665／2836 免費配股應收與交付、6288→3717 承繼換股、13 筆現金證據和 4927 放棄付費認股情境。詳見 `research_report_2025_v23.md`、根目錄規格檔與 v23 證據 CSV。

在解壓根目錄安裝 `twse_history/requirements_research_v4.txt` 後執行：

```bash
python3 -m twse_history.raw_replay_v23
python3 -m unittest discover -s . -p 'test_*.py'
```

全年四策略 NAV 尚未完成。未解權益之後的交易僅是條件式診斷；本研究帳允許小數股，不代表券商整股與股利實際捨入。
