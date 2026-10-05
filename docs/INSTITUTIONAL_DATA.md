# 免費法人買賣超資料與特徵

## 已核對

官方免費日報：`https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date=YYYYMMDD&selectType=ALL`。2015-01-05、2020-01-06、2024-01-05 樣本共 31,394 筆、無重複代碼、買賣與加總恒等式均一致。見 `deliverables/institutional_source_pilot.json`。

2024-01-05 的既有歷史普通股池有 997 檔，960 檔在 T86 出現，37 檔無列；缺列不作零值。ALL 回應含 ETF、權證等，不能把所有 14,141 列当普通股。

2015 樣本为旧「外資」欄位；2020 和 2024 为「外陸資（不含外資自營商）」並另列外資自營商。保留 `foreign_schema`，不宣稱舊新外資口徑已等同。外資自營商數據不再加到三大法人合計，避免重複計數。來源說明：[TWSE 日報](https://wwwc.twse.com.tw/zh/trading/foreign/t86.html)、[TWSE 欄位與計數說明](https://eshop.twse.com.tw/zh/product/detail/010ebd2cdb854169bb8707378f75b12a)。

來源 notes 明載：含一般、零股、盤後定價、鉅額，且以當日原始成交情形統計，不以申報錯帳／更正帳號調整後資料統計。保存原文與 hash，不把這個說明當逐筆下載時刻或完整版本歷史。

## Tasks

- [x] 三個年度樣本可取得，欄位與加總驗證通過。
- [x] 擷取工具逐日保存原始 JSON 與 SHA-256 metadata，缺檔可續抓，最多 2 workers。
- [x] 當時普通股池篩選介面；先驗證所有原始列，再依 date/symbol 篩選，缺列保留。
- [x] 1／5／20 日因果特徵工具與邊界測試；共 16 項營收、法人解析與特徵測試通過。
- [x] 2023 全年 239 日下載與覆蓋檢查完成，完整重跑包已封存。
- [x] 2023 年內固定成本與共同池的 Ridge 增量完成；見 `deliverables/institutional_increment_report_2023.md`。
- [x] 2024 全年 242 日、241,431 筆普通股流量與 2023–2024 連續特徵生成成功。
- [ ] 2024 跨年比較與補充包封存被 environment_offline 阻塞，詳見 `docs/SESSION_RECOVERY.md`。
- [ ] 新期間資料與預先固定驗證方案；目前研究年份不可改稱独立留出。

## 重跑

```bash
python -m twse_history.institutional --dates 20150105 20200106 20240105
python -m unittest twse_history.test_institutional twse_history.test_institutional_features -v

python -m twse_history.institutional --year 2023 \
  --cache inputs/institutional_2023 \
  --universe twse_history/output_multiyear_2023_2026_asof_20261002/universe_daily_2023_2026.csv.gz \
  --output inputs/institutional_twse_2023.csv.gz --fetch

python -m twse_history.institutional_features --year 2023 \
  --prices twse_history/output_multiyear_2023_2026_asof_20261002/prices_adjusted_2023_2026.csv.gz \
  --flows inputs/institutional_twse_2023.csv.gz \
  --output inputs/institutional_features_2023.csv.gz
```

需要官方年度交易日曆及完整的歷史普通股池；缺檔、壓縮檔不完整、日期或加總不一致會停止。所有原始日期確認後才寫年度 CSV；錯誤時取消未執行下載，最多等待兩個已啟動請求各自的 timeout。原始 JSON 每日已保存，可以原命令續抓。

## 特徵規格

每一來源日用 raw shares / raw quote volume 得到日比率，訊號只使用上一市場日及更早資料：

- `foreign_net_volume_ratio_1d/5d/20d`
- `trust_net_volume_ratio_1d/5d/20d`
- `total_net_volume_ratio_1d/5d/20d`

5／20 日为日比率的平均，每個窗口須有完整觀測；不 forward fill，不補零。這不是持股比例，兩種來源的成交範圍可能不同，比率超过 1 不直接截斷；後續研究须做覆蓋與異常值檢查。暫只接受新版外資口徑。未知精確公告時間採次市場日的研究使用規則，明示回溯來源和修正歷史限制。這批來源工程尚未產生新模型成效。

## 降低後續下載量與復原

官方頁面明确列出 `ALLBUT0999`：不含權證、牛熊證、可展延牛熊證。三個年度樣本的保留列與完整 ALL 完全一致，原始样本已記錄；2024 採這個範圍。不同範圍須使用各自快取目录，不讓原始來源 URL 悄悄改寫。

2024 下載命令在原年度命令改為 `--year 2024 --cache inputs/institutional_2024 --output inputs/institutional_twse_2024.csv.gz --select-type ALLBUT0999`，沿用完整普通股池和 calendar。網路 timeout／500/502/503/504 最多三次請求，5／10 秒退避；4xx 不自動反覆重試。

還原資料後可執行 `make test-institutional`、`make institutional-diagnostics`，重建特徵和兩份研究比較。2023 包已確認保存；2024 備份狀態未確認，先核對而非盲目重新寫入。模型 coefficients JSON 的輸出介面已加入，待恢復執行後生成；目前只有 2023 結果已確認。
