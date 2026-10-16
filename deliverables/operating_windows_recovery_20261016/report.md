# Windows 本機來源恢復

使用者授權操作電腦後，從 WSL 呼叫 Windows 內建 curl 8.21.0，兩個下載 worker 共用 acquisition.lock。Desktop Commander 裝置 LAPTOP-HQTVA3O0 顯示離線；目前確認能執行 Windows 命令，尚未建立桌面 GUI 操作連線。

原先 Windows PowerShell `.ps1` 受到執行政策拒絕；保留實際錯誤，不變更執行政策。改用內建 curl 成功取得台積電2024Q4官方盈餘公告，HTTP200、178,679 bytes、SHA256 `3a2e2a2b10eaf67fb16f0f57edca44dc57ac472c2f24664abec5fe7c4d6ceb9a`。實際取得時間 `2026-10-16T12:25:01.694263+00:00`，不是歷史公告時刻。

本輪共5個 Windows HTTP 請求，台積電PDF成功，兩家公司SEC submissions及已知台積電6-K原文、索引共4次HTTP403；原始403回應及headers亦保存，不解析為JSON索引或有效申報。本輪只測指定路徑，不能推論所有來源不可取得。

先封存原文、metadata、headers、失敗觀察、取得腳本及凍結協定，再備份取回驗證整包SHA、manifest與CRC，最後才從取回包解析PDF。封存SHA `0bf208b20ce67ee0741e725dca79069f2cf7d6a94bb5a723bce0ab328972d284`。備份位於同檔案系統，沒有宣稱已具離機災難恢復。

PDF第1頁確認TSMC、2024Q4及可見日期2025-01-16，並重播毛利率59.0%、EPS新台幣14.45元、合併營收新台幣868.46十億元，共2頁。未以PDF內可見日期、下載時間或HTTP修改時間補造首次公開時刻；SEC接受時間仍空白。此輪沒有財務預測、建模、訊號或績效宣稱。

累計兩家公司2024Q4原始盈餘公告皆已取得，24公司季中仍有22季缺原文，全部仍未通過完整時點／版本驗收。原先[來源試點報告](../operating_pilot_20261016/report.md)是此輪之前的觀察快照。

## 使用者提供電腦的方式

目前已有Windows命令操作通道，無需再給帳密。若要改由Desktop Commander連線，在Windows開啟已安裝的Desktop Commander，登入原帳號並保持程式運作；於 https://mcp.desktopcommander.app/ 確認該裝置Online，再回覆「已上線」。工具連線不等於已有瀏覽器點擊能力；上線後仍須以實際可用工具確認。

若一般瀏覽器可以正常下載SEC文件，也可將原始文件放在 `inputs/operating_pilot_20261016/incoming/`，由後續流程驗證，無需先自行改名、解析或壓縮。本機目前遇到的403是來源取得阻礙，增加操作授權本身不保證解除。
