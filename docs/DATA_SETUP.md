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

v79–v81 的三份直接上游檔案已另列於 [DIAGNOSTIC_INPUTS.json](DIAGNOSTIC_INPUTS.json)。`make check-diagnostic-inputs` 先核對位元組數和 SHA-256；通過後 `make diagnostics` 才重算波動排名、次日開盤先觸及與區塊敏感性。此入口只覆蓋本次診斷，沒有把原始快取或 2023–2026 上游模型重建變成一鍵流程。

## 盤中零股與界線

證交所[盤中零股交易行情單](https://www.twse.com.tw/zh/trading/historical/twtc7u.html)可按日期查詢並下載 CSV。研究需 2026-01-02、02-02、03-02、04-01、05-04、06-01、07-01、08-03、09-01 九日資料。取得後先保存原始檔、URL、時間及 SHA-256，核對欄位和代號覆蓋率；每日市場成交價量不等於我方委託已撮合。若缺檔則維持成交與現金帳未知。

## 更早年度的上市行情

證交所[每日收盤行情](https://www.twse.com.tw/zh/trading/historical/mi-index.html)頁面列有較早歷史資料；**頁面有歷史不代表目前下載器已通過該年度的 JSON 欄位、公司分類與公司行動核對**。先挑 2015、2018、2020、2022 年，各自執行：

```bash
python -m twse_history.fetch_quotes --year 2018 --workers 1 --delay 3
python -m twse_history.fetch_history --year 2018 --quotes inputs/quotes_twse_2018.csv.gz
```

按年替換 `2018`；先核對 `health_twse_<year>.json`、完整日曆、原始回應與 `.meta.json` 的 SHA-256，再建立連續 2015–2026 的原始行情與公司行動。**不能只把 2015／2018／2020／2022 四個年份拼起來**：120 日量價特徵和 20 日標籤都依賴中間連續的交易日。重建時將所有年度原始行情共同傳入 `build_multiyear`，並複查跨年公司行動和股票池；各年度不能先獨立還原後拼接。

2026-10-05 已取得、驗證 2015–2022 八個完整年度。2015 年有 244 日、225,139 列，並與 2016 共用因子，見 [2015 試點報告](../deliverables/history_2015_acquisition_report.md)；2016 年有 244 日、233,286 列，並與 2017 共用因子，見 [2016 試點報告](../deliverables/history_2016_acquisition_report.md)；2017 年有 246 日、248,380 列，並與 2018 共用因子，見 [2017 試點報告](../deliverables/history_2017_acquisition_report.md)；2018 年有 247 日、260,823 列，見 [2018 試點報告](../deliverables/history_2018_acquisition_report.md)；2019 年有 242 日、265,503 列，並與 2020 共用因子，見 [2019 試點報告](../deliverables/history_2019_acquisition_report.md)；2020 年有 245 日、273,675 列，並與 2021 共用因子，見 [2020 試點報告](../deliverables/history_2020_acquisition_report.md)；2021 年有 244 日、276,705 列，並與 2022 共用因子，見 [2021 試點報告](../deliverables/history_2021_acquisition_report.md)；2022 年有 246 日、287,161 列，並與 2023 共用因子，見 [2022 試點報告](../deliverables/history_2022_acquisition_report.md)。年度封存包與行情的 SHA-256 見 [INPUT_CHECKSUMS.json](INPUT_CHECKSUMS.json)。

原始來源封存包可解壓到專案根目錄，內含 `inputs/`、`data/raw/twse_<year>/` 及 `twse_history/raw/` 的必要來源；重新執行 `python -m twse_history.build_history --year 2018 --quotes inputs/quotes_twse_2018.csv.gz`，或替換為 2015、2016、2017、2019、2020、2021、2022。`package_year_archive.py --year 2018 --output ...` 可在完整快取上重新產生帶逐檔 SHA-256 的 ZIP。已有 2015–2026 的年度行情與部分原始封存，仍須全段共同建置與核對；不能把各年度已還原價直接拼接。

## 月營收的公告時點

免費入口有證交所 [OpenAPI 的上市公司月營收資料](https://openapi.twse.com.tw/)和[公開資訊觀測站的公司公告查詢](https://mops.twse.com.tw/mops/web/index)。彙總表中的「營收所屬月份」或後來下載的最新快照，**都不能代替該家公司當時的實際公告時間**。資料準備者必須從可稽核的歷史公告與原始快照產生 `reports.csv`，每筆含：

| 欄位 | 內容 |
|---|---|
| `symbol` | 保留前導零的代號 |
| `revenue_month` | `YYYY-MM`，營收所屬月份 |
| `revenue_twd_thousands` | 當月營收，千元；需確認來源單位 |
| `reported_yoy_pct` | 該次公告版本的同比增減百分比，例如 `12.5` 表示 +12.5% |
| `published_at` | 真正公開時刻，含時區，例如 `2024-03-11T17:30:00+08:00` |
| `source_url`、`snapshot_sha256` | 公告來源與所存原始證據 SHA-256 |

`twse_history/asof_revenue.py` 只處理**已核實公告時間的標準化資料**，並保守地從公告日期的下一個市場日才提供訊號特徵。同月份修正會在公開後更新；較舊月份的晚到修正不會把最新月份倒退。用法如下，`signals.csv` 需有 `date,symbol`，`calendar.csv` 需有 `date`：

```bash
python -m twse_history.asof_revenue --signals signals.csv --reports reports.csv \
  --market-calendar calendar.csv --output outputs/signals_with_revenue.csv
```

目前沒有經核實的歷史逐公司公告時間表，因此**尚未訓練含月營收的新模型，也未宣稱增加績效**。切勿把「次月 10 日截止申報」直接填入 `published_at`。
