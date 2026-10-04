# 台股飆股研究：公司行動盤點與 0050 現金帳 v6

接續 v5 的 2025 模型與合併權益紀錄，本版重播成交以盤點持股遭遇的公司行動，並獨立重算 0050 的實股、分割、應收與實際發放現金。其他選股策略仍採 v5 的還原價格代理。方法與結果詳見 `twse_history/research_report_2025_v6.md`。

## 離線重現

在解壓縮後的根目錄，使用 Python 3.10+：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r twse_history/requirements_research_v4.txt
python -m unittest discover -s twse_history -t . -p 'test_*.py' -q
python -m twse_history.research_cash_v6
```

本包包含 v3 原始行情和官方事件快照、v5 模型及交易輸出、v6 程式、測試與輸出。`held_corporate_actions_2025.csv` 是**持有事件盤點**，其中調整後單位換算不得視為實股或股利。`etf_0050_distribution_ledger.csv` 和 `etf_0050_daily_physical_nav.csv` 才是本階段實股現金帳，範圍僅 0050 買入持有。腳本中的兩筆 ETF 配息及分割條件有官方來源連結。

若從本工作目錄而非解壓縮包執行，改用：

```bash
python -m twse_history.research_cash_v6 --raw-quotes recovered/財務/quotes_twse_2025.csv.gz
```
