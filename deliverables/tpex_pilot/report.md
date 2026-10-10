# TPEx 免費來源試點（2026-10-11）

使用者採用：繼續免費上櫃資料可用性檢查、事件規則列入 Tasks，暫不擴大模型調參。未訓練新模型。

## 已實際取得

| 資料 | 請求日期／期間 | 紀錄數 | 檢查 |
|---|---|---:|---|
| 全市場收盤行情 | 2023-01-03 | 907 | 872 列完整價格；日期／鍵／OHLC 通過 |
| 全市場收盤行情 | 2024-01-02 | 911 | 895 列完整價格；日期／鍵／OHLC 通過 |
| 全市場收盤行情 | 2025-01-02 | 943 | 929 列完整價格；日期／鍵／OHLC 通過 |
| 除權息計算結果 | 2023 全年 | 1014 | 回傳期間一致，含現金股利與每仟股配股欄 |
| 減資恢復交易參考價 | 2023 全年 | 15 | 含詳細停牌日、每仟股換股數、每股退還款 |
| 終止上櫃 | 2023 | 9 | 回傳年度一致；須區分轉上市與其他下櫃 |
| 面額變更 | 2023 全年 | 0 | stat=ok 與查詢期間正確；不推論其他年無事件 |
| 面額變更 | 2024 全年 | 3 | 綠界科技、智通、尚凡；含換股率和停牌日期 |

行情成交量欄為「成交股數」，成交額為元；最後買／賣量另為千股，不能套同一倍率。行情包含 ETF／ETN，以上不是普通股數量。頁面標示主行情自 2007-07-01 開始，另有 2007 上半年 historical 頁；更早範圍尚未實測。

官方 OpenAPI swagger 的收盤與除權息介面沒有歷史日期參數。本次 latest 回傳 2026-10-08，除權息樣本回傳 2026-10-12 預定事件；皆不得加入截止 2026-10-02 的研究。歷史改用官方頁面所宣告的 www 查詢。

網頁查詢工具回傳 403，但 Python HTTPS 下載正常；不代表需要白名單或變更權限。每次下載有 20 秒 timeout，不無限重試，不把失敗當休市。

## 來源與工具

- 政府免費資料目錄：https://data.gov.tw/dataset/11371
- Swagger：https://www.tpex.org.tw/openapi/swagger.json
- 日行情頁：https://www.tpex.org.tw/zh-tw/mainboard/trading/info/mi-pricing.html
- 官方選單：https://www.tpex.org.tw/data/menu/zh-tw/menu.json
- 除權息：https://www.tpex.org.tw/zh-tw/announce/market/ex/cal.html
- 減資：https://www.tpex.org.tw/zh-tw/announce/market/reduction/reference.html
- 面額變更：https://www.tpex.org.tw/zh-tw/announce/market/change/reference.html
- 下櫃：https://www.tpex.org.tw/zh-tw/mainboard/listed/delisted.html

下載與行情檢核：`python3 tpex_source_pilot.py`；來源包解壓後可用 `python3 tpex_source_pilot.py --offline`。三個行情樣本重解析通過，另實測錯日期、重複代碼、錯欄寬、錯 OHLC 四種來源會拒絕。原始樣本包附 SHA256MANIFEST.json；probe.json、history_probe.json 保存實際網址、抓取時間與 hash。網頁與 JSON 原始樣本一起封存，來源範圍不等於完整年度資料集。

## 尚未通過的建模門檻

歷史普通股分類（含退出市場的股票）、完整交易日曆、公司行動與行情橋接、還原價、法人欄位與授權使用範圍仍待檢查。未建立年度資料或聲稱 PIT 股票池；下載現在的資料也不證明保留首次公告版本。

下一步先建立歷史分類與事件解析試點，核對換股前後報價；通過後才擴大年度下載。事件規則 Tasks 已加入营收加速、法人連續買超、價量突破及單規則／交集比較，正式執行前固定設定、不搜尋門檻。現有模型保持不變。
