# 台股選股研究 v22

本版在原有 2025 封存訊號上增補 AMAX-KY 30% 扣繳壓力情境、6919 面額換股、19 筆現金除息、1 筆付費認購權放棄與 5 筆配息率修正。詳見 `research_report_2025_v22.md`、根目錄規格檔及證據 CSV。

在解壓根目錄安裝 `twse_history/requirements_research_v4.txt` 後：

```bash
python3 -m twse_history.raw_replay_v22
python3 -m unittest discover -s . -p 'test_*.py'
```

四策略 2025 全年 NAV 仍未完成；首個未解事件之後的交易是條件式診斷，不能視作真實績效。小數股研究帳不代表券商整股及股利實際捨入。
