# 台股飆股研究：持股股利證據與核對清單 v7

本版承接 v6 的 2025 持股公司行動盤點，對純除息事件加入有來源連結的每股金額和付款日期，輸出下一批核對順序。九個事件有證據，尚有 512 個不同的持股純除息事件待查。研究方法、限制與 Tasks 見 `twse_history/research_report_2025_v7.md`。

## 離線重現

在解壓縮後的根目錄，使用 Python 3.10+：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r twse_history/requirements_research_v4.txt
python -m unittest discover -s twse_history -t . -p 'test_*.py' -q
python -m twse_history.dividend_priority_v7
```

`twse_history/dividend_evidence_v7.csv` 可加入新查得的除息條件。程式重建 `output_research_v7/` 下的證據對照、持股交集與排序清單；參考價缺口僅用於資料蒐集排序，不會更動已保存的代理績效或任何實股現金帳。新聞網站轉載的重大訊息標為 `mops_republication`，不能冒充直接取得的官方來源。

本包還包括 v3 原始行情和事件快照、v5 模型及交易輸出、v6 的 0050 獨立實股現金帳。四個選股組合仍無一致的原始實股和權益現金帳，故不得把本版證據條件當作已計算的策略總報酬。
