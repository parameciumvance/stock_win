# 台股歷史普通股股票池與價格還原 v2

已實跑期間：2025-01-02～2025-12-31。資料來源全部為免費官方資料，不需要 API key。這是研究資料層；尚未訓練預測模型或計算可成交策略績效。

## 直接重現

解壓縮後，在包含 `twse_history/` 與 `inputs/` 的目錄執行。適用 Python 3.10 以上；本次以 Python 3.12.14、pandas 2.2.3、numpy 2.3.5 驗證。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r twse_history/requirements.txt
python -m unittest twse_history.test_history -v
python -m twse_history.build_history --year 2025 --quotes inputs/quotes_twse_2025.csv.gz
```

資料包內含輸入行情、官方來源快照與全部輸出。已有依賴套件時，重建過程不需要連網。WSL Ubuntu 可以直接使用上述指令；Windows PowerShell 啟用環境改用 `.venv\Scripts\Activate.ps1`。

重新取得來源時使用另一個快取目錄，避免混淆不同取得時間的版本：

```bash
python -m twse_history.fetch_history --year 2025 --quotes inputs/quotes_twse_2025.csv.gz --raw refreshed_raw --delay 3
```

下載器保留原始回應、來源網址、取得時間與 SHA-256，採逐筆請求、限速與重試。2025 年 0050 精確分割比例另外由官方公告人工核對，記在 `raw/verified_share_ratios.json`；要完整重現本版結果，使用隨附的原始 `raw/`。新抓取的來源未帶此核對檔時，會採官方顯示參考價比值，不能宣稱已使用精確分割比例。

## 股票池定義

1. 從 2025 年每日歷史行情出現的證券建立候選集合，不以今日仍上市的公司名單作內連接。
2. 使用官方 ISIN 的 CFI 分類；`ES` 類列為普通股，包括上市創新板與第一上市 KY 普通股。ETF、特別股、TDR、ETN 等排除，0050 只作 benchmark。
3. 今日名單消失的公司另做代號查詢。仍無 ISIN 的新光金、晶睿，以官方終止上市公司清單及四碼公司代號交叉確認；分類依據逐筆保留。
4. 納入日以「本資料期間第一次出現歷史行情」為界，下市日當天起停止納入。當中停牌或缺價的日期仍保留成員列，不以價格前填假造成交。
5. 今日 ISIN 的上市日只供核對，不能拿來往前補股票池。例如 3717 的目前基本資料可能沿用前身日期，本版從實際首筆行情 2025-08-15 才納入。

這是**依歷史行情重建的股票池**，不是已取得每一天的原始證券主檔。尚未證明包含期間內完全沒有行情、且其他來源也查不到的公司，也不把第一筆觀測日冒充正式初次上市日。歷史 API 回傳的公司名稱可能已更新，只供顯示；`observed_name_history` 不是正式更名公告史。下市日、最後觀測日與今日 CFI 等稽核欄位不得直接放進模型特徵。

## 價格還原定義

一般公司行動的調整因子為：

\[
f_e = \frac{\text{官方事件後參考價}}{\text{官方事件前收盤價}}
\]

減資同時增資時，優先使用結果表的增資後除權參考價。已核實的純分割，使用 `1 / 每一舊股換得新股數`；0050 一拆四用 0.25，避免 47.16 元顯示值的四捨五入誤差。同股票同日多筆事件會停止，待確認是否為複合事件，不能盲目連乘。

輸出兩種比例，原始價量始終保留：

\[
P^{causal}_t = P^{raw}_t\Big/\prod_{e\le t} f_e
\]

\[
P^{back}_t = P^{raw}_t\prod_{t<e\le T} f_e
\]

`adj_open/high/low/close` 只使用截至該列日期已生效的事件。`back_adj_close` 錨定資料結尾 T，使用後續事件，適合圖表；其絕對水準不可直接當歷史時點已知特徵。`--as-of YYYY-MM-DD` 可限制同一年內的行情與生效事件，但不會把今日取得的證券主檔變成當時公布版本。

本版是**官方參考價連續還原**。現金股利、減資退還股款、認股款支出與持股數變化尚未建立逐筆股東現金流帳，因此不能當作精確總報酬、資產淨值或回測損益。成交量與成交金額保留原值，不用除息因子調整股數。在補齊股數事件前，量能特徵優先使用成交金額；跨分割前後的原始成交股數不可直接比較。

每次建置僅處理一個年度。跨年度訓練前，須合併各年原始行情及公司行動、使用共同起點重新累積因子；**不能直接串接每年各自錨定的還原價格水準**。

## 飆股標籤 v2

使用還原後的未來 20 個市場交易日最高價，相對訊號日還原收盤價上漲至少 30%。當日最高價不在窗口內。20 日必須全部有有效最高價，訊號日也須有有效收盤價；不足時 label 留空，並寫入 `censor_reason`。

`surge_next_open` 改用下一個市場交易日開盤價作分母，只是觀測口徑；沒有假設漲停或低量時一定能買到，也沒有假設能賣在未來最高價。缺價與下市可能非隨機發生，不能把留空列直接當負例，也不能忽略其對回測樣本的影響。

舊版 `build_surging_labels.py` 與舊 Excel 報表保留作歷史原型。新研究改用本目錄的 `build_history.py` 與 `surge_labels_adjusted_2025.csv.gz`。舊版忽略部分窗口內缺價的問題已在本版修正。

## 輸出檔案

| 檔案（位於 output/） | 用途 |
|---|---|
| security_master_2025.csv | 全部 1,344 個歷史證券代號的分類、證據與觀測界線 |
| universe_daily_2025.csv.gz | 逐日普通股成員、行情存在狀態與價格可用性 |
| universe_daily_counts_2025.csv | 每日成員與有效價格筆數 |
| corporate_actions_2025.csv | 所有來源事件、因子、日期、來源列號與雜湊 |
| corporate_action_audit_2025.csv | 普通股及 0050 事件前收核對與價差比較 |
| prices_adjusted_2025.csv.gz | 普通股及 0050 原始 OHLC、因子、還原 OHLC |
| surge_labels_adjusted_2025.csv.gz | 嚴格窗口標籤、缺價原因、隔日開盤口徑 |
| label_changes_2025.csv | 相同有效窗口下，還原前後標籤差異 |
| new_listings_audit_2025.csv | 官方最近上市表與首筆行情的日期核對 |
| universe_coverage_gaps_2025.csv | 目前普通股主檔應涵蓋但本年沒有行情的候選缺口 |
| delistings_observed_2025.csv | 重建時查得的 2025～2026 下市事件，供稽核 |
| observed_name_history_2025.csv | 行情快照所見名稱，不等於正式更名生效日 |
| large_price_moves_2025.csv | 還原後前後兩次有收盤行情仍相差超過 30% 的紀錄 |
| summary_2025.json、source_manifest.json | 統計、限制與來源紀錄 |

讀取資料時保留代號字串，例如 `pd.read_csv(path, dtype={"symbol": str}, parse_dates=["date"])`，避免 0050 變成 50。

官方來源及本次結果詳見 `history_adjustment_report_2025.md`。
