# 2015上櫃來源驗收與2016跨年前收核對（2026-10-13）

2015全年行情244日、169,277筆；法人244日、101,687筆逐筆原始重播通過。行情575個、法人493個manifest成員保存取回SHA與CRC核對全部通過。來源續跑六階段完成，重跑全部SHA驗證跳過。

法人探索池平均每日覆蓋60.0598%，67,386筆缺列保留未知。股票分類保留153,033筆已核實普通股列、15,756筆候選列與244筆未解分類列，不使用今日名單刪除歷史證券。

2015公司行動529筆：524筆前收吻合、5筆非交易日事件。事件參考價公式、非交易日對應、完整停復牌主檔、還原價、現金帳及嚴格營收公告時點仍有待核對；來源驗收不是模型效果驗收，也不是新的独立留出。本輪沒有訓練模型或改規則、成本。

## Tasks

- [x] 2016驗收報告及封存收據九檔同步至main 3e28eece8fbea53aaf2c18f12cd6565be73d34da。
- [x] 2015行情月級與全年日曆、分類、原始重播及封存取回。
- [x] 2015法人來源、逐筆重播及封存取回。
- [x] 2015事件與年度缺口驗收；六階段重跑驗證全部跳過。
- [x] 已凍結2015行情補入2016年初前收核對，獨立輸出，不覆寫既有2016驗收報告。
- [x] 使用者於2026-10-13明確授權2015報告與封存收據同步GitHub；本提交納入已驗收的2015同步包。
- [ ] 總進度文件更新：整份研究歷史文件被自動核准審查拒絕，原文件未改寫。
- [ ] 下一研究階段：跨年未知事件遮罩與還原價格驗證，再沿用固定規則評估；嚴格PIT與精確現金帳維持pending，不擴調參。

## 2016跨年前收核對

{
  "year": 2016,
  "events": 537,
  "by_kind": {
    "ex_right_dividend": 510,
    "capital_reduction": 27
  },
  "by_status": {
    "last_close_matches": 525,
    "event_date_outside_market_calendar": 11,
    "last_close_mismatch": 1
  },
  "scope": "all source events including nonordinary securities; quote bridge only",
  "not_completed": [
    "reference formula and rounding verification",
    "cash ledger",
    "adjusted price construction"
  ],
  "prior_year_source_hashes": {
    "deliverables/tpex_2015/quotes_with_type_2015.csv.gz": "029e63d825bee84318315ce3d246c212ca02f78bb2fbd1605dde2417b4e67455"
  }
}

## GitHub同步範圍

本包為2015小型驗收報告、Tasks與來源封存收據，以及2016跨年事件核對摘要；收據含Library檔案識別碼。大型原始來源ZIP不提交Git。GitHub整份既有進度文件未放入本包，本包提供本輪增補進度供檢閱。
