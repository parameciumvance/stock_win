# 台股選股與飆股研究（stock_win）

這是研究用 Python 專案，使用證交所免費歷史行情、普通股股票池與公司行動，建立「未來 20 個市場日最高還原價達訊號日收盤價 +30%」的分類排名，並探索未來 20 日相對 0050 報酬的預測。程式和報告保留原研究版本號，方便追溯每次新增的檢核。

**目前狀態（資料截至 2026-10-02）**：已採用 30 萬元虛擬本金、每月前 15 檔、預留 5% 現金的委託研究規則。分類輸出是**未校準分數**，不是可信的上漲機率；相對報酬預測的 `>0` 篩選僅作診斷，**尚未啟用**。缺少盤中零股逐日原始 CSV、實際成交／交付、部分公司權益和新的獨立市場期間，因此沒有可宣稱的組合 NAV 或實盤績效。

## 從哪裡開始

- [完整 Tasks 與研究規格](docs/taiwan_stock_ml_v1_spec.md)
- [資料取得與重建](docs/DATA_SETUP.md)；[輸入檔 SHA-256](docs/INPUT_CHECKSUMS.json)
- [免費月營收來源與公告時點決策](docs/MONTHLY_REVENUE_SOURCE_DECISION.md)；[公告時點接入](docs/DATA_SETUP.md#月營收的公告時點)；`twse_history/asof_revenue.py` 需真正公開時間及原始快照
- [2015–2023 波動基準長期壓力測試](deliverables/long_volatility_2015_2023_report.md)
- [2015–2026 全段共同建置與五筆邊界稽核](deliverables/long_history_2015_2026_report.md)
- [2015 年度與 2015–2016 跨年試點](deliverables/history_2015_acquisition_report.md)
- [2016 年度與 2016–2017 跨年試點](deliverables/history_2016_acquisition_report.md)
- [2017 年度與 2017–2018 跨年試點](deliverables/history_2017_acquisition_report.md)
- [2018 年度免費資料與股票池試點](deliverables/history_2018_acquisition_report.md)；[年度封存 SHA-256](docs/INPUT_CHECKSUMS.json)
- [2019 年度與 2019–2020 跨年試點](deliverables/history_2019_acquisition_report.md)
- [2020 年度與 2020–2021 跨年試點](deliverables/history_2020_acquisition_report.md)
- [2021 年度與 2021–2022 跨年試點](deliverables/history_2021_acquisition_report.md)
- [2022 年度與 2022–2023 跨年試點](deliverables/history_2022_acquisition_report.md)
- [30 萬元 Top 15 委託與資金檢核](deliverables/top15_300k_order_funding_report_2026_v75.md)
- [相對報酬模型與零股來源檢核](deliverables/relative_return_and_oddlot_report_2026_v78.md)

## 目錄

- `twse_history/`：官方資料下載、歷史股票池、公司行動還原、標籤、模型、交易及權益帳的版本化程式與測試。
- 根目錄的 `audit_*.py`：後續年度、流動性、月度名單、權益、30 萬元委託及預測門檻的稽核工具。
- `deliverables/`：文字報告、摘要與較小的逐筆 CSV。它們是**研究輸出**；舊版代理報酬不可視為可交易績效。
- `docs/`：研究規格和輸入重建說明。

## 開發環境與核對

Python 3.10 以上；本次使用 Python 3.12。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r twse_history/requirements_research_v4.txt
python -m unittest twse_history.test_history twse_history.test_multiyear -v
```

這次 v79–v81 診斷可先 `make test-diagnostics`；將三份上游大檔依 [資料說明](docs/DATA_SETUP.md)放入相應路徑後，執行 `make check-diagnostic-inputs` 核對[大小與 SHA-256](docs/DIAGNOSTIC_INPUTS.json)，再用 `make diagnostics` 依序重算。缺少或不符時命令會停止，不會用另一版快照冒充封存結果。

WSL2 Ubuntu 可直接使用；Windows PowerShell 啟用環境請改用 `.venv\Scripts\Activate.ps1`。大量研究重算須先依 `docs/DATA_SETUP.md` 放入來源快取與年度行情。部分舊版程式會檢查特定快取與 SHA-256，應使用匹配版本的資料，不要用新抓資料冒充當時快照。

## 最新研究流程

在來源檔已備妥後，以下程式依序重建分類分數、Top 15 委託、資金閘門及相對報酬模型：

```bash
python evaluate_2026_fixed_v57.py
python audit_monthly_bridge_2026_v61.py
python audit_complete_monthly_2026_v62.py
python audit_top15_300k_selections_v74.py
python audit_top15_300k_funding_v75.py
python audit_relative_return_model_v76.py
python audit_relative_return_tree_v77.py
python audit_relative_gate_history_v78.py
```

各步驟會讀取前步驟的輸出及 `twse_history/output_multiyear_2023_2026_asof_20261002/`；若從空白 checkout 重建，還需執行 `docs/DATA_SETUP.md` 所列的先行建置。這些腳本不會下真實訂單。

## 最新對照

[波動排序與先觸及標籤](deliverables/volatility_and_entry_barriers_report_2026_v81.md)顯示只看波動已接近舊飆股命中率，三年次日開盤進場與成本後的前 10% 報價代理均值仍為負。這是日線研究代理，尚無可成交 NAV。[優先序與 Tasks](docs/RESEARCH_PRIORITIES.md)整理後續方向。

## 下一步

已完成 2015–2026（截至 10/02）上市行情、普通股池與全段共同因子建置，另備妥月營收時點對齊工具。接著須補逐公司原始公告時間，才能測試對次日開盤與固定持有相對報酬的增量價值。事先固定方法，等新的市場期間再評估。2026 年九個換股日的官方盤中零股 CSV 與精確持股現金帳暫列後續工作；每日市場價量也不能證明限價單必然成交。


## 2024 法人增量診斷

固定模型結果見 [2024 比較](deliverables/institutional_increment_report_2024.md)；
接續的 [月度與區塊不確定性](deliverables/institutional_uncertainty_report_2024.md)
使用同一每日結果，不重新訓練。`make institutional-uncertainty` 可由 repo 內的
每日 CSV 重算，無需下載新的市場資料。`make test-institutional` 現含 26 項測試。
2024 原始資料包已收到並完成來源重跑，見 [重跑核對](deliverables/institutional_source_replay_20261009.json)。
[股票池篩選檢查](deliverables/institutional_pool_audit_report_2024.md)
可用 `make institutional-pool-audit` 重算；沒有將未知持股結果補零。
2025 延伸設定已固定；接續命令與資料包依賴見 [接續說明](docs/INSTITUTIONAL_RESUME.md)。
