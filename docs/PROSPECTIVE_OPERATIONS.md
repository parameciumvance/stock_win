# 執行狀態：停止

2026-10-16使用者已決定停止七規則每日前瞻計畫。以下命令僅作歷史操作參考，不再執行10/16或後續日計畫；原始協定及封存保持不變。詳見[研究方向決定](RESEARCH_DIRECTION_20261016.md)。

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

跨年暖機會取得窗口所跨每一年度的TPEx三類及TWSE四類事件，前一年查詢至12/31、訊號年查詢至當日，任何年度缺檔、錯年、範圍或格式不符均拒絕。0050公司行動在同一序列跨年累積；全年確定無事件須有成功且格式完整的空來源，不能以錯誤回應代替。12月版本另取得翌年開休市表，跨年進場若缺翌年日曆即拒絕。2026-10-16新增跨年fixture與10/15封存來源回歸核對；尚未取得未來2027年真實每日來源，fixture不算新前瞻訊號。未啟動定時服務，沒有實際訂單。若錯過當日封存，另記缺口，不能把事後診斷當作前瞻觀測。

## 每日設定與封存來源稽核

建立新日期設定（只寫plan，不下載、不排程、不產生訊號）：

```bash
.venv/bin/python prepare_prospective_run.py --date 2026-10-16
```

10/16設定已建立，不要重複建立。當日15:00臺北時間後，依序執行：

```bash
.venv/bin/python research_pipeline.py --plan configs/prospective/20261016/source.json --state-dir inputs/prospective/20261016/pipeline
.venv/bin/python research_pipeline.py --plan configs/prospective/20261016/replay.json --state-dir inputs/prospective/20261016/replay_pipeline
.venv/bin/python research_pipeline.py --plan configs/prospective/20261016/seal.json --state-dir inputs/prospective/20261016/seal_pipeline
```

來源入口現已拒絕非當日或15:00以前的取得要求。15:00仍只是最低門檻，實際來源、日期、暖機、重播與封存必須全部通過。週末或休市日會在官方市場日曆關卡被拒絕。

更新程式後，使用`verify_prospective_archive.py`稽核舊訊號：從Git還原其manifest記錄的舊程式SHA，核對來源包及備份，再以目前程式重播比較矩陣、名單與0050。稽核報告另存，舊manifest／訊號及其程式版本記錄不修改。封存目錄的features與replay寫入入口均拒絕覆寫；不要直接對舊訊號目錄重跑產生器。
