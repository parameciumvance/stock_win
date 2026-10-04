# 2025 持股現金條件高優先級核對 v8

更新：2026-09-29。本版接續 v7，按已保存的事件清單優先度核對排序前 20 個純除息事件的每股現金與支付日。資料來源仍以免費可查公告、發行人頁面及重大訊息轉載為主，沒有改動 v5 四個選股組合的代理淨值或 v6 0050 實股帳。

## Tasks

- [x] 核對 v7 清單中排序前 20 個持股純除息事件，新增 11 筆有來源的條件。
- [x] 追蹤 3002、4569、8021、8045 的每股配息率修正，採除息前已發布的修正值。
- [x] 檢查官方事件鍵、公告日、除息日、支付日及來源連結；保留還原價參考缺口為獨立欄位。
- [x] 離線重算來源覆蓋率及待核對優先順序。
- [ ] 補齊其餘 501 個純除息事件的條件，查詢後續補充／更正公告。
- [ ] 查核 125 筆配股或權息持股交集，以及減資、面額變更、分割與下市相關權益。
- [ ] 從原始成交重建四個選股組合的實際股數、應收現金、付款和期末權益；進行同口徑回測。
- [ ] 加入較早年度、逐折訓練、公告時間與可成交性驗證。

## 新增條件

表內金額為每股新臺幣現金。`amount_source_url` 和 `payment_source_url` 分別保留在 `dividend_evidence_v8.csv`；下方「重大訊息轉載」是新聞網站所刊的公告文字，尚非直接下載的 MOPS 原件。當期來源的公告日與修正紀錄另見 CSV。

| 代號 | 2025 除息日 | 修正後每股現金 | 支付日 | 核對來源 |
|---|---|---:|---|---|
| 6625 | 06-19 | 4 | 07-16 | [重大訊息轉載](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=7ca9b3c1-7ec6-466f-8865-32179b5aeffc) |
| 3002 | 09-17 | 0.69781688 | 10-17 | [金額修正](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=6272b79c-1e36-4a2f-87e8-cf7281782152)、[原支付日公告](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=f116fbc0-b529-4ba4-93b7-7a5651b64a28) |
| 4569 | 08-07 | 5.71127779 | 09-08 | [調整後條件](https://www.moneydj.com/KMDJ/News/NewsViewer.aspx?a=6c3a58c7-cacc-4acf-9eb0-df9f8a75a850) |
| 4770 | 03-27 | 12 | 04-30 | [發行人股利頁](https://www.alliedsupreme.com/tw/investor/investor-2/investor-10)、[3/11 公告轉載](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=cc20f948-b5df-4eb0-9fcc-02e3b5bf96fc) |
| 4949 | 03-27 | 1.1 | 04-25 | [重大訊息轉載](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=366d9231-e879-44ff-92a4-8c3d772234f1) |
| 8021 | 07-03 | 1.20685848 | 07-29 | [金額修正](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=f222fb35-364f-4952-9dce-42995c9ca463)、[原支付日公告](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=695e0adf-5361-4556-8260-b96d196ff31b) |
| 1419 | 07-24 | 1.5 | 08-22 | [重大訊息轉載](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=770a3249-25e3-4731-ab7f-14465112b6ff) |
| 2615 | 06-24 | 3.5 | 07-23 | [重大訊息轉載](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=e00f951b-51e1-4806-9506-eb0073110f1c) |
| 3596 | 06-02 | 7.5 | 06-27 | [發行人每股金額](https://www.arcadyan.com/zh-hant/investor/dividend-history/)、[支付日公告轉載](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=0a9ee8cf-f1e8-4615-9dcb-9a9c844589e5) |
| 8045 | 07-03 | 1.96783050 | 07-25 | [調整後條件](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=77be9fd4-77c9-4b40-b41a-3dbb49ec4ea5) |
| 8072 | 07-04 | 1 | 08-01 | [重大訊息轉載](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=cb0da927-e323-4549-9c2a-6f9f75c81a96) |

`dividend_revisions_v8.csv` 保留四筆舊值、修正值、公告日期與兩個來源欄位：3002 **0.69876859 → 0.69781688**（09-02 庫藏股轉讓）；4569 **5.6 → 5.71127779**（07-10 買回庫藏股）；8021 **1.2 → 1.20685848**（06-10 執行庫藏股）；8045 **2 → 1.96783050**（04-28 員工認股權行使）。這四筆都是除息前的公開修正。3596 的 7.5 元現金分派包含盈餘及資本公積來源，未推定其稅務或交易成本處理。

## 覆蓋率及下一批

目前累積有 **20／521 個不同純除息事件**，跨五組合合計 **58／663 筆持股交集**；仍缺 **501 個事件、605 筆持股交集**。20 個已查事件剛好覆蓋 v7 排序表最前面的 20 個，其中兩筆為 0050，已在 v6 實股帳處理。下一批在 v8 `cash_event_research_queue.csv` 排序前列的是 2832、6768、6412、3036、3705、9902 等；其參考價差只能供選擇核查順序，不能當現金或新績效。尤其 6768 的參考缺口約 6.18 元，須取當期公告精確每股率。

程式 `dividend_priority_v8.py` 驗證官方事件對照及已記錄修正條件；輸出 `audited_dividend_revisions.csv`、`source_linked_dividend_terms.csv`、`held_cash_event_priority.csv`、`cash_event_research_queue.csv`、`summary.json`。每筆現金、付款日仍可能有後續公告，須人工再查，不能把網站的當前歷史頁當作當時可得的訓練特徵。這批證據只為股東現金帳做準備；還原價等效單位並非原始實股數，配股、減資、認股款與現金稅費亦未結清，因此不能宣稱四組合實際投資績效。

下一步規劃：研究可重複取得 **2025 全年公告修正史及付款日** 的免費批次方式；先處理剩餘高優先事件及 6768 的精確配息率。同步把 v5 成交單位和 v6 持股事件整理為原始股數帳的可測資料結構，等足夠現金及權益條件核實後才重算四組合淨值。
