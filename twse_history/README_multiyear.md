# 台股歷史資料 v3：2024–2025 跨年流程

本版接續 2025 原型，加入 2024 年官方全市場行情與公司行動，並在共同交易日曆上重算股票池、還原價格和飆股標籤。確切筆數及品質檢查見隨附 `history_extension_report_2024_2025.md`。

## 重現結果

在解壓縮後的根目錄執行（Python 3.10 以上；本次環境為 Python 3.12、pandas 2.2.3、numpy 2.3.5）：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r twse_history/requirements.txt
python -m unittest twse_history.test_history twse_history.test_multiyear -v
python -m twse_history.build_multiyear \
  --start-year 2024 --end-year 2025 \
  --quotes inputs/quotes_twse_2024.csv.gz inputs/quotes_twse_2025.csv.gz
```

WSL Ubuntu 可直接使用上述指令。Windows PowerShell 啟用環境改為 `.venv\Scripts\Activate.ps1`，並把多行命令寫在同一行。套件已安裝後，重算步驟完全使用包內來源快照，不需連網。

## 新增能力

### 按官方交易日取得資料

`fetch_quotes.py` 先讀取 TWSE 每月 FMTQIK 市場成交紀錄，確認全年應有的市場交易日，再逐日下載 MI_INDEX。不把「伺服器沒回資料」視為休市。任一預期交易日失敗時，保留快取及錯誤紀錄，**不寫出宣稱完整的年度行情檔**。

```bash
python -m twse_history.fetch_quotes --year 2024 --workers 2 --delay 3
python -m twse_history.fetch_history --year 2024 --quotes inputs/quotes_twse_2024.csv.gz
```

可用 1～4 個下載工作，預設 2 個；保留每次成功請求後的間隔。2024 原始每日回應在 `data/raw/twse_2024/`，網址、時間及 SHA-256 在相鄰 `.meta.json`。中斷後重跑會復用有效快取。官方欄位、日期或快取雜湊不符時停止並報錯。

2025 行情沿用上一版已取得的檔案，另以 12 份官方月資料核對完整交易日。套件含原始年度行情的雜湊；2025 的逐日原始 JSON 不在本版下載包內，沒有虛構其取得時間或來源快照。

### 跨年使用共同因子

先合併原始行情與全部期間的公司行動，再按日期累積一次因子。不能直接串接「2024 年自行還原」與「2025 年自行還原」的價格水準；兩者起點不同，會在跨年造成假報酬。

減資年度結果表遺漏了華冠 8101 停牌期間換股事件。`verified_supplemental_actions.json` 記錄證交所減資換發公告的每千股換發 200 股、11 月 19 日恢復買賣，以及官方行情最後收盤 1.90 元；程式驗證隨附兩份公告 PDF 的雜湊，再計算因子 5 與價格基準 9.50。若官方年度表日後補列同日事件，重複鍵會停止建置，要求人工比對。

`prices_adjusted_2024_2025.csv.gz` 中 `adj_*` 使用當日以前已生效的因子；`back_adj_close` 使用截至資料期末的事件，只供期末錨定圖表，不當成歷史時點已知的絕對價格特徵。原始 OHLC、成交股數和成交額保留。

### 年底標籤可以跨年，訓練切分須清除重疊

仍以未來 20 個市場交易日、還原最高價相對還原收盤價上漲至少 30% 定義研究事件。任何未來日缺最高價即留空，不前填、也不壓縮市場日曆。

新增 `label_window_end` 與 `entry_market_date` 作目標／交易時點中繼資料。2024 年底的 label 可以使用 2025 年行情，但若要把 2025 年當留出測試，這些跨界 label **不能出現在訓練集**。

`temporal_split_2024_2025.csv.gz` 預設以 2025-01-01 為切分邊界：

| role | 定義 |
|---|---|
| train_eligible | 訊號日在邊界前，標籤完整，且 `label_window_end` 嚴格早於邊界 |
| purged_overlap | 訊號日在邊界前，標籤完整，但未來窗口到達或跨過邊界 |
| test_eligible | 訊號日在邊界當天或之後，且標籤完整 |
| unlabeled | 訊號／未來缺價，或資料結尾不足完整窗口 |

此表只是候選切分，尚未產生模型特徵、訓練或績效。`label_window_end`、未來最高價、最後觀測日、下市日與切分 role 都不能作預測輸入；做 rolling walk-forward 時須逐折重新清除重疊，並按驗證設計考慮 embargo。

官方新上市表遇到公告日期是非市場日時，同時保留原始日期與「下一實際市場日」的首筆行情比對結果。例如 6919 官方表為 2024-10-02，當週下一市場日為 10 月 4 日。

## 主要輸出

全部位於 `twse_history/output_multiyear/`：

| 檔案前綴 | 用途 |
|---|---|
| security_master、universe_daily | 證券分類證據與逐日股票池 |
| prices_adjusted | 原始與共同起點還原價格 |
| corporate_actions、corporate_action_audit | 事件因子及官方前收價核對 |
| surge_labels_adjusted | 嚴格完整窗口的飆股標籤 |
| temporal_split | 訓練、重疊排除、留出測試與未標籤列 |
| year_boundary_audit | 年末／隔年首個市場交易日價格銜接 |
| new_listings_audit、delistings | 上市日期核對及查得的下市事件 |
| large_price_moves | 還原後仍超過 30% 的前後收盤變動 |
| year_summary、summary | 分年統計與整體健康結果 |

檔名均帶 `_2024_2025`。讀檔時 `symbol` 要指定字串，避免 0050 變成 50。

## 延伸下一年度

先用 `fetch_quotes.py` 取得行情與 12 份月交易日曆，再用 `fetch_history.py` 取得該年事件和下市資訊；最後把全部原始年度行情傳給 `build_multiyear.py`。不要合併之前已各自還原的輸出。

本版已實際驗證的範圍是 2024–2025。更早年度可能有 API 覆蓋期間、空表回應及欄位差異，需檢查後才能擴充；尚未宣稱完成 2016 年至今。

## 保留限制

股票池依歷史行情及官方 CFI／下市清單回溯重建，並非保存了每一天原始證券主檔；完全沒有行情的公司仍須查漏。公司名稱及當前分類只作顯示／分類證據，不作歷史可得的財報或產業特徵。

價格採官方參考價連續還原。股利、減資退還、認股款、股數、合併和下市對價尚未建立完整投資人現金流帳，故不能用來宣稱精確總報酬或可成交策略績效。隔日開盤與未來最高價均未假設保證成交。
