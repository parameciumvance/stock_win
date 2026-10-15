# 前瞻來源與重播操作

使用持久化工作區 `.venv/bin/python`，不得改動七法凍結配置。2026-10-15 的實際入口：

```bash
.venv/bin/python research_pipeline.py --plan configs/tpex_prospective_source_pipeline.json --state-dir inputs/prospective/20261015/pipeline
.venv/bin/python research_pipeline.py --plan configs/tpex_prospective_replay_pipeline.json --state-dir inputs/prospective/20261015/replay_pipeline
.venv/bin/python research_pipeline.py --plan configs/tpex_prospective_seal_pipeline.json --state-dir inputs/prospective/20261015/seal_pipeline
```

三個 plan 是該日的固定執行設定；下一訊號日需另建 plan 與版本目錄、更新日期，不能重用已封存目錄。未封存的同版本失敗可續跑，快取須先核對 URL／SHA。來源階段兩個 worker 並持有專屬鎖；下游階段循序執行。不要啟動第二個相同來源程序。所有日期判斷使用 Asia/Taipei。

來源階段保存四個完整月加當月的官方 TPEx 月指數日期、逐日行情、前五日法人、四個月國內／國外營收、三類 TPEx 事件、ISIN、0050 月行情及四類 TWSE 公司行動，另保存年度開休市表。不得用下載失敗推定休市，也不得把本次取得時間寫成原始公告時間。當日資料需完成後才可封存；15:00只是最低時刻。

`prospective_sources.py archive` 先打包、複製到 `inputs/prospective/backups/<run>/`，再取回另檔，驗證整包 SHA、所有 manifest 成員及 ZIP CRC，才產生 checkpoint。這是使用者指定本地持久化資料模式，同檔案系統備份不等於異機備援；大型原始檔不提交 Git。receipt 使用 `storage_kind=local_persistent_copy`，不偽造 Library ID。此模式以 pipeline 的 command stage 驗證，不使用既有只接受 Library receipt 的 checkpoint stage。

`prospective_replay.py features` 只能讀取經核驗的來源包，重建分類、事件遮罩及七個價量特徵；法人排除訊號日，營收同時受實際觀測及固定45／60日門檻限制。0050使用既有 forward-reference 邏輯，缺價保持未知，不更改市場時計。`replay` 再由原始包重建、比較特徵矩陣及0050，並以獨立逐筆選股程式比較兩種營收延遲的七法全名單。

`prospective_finalize.py` 將來源包及 selection manifest 放入 journal 的內容雜湊路徑。journal 封存完整訊號時會重新重播、核對全部名單、程式版本、來源觀測／驗證時間、訊號日期及下一市場日09:00截止，並在重播結束後再讀時鐘。單獨提供 `raw_replay_verified` 字串或64字元摘要不能通過。已封存訊號不可覆寫，來源取得及來源包覆寫亦被拒絕。

最後另封存包含原始包、兩份矩陣、0050、manifest及journal的訊號重跑包，備份取回後再驗 SHA／CRC／全部成員。小型 receipt、manifest及訊號記錄可提交 Git；本地路徑是稽核定位，不是可跨機自動恢復的承諾。移機須先恢復原檔與 hash，再記錄明確的路徑重定位；不能修改原封存紀錄。

目前已驗證的是2026年同年度暖機；跨年暖機尚需同時取得前一年事件，本版遇到跨年要求會明確拒絕，不能忽略前一年事件繼續產生訊號。未啟動定時服務，沒有實際訂單。若錯過當日封存，另記缺口，不能把事後診斷當作前瞻觀測。
