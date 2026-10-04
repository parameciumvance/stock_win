# 台股飆股研究：2025 合併權益修正 v5

在 2024 訓練、2025 留出回測中，三起實際持有的合併股票依官方條件換成接續股票及現金。完整結果與限制見 `twse_history/research_report_2025_v5.md`。選股和模型分數與 v4 相同，組合估值仍採參考價及小數持股代理。

## 離線重現

在解壓縮後的根目錄執行（Python 3.10+）：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r twse_history/requirements_research_v4.txt
python -m unittest discover -s twse_history -t . -p 'test_*.py' -q
python -m twse_history.research_v5
python -m twse_history.make_research_report_v5
```

包內含 2024–2025 原始資料與 v3 官方來源快照、2025 每日報價、可重現腳本和本次完整輸出。`inputs/quotes_twse_2025.csv.gz` 的 2887I 特別股報價只供換股對價估值；`twse_history/output_multiyear/prices_adjusted_2024_2025.csv.gz` 的普通股候選沒有混入它。每筆轉換比例及來源連結寫在程式常數、摘要與報告中。

若從本工作目錄直接執行，輸入報價改用：

```bash
python -m twse_history.research_v5 --raw-quotes recovered/財務/quotes_twse_2025.csv.gz
```

輸出的 `merger_rights_ledger.csv` 記錄生效日、原持股單位、換得股數、現金稅額及來源；`comparison_v4_v5.csv` 對照每種組合。完整股息、減資現金流、實際零股結算、委託簿與多年度驗證尚未完成。
