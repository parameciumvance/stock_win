# 中斷恢復與防護

適用 Linux／WSL（使用 POSIX 檔案鎖與程序群組）；原生 Windows 請先進 WSL。

```sh
make test-research-runtime
make research-status
make research-run
```

預設計畫是 `configs/tpex_source_pipeline_2026.json`，重新使用凍結日曆；不補截止日之後資料，不改模型。先還原日曆與年度行情，否則 exit 78 `needs_restore`。改計畫可設定 `RESEARCH_PLAN` 和獨立 `RESEARCH_STATE_DIR`。本次只驗證 runner 與 fixture，沒有重抓整年來源。

`state.json` 每 15 秒原子更新，記錄目前階段、PID 身分、日誌位置、耗時、觀察到的主程序 RSS、退出碼／訊號與 cgroup 計數。日誌持續寫入。預設單階段限時一小時，RSS 上限 4096 MiB；RSS 取樣不是整棵程序樹的硬性記憶體限制。平台完全消失時不會再有心跳。

重跑同一指令會核對輸入、設定與輸出 SHA，只跳過完整吻合的階段。gzip 必須讀到結尾，ZIP 必須通過 CRC。失敗不標完成。只重試計畫中明列的退出碼（最多三次）；下載僅對連線／逾時重試一次，解析或會計一致性錯誤直接失敗。既有 raw/meta 雜湊不符會停下查核，缺 meta 則重新取得並驗證。

來源下載加鎖；完成 raw 原子寫入後才原子寫 meta。每批兩日寫下載進度。runner 使用獨立鎖，若發現上次子程序仍活著，回傳 75，避免重複啟動；請確認日誌與程序，不要直接刪狀態。

封存 gate：exit 78 `awaiting_checkpoint` 表示需保存並取回 ZIP。執行方完成保存與 SHA／CRC／manifest 核對後建立 `pipeline_checkpoint_receipt.json`：

```json
{"library_file_id":"實際保存ID","sha256":"ZIP的SHA-256","roundtrip_verified":true}
```

再執行相同指令即可接續。這是可稽核的保存紀錄，不是 runner 自動上傳；禁止未驗證就填 true。報告與 receipt 需推 Git，不能只留暫存。來源包與後續研究包分開保存，縮小重做範圍。

退出碼：0 完成；1 階段失敗；75 既有子程序仍活著；78 缺輸入／待保存；130 收到中斷。`--status` 僅顯示最後狀態，不能證明程序仍在執行。工具通道超時也不能假定子程序已停止。

平台錯誤為 transport disconnected 或 environment_offline 時，保存原訊息、時間、最後階段與可得日誌。底層原因需平台診斷，不能把執行環境斷線當成證交所封鎖。新環境的 OOM 計數不能代表舊環境。若工作區遺失，從 Git 還原程式、從已核對的封存還原資料，再執行同一計畫。

更長的下載可在自己的 WSL 或持續運作的主機使用同一 runner，減少對聊天暫存環境的依賴；仍需資料備份與程序監控，不能保證永不中斷。

本環境觀察到沙箱 PID 與主機 `/proc` PID 不同；工具以 PID namespace 與 `NSpid` 對應程序，避免誤判孤兒或讀取別的程序 RSS。這是工具相容性修正，不是先前平台中斷的根因證據。


## 長歷史舊格式試點

先將已保存的 `tpex_long_history_availability_checkpoint.zip`（SHA `daf1f8cfba8832d9519ff735265ea5c907be1d2a90091163674125a7c9f2f36e`）還原到 `deliverables/tpex_long_history_probe/`，逐檔SHA與CRC核對後解出原路徑。保存ID及已核對紀錄在同目錄 `pipeline_checkpoint_receipt.json`。然後執行：

```sh
make research-run RESEARCH_PLAN=configs/tpex_long_history_schema_pipeline.json RESEARCH_STATE_DIR=deliverables/tpex_long_history_schema_run
```

第一次執行包含57項TPEx及10項runtime測試、四日舊／新版法人逐筆重播和全證券行情交集檢查；後續依完整SHA跳過已驗收階段。Git中的fixture是來源回應的壓縮副本，可獨立執行 `python -m unittest test_tpex_flow_legacy -q`。四日結果不代表全年或歷史普通股分類已完成。


## 2022全年來源試點

使用者已採用先做2022，再考慮擴八年。入口：

```sh
make research-run RESEARCH_PLAN=configs/tpex_2022_source_pipeline.json RESEARCH_STATE_DIR=deliverables/tpex_2022_source_run
```

需先還原凍結的 `deliverables/tpex_pilot/classification/isin.raw`、`isin_listed.raw`、`unknown_single_query.html`。其SHA由年度 `type_input_hashes.json` 固定，不能換成新抓版本。年度行情包包含相同三份分類副本，來源為回溯分類證據，並非當年公告快照。恢復時核對副本SHA再還原到上述位置。

行情先逐月下載；年末逐日重播及TPEx／TWSE日曆相互核對，保存行情ZIP並取回驗證後寫 `deliverables/tpex_2022/pipeline_checkpoint_receipt.json`。再執行同一入口，續抓法人並逐筆重播、保存第二包、取回核對及寫 `deliverables/tpex_flow_2022/pipeline_checkpoint_receipt.json`。最後執行事件前收盤對應與來源缺口報告。正常保存gate不需再次詢問使用者。

部分月份checkpoint只供恢復，不代表全年驗收完成。2022年初缺2021前收盤、完整停牌證券主檔、未解分類、還原價及股東現金帳仍分開列待辦；不因下載完成就開模型調參。
