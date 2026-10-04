# 台股研究：現金條件與實股帳骨架 v9

接續 v8，累積 27 個持股純除息事件有來源條件，另以 0050 驗證原始股數、應收和實收現金帳的逐日計算。四個股票策略仍是 v5 還原價代理，不是實股績效。詳細來源、Tasks、限制與下一步見 `twse_history/research_report_2025_v9.md`。

## 離線重現

在解壓縮根目錄，使用 Python 3.10+：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r twse_history/requirements_research_v4.txt
python -m unittest discover -s . -p 'test_*.py' -q
python -m twse_history.dividend_priority_v9
python -m twse_history.physical_ledger_v9
```

`dividend_evidence_v9.csv` 接受新增公告條件，`dividend_revisions_v9.csv` 保存改率紀錄；兩個程式在 `output_research_v9` 輸出來源覆蓋率、待查清單與 0050 對帳。6768 仍未匯入精確現金。實股帳只以原始成交股數為輸入，不能把 v5 還原價委託的 `notional` 當成已成交原始股數。
