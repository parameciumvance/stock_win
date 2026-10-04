# 台股選股研究 v21

此版保存 2025 封存訊號的原價、持股權益重播，以及新增 25 筆現金除息、2 筆放棄付費認購和 4 筆事前金額修正。逐筆來源、Tasks、有效範圍與待決策事項見 `research_report_2025_v21.md`；根目錄規格檔保存歷版。

安裝 `twse_history/requirements_research_v4.txt` 後，在解壓根目錄執行：

```bash
python3 -m twse_history.raw_replay_v21
python3 -m unittest discover -s . -p 'test_*.py'
```

AMAX-KY 6933 的境外股利扣繳口徑未定，仍為未解事件；不可從本版生成全年有效 NAV。未解事件後的交易僅是條件式診斷。
