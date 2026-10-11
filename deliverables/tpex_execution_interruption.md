# 執行環境中斷檢核（2026-10-11）

2023、2024、2025 TPEx 全年原始行情與分類已完成，三包保存後取回 SHA、逐檔 manifest 與 ZIP CRC 均通過；詳細報告各年度 acquisition_report.md。

2026 最後觀測：1–4 月下載完成，5–6 月正在抓取。write_stdin 回報 `exec-server transport disconnected; failed to resume exec-server session: recovery timed out after 25s`。新 `pwd` 也未返回結果，已中止等待。無法確認背景下載程序是否仍在執行，不能當作櫃買來源拒絕、假日或全年完成。

恢復順序：先檢查是否已有正在執行的 acquire_tpex_year 程序，避免重複寫入；核對 raw／meta SHA 與月 CSV／摘要 SHA，再以既有快取續抓；完成獨立 TPEx 日曆與部分年度驗收、保存後取回核對，才勾選完成。接著建立保守還原價代理與事件規則，暫不調參。

19 項解析／截點測試在中斷前通過。跨年事件檢查已執行成功；最後補入的 current-year hash／partial-year event guards 尚未在中斷環境重新執行，不宣稱額外測試完成。
