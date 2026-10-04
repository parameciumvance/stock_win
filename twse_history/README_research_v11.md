# 台股 ML 選股研究 v11

在 v10 的原價成交重播上，新增三件現金增資舊股東認購權的可追溯證據，預設明確採「放棄認購」情境。保留歷史 v10 檔案，不對有未解權益之後的條件式委託宣稱全年績效。

```bash
python -m twse_history.raw_replay_v11
python -m unittest discover -s twse_history -t . -p 'test_*.py'
```

詳見 `twse_history/research_report_2025_v11.md` 的 Tasks、公告來源、限制與下一步規劃。v11 結果置於 `twse_history/output_research_v11/`，輸入雜湊見 `summary.json`。
