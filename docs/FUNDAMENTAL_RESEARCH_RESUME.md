# 免費基本面與籌碼研究的復原及重跑

月營收嚴格首次公告時間／修訂軌跡仍 pending；本輪採用月底後 45 日固定延遲靜態代理，60 日只作已固定敏感度。融資融券只使用前市場日來源，不補缺列。2024–2026 都已研究，不能稱新的獨立留出。

## 資料依賴

先依 `docs/INSTITUTIONAL_RESUME.md` 復原凍結的 2023–2026 還原價格、歷史普通股池、官方日曆及四年度法人來源／特徵。價格與股票池 hash 在各研究配置／來源報告中核對；法人 gzip 可重建，但只有解壓 CSV 的預先固定 hash 完全相符才接受。

解壓 `monthly_revenue_proxy_2022_2026_source_checkpoint.zip` 到 repo 根目錄，保留其 `inputs/revenue_proxy/` 結構；亦可依 `docs/REVENUE_PROXY.md` 從官方快取重建。該包包含 110 份原始 HTML 與原始月表、延遲代理特徵和營收研究選股明細。

解壓四份 `margin_twse_2023_source_checkpoint.zip` 至 `margin_twse_2026_asof_20261002_source_checkpoint.zip` 到 repo 根目錄。每份含 `inputs/margin/raw_年度/`、年度 CSV、日曆快取、來源摘要及 SHA256MANIFEST；2026 截止 10/02。根目錄同名 manifest／SOURCE_SUMMARY 可分別留在年度來源包內，以免互相覆蓋。來源包的資料可重算 `deliverables/margin/acquisition_年度.json`：

```bash
python3 -m twse_history.margin --year 2023
python3 -m twse_history.margin --year 2024
python3 -m twse_history.margin --year 2025
python3 -m twse_history.margin --year 2026 --asof 2026-10-02
```

所有必需市場日完整、schema／餘額／來源 hash 通過後才寫年度模型输入。若需補缺，只向官方取得免費資料，可加 `--fetch --max-new-days 40` 分批執行；直到狀態不再是 partial 才建模。

## 固定模型及明細核對

Python 依賴為 numpy、pandas、scikit-learn、joblib、threadpoolctl 及既有抓取解析依賴；本輪 sklearn 1.8.0。模型配置存於 `configs/margin_protocol.json` 和 `configs/fundamental_tree_protocol.json`，沒有參數搜尋。由乾淨 checkout 復原上述大檔後，依序執行：

```bash
make test-institutional test-revenue-proxy test-margin
python3 audit_margin_increment.py --year 2024
python3 audit_margin_increment.py --year 2025
python3 audit_margin_increment.py --year 2026
python3 audit_fundamental_tree.py --year 2024
python3 audit_fundamental_tree.py --year 2025
python3 audit_fundamental_tree.py --year 2026
make research-selection-audit
python3 package_fundamental_traces.py
```

Ridge 每年度會生成有 hash 的本地共同矩陣快取；若只需重建矩陣而保留既有 Ridge 結果，使用 `--prepare-only --year 年度`，或 `make fundamental-tree YEAR=年度`。快取只保存自產資料，不能載入不可信 pickle。快取與 gzip 的封装 bytes 可因執行細節改變，重跑以實際來源 hash、相同訓練／測試列數、Ridge 每日重播與模型結果數值為準，不將封裝 hash 差異冒充資料變更。

`fundamental_research_2024_2026_traces.zip` 保存六份當時 Top10% 明細及九個可信梯度樹模型；小型結果、係數、配置與程式保留於 Git。只需要核對既有結果時，把該包解壓到根目錄後執行 `make research-selection-audit`，不必重訓。joblib／pickle 只能從可信且 hash 已核對的自產檔載入。

來源包 hash 見 `deliverables/margin/checkpoint_年度.json`，研究明細包 hash 見 `deliverables/fundamental_tree/trace_checkpoint.json`。成本後平均相對端點代理不是年度 NAV，不保證可成交；未知選中端點保留、整組均值未知，不補零。
