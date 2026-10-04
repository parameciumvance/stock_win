# 台股飆股研究：高優先度除息與修正紀錄 v8

本版接續 v7，核對排序前 20 個持股純除息事件的現金與付款條件，其中 11 個為新補資料。新增 `dividend_revisions_v8.csv` 記錄 4 筆除息前配息率修正。方法、來源及 Tasks 詳見 `twse_history/research_report_2025_v8.md`。

## 離線重現

在解壓縮後的根目錄，使用 Python 3.10+：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r twse_history/requirements_research_v4.txt
python -m unittest discover -s . -p 'test_*.py' -q
python -m twse_history.dividend_priority_v8
```

可繼續將查得條件追加至 `twse_history/dividend_evidence_v8.csv`；若發現初始條件有公開修正，同時更新 `twse_history/dividend_revisions_v8.csv`。程式檢查修正值、公開日期及來源一致性，輸出 `twse_history/output_research_v8/`。涉及重大訊息的新聞網站頁面標為轉載；並非直接取得 MOPS 原件。

20 個事件覆蓋 58 筆持股交集，另 501 個事件仍待核對。本版不把還原價參考缺口當現金、不更動 v5 四組合代理淨值；只有 v6 的 0050 實股帳維持先前可用範圍。
