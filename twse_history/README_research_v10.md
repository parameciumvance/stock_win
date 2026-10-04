# 台股 ML 選股研究 v10

四個股票組合使用 v5 已保存的 12 個月訊號，改按原始開盤價、小數股及現金守恆重播。首次未核實權益後的交易只供資料缺口排查，不是實股帳或可比較績效。

```bash
python -m twse_history.raw_replay_v10
python -m unittest discover -s twse_history -t . -p 'test_*.py'
```

結果在 `twse_history/output_research_v10/`；完整 Tasks、方法、限制與下一步見 `twse_history/research_report_2025_v10.md`。原始股價、公司行動、月度訊號及來源的既有版本一併封存；輸入雜湊記於 `summary.json`。
