# 聯電SEC索引HTML：標頭時鐘獲佐證，JSON差異保留

瀏覽器另存HTML已原樣保存：12,186 bytes，SHA `0fca0852e3d83b13e1131236bbc1fd9a6aa615c6ed12dd42db2382f41264a3ff`。Zone.Identifier HostUrl與頁內saved-from註解符合指定官方索引URL。這是瀏覽器保存的HTML表示，不宣稱原始HTTP回應bytes；沒有HTTP headers，未執行頁內script或讀取旁邊資源資料夾。

## 時鐘結論

Accepted明示 **2025-01-21 06:03:58**，與完整SGML原值20250121060358一致。CIK、accession、6-K、事件日、三個文件的序號／名稱／類型／URL及完整申報55,016 bytes均對上。

按既有America/New_York解讀，UTC為 **2025-01-21 11:03:58**，台北為 **2025-01-21 19:03:58**。頁內Last-Modified metadata也寫Tue, 21 Jan 2025 11:03:58 GMT，僅記為輔助一致性，不把HTML metadata冒充HTTP header或接受／公告時間。

本輪明示來源優先序：完整申報SGML與另存申報索引兩種表示相符，採其換算作SEC接受時間錨點，不依數值較早／較晚選時間。新ledger填入該錨點，舊衝突快照原樣保留。submissions JSON仍原樣為2025-01-21T16:03:58.000Z，差18000秒；`json_conflict_retained=True`，未改寫JSON或宣稱查明SEC根因。這是接受時間獲佐證，並非三來源完全一致。

SEC接受時間仍不等於公開傳播時間或台灣首次公告。未以本次下載／檔案修改時間回填歷史公開時點；全部24列ready_for_model=False，沒有重啟每日前瞻或建模／績效。

## 封存與重播

先封存HTML、取得紀錄、凍結協定、上一輪完整來源包及證據，再經Windows備份取回；整包SHA／manifest／CRC通過。checkpoint SHA `8ca0ddcddce81b7ca8e749399aa0feac3854f0457c6ee37d0ef3483463f897da`。備份在Windows使用者研究目錄，取回在WSL，屬同電腦跨檔案系統，不宣稱離機備份。下游僅從取回包解析，重新解析SGML與JSON候選，核對巢狀來源包SHA／CRC／manifest；未修改凍結參數或舊來源。

## 進度與外部依賴

台積電與聯電2024Q4各有官方PDF及完整SEC版本，數值一致，兩組接受時鐘均有索引佐證；聯電JSON的五小時差異仍標記。其餘22季缺原文。既定關卡所需的歷史公開／首次公告時點與版本涵蓋證據尚缺，不能只憑一份快照宣稱完整。先完成這兩組來源可行性，再擴充22季；不需使用者重傳既有檔案。

[下一步清單](next_tasks.json)明列外部證據缺口及擴充條件。七規則252日計畫保持停止；新方向尚無訓練資料集或預測誤差結果。

重播：`.venv/bin/python research_pipeline.py --plan configs/operating_sec_index_import_pipeline.json --state-dir inputs/operating_pilot_20261016/umc_index_html_pipeline`。測試與實際執行時間見[tests.json](tests.json)，階段輸出hash見[pipeline_state.json](pipeline_state.json)。
