# 6674官方文件取得與來源重播（2026-10-22）

已自動取得固定6674／115年文件目錄，並循實際回傳指標取得11月9日臨時會的兩份PDF；不需要使用者逐份下載。目錄宣告Big5，已嚴格解碼，保留15列×11欄，包括兩列資料年度114的年報。未執行頁面JavaScript，也未猜檔名或排除不合查詢年度的回傳列。

本段四請求依原上限完成：查詢1、目錄1、兩個下載POST2，連先前發現8次累計12。兩POST雖HTTP200／curl0，實際都是503-byte Big5 HTML，保留原回應而不當PDF。其精確href的兩次GET另凍結為實體傳輸階段，累計14；沒有改動舊八次／四次上限。實體PDF驗收見[報告](../cash_merger_pdf_transfer_20261022/report.md)。

三包原件均先Windows備份、取回、驗SHA／CRC／manifest，合計23項manifest。26項測試通過；11階段重跑全部hash驗證跳過。373項舊checkpoint成員未改；原始資料在持久化inputs與Windows同機備份，不提交Git。

目錄上傳標示115/10/20只是目前回傳值，不是已證實的首次可得時間；實際取得在10月22日清晨，不能當作前一日或當晚已知狀態。沒有行情／收益計算、訂單或有效前瞻訊號。初次UTF8解碼失敗、缺pytest與權限工具觀察均見execution_observations.json；測試採專案既有unittest。

- 查詢包：`c104cebaf53c1629f7e257aee08decb05b93a112d16172158d44bf6e64866012`
- Big5目錄包：`2dc775a28540045d30bcf244209c0d07bb2ea8b8aac06bd2e7372f468816f406`
- HTML下載入口包：`a21b4ec1547bb4cae44f69ef7d99b714d42240df655e38617c87698f7ae34f2e`
