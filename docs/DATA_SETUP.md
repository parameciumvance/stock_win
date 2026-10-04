# 來源資料與重算邊界

此 repo 保存程式、檢核表、報告及小型表格。大體積的原始證交所回應、年度行情、還原價格、標籤、模型二進位檔及重複打包的 ZIP 不放入 Git；這些檔案的取得時間與內容影響重現。它們仍需保存在本機或個人的資料封存處。

## 研究用輸入

將對應年度的行情檔放在 `inputs/`：

- `quotes_twse_2023.csv.gz`
- `quotes_twse_2024.csv.gz`
- `quotes_twse_2025.csv.gz`
- `quotes_twse_2026_asof_20261002.csv.gz`

已封存的 `twse_raw_2023.zip` 和 `twse_raw_2026_asof_20261002.zip` 內含相對於專案根目錄的 `data/raw/`、`twse_history/raw/` 和 metadata 路徑；2023 ZIP 亦含年度行情。解壓縮前請核對檔案內容及 [SHA-256 清單](INPUT_CHECKSUMS.json)。2024／2025 的原始快取可依 `twse_history/README_multiyear.md` 與歷史版本的來源封存補齊；不要把現在下載的欄位或公告版本假稱為舊快照。

若自行從官方網站重新下載，資料取得命令範例：

```bash
python -m twse_history.fetch_quotes --year 2024 --workers 2 --delay 3
python -m twse_history.fetch_history --year 2024 --quotes inputs/quotes_twse_2024.csv.gz
```

下載器會保存 URL、取得時間與 SHA-256；日期未齊不產生完整年度行情。重建跨年價格時先合併**原始**行情，再共同累積調整因子，不能拼接逐年各自調整後的價格。詳細參數和特殊公司行動補證見 `twse_history/README_multiyear.md` 和規格。

## 封存結果與依賴順序

`audit_relative_return_model_v76.py` 等腳本期待：

- `twse_history/output_multiyear_2023_2026_asof_20261002/` 中的 `prices_adjusted_2023_2026.csv.gz`、`surge_labels_adjusted_2023_2026.csv.gz`、`temporal_split_2023_2026.csv.gz`；
- `deliverables/holdout_scores_2026_v57.csv.gz` 與 `deliverables/crossyear_scores_v55.csv.gz` 等較大的上游模型分數；
- `deliverables/top15_300k_selections_2026_v74.csv` 等本 repo 的小型中繼結果。

這些大型上游檔案在原研究封存／本機工作目錄中；可用 `twse_history.build_multiyear`、`crossyear_research_2023_2025_v55.py`、`evaluate_2026_fixed_v57.py` 等版本化程式重算。若缺乏匹配的原始快取，舊期數字只能查閱報告，不能宣稱已從本 repo 的空白 checkout 重現。

## 盤中零股與界線

證交所[盤中零股交易行情單](https://www.twse.com.tw/zh/trading/historical/twtc7u.html)可按日期查詢並下載 CSV。研究需 2026-01-02、02-02、03-02、04-01、05-04、06-01、07-01、08-03、09-01 九日資料。取得後先保存原始檔、URL、時間及 SHA-256，核對欄位和代號覆蓋率；每日市場成交價量不等於我方委託已撮合。若缺檔則維持成交與現金帳未知。
