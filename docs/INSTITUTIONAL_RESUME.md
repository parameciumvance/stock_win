# 2024 法人比較接續方式

目前已重現 2023 結果、完成 18 項測試。2024 的原取得數據和配置已保存，
但原始／正規化暫存輸入經平台清理；備份請求沒有成功回覆，搜尋和最近清單
未找到可用檔案，不能宣稱其保存成功或永久不存在。

目前環境不能直連 TWSE；一次官方端點測試在 10 秒逾時。
2024 模型沒有完成結果。以下流程在能連 TWSE 的 Python 主機執行，
例如既有 WSL Ubuntu。沒有實股交易動作，不更改已固定的模型選擇或成本。

## 恢復並檢查

將已保存的 114 MB `institutional_twse_2023_repro_bundle.zip` 下載至 repo 根目錄，
在 repo checkout 內執行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install numpy pandas scikit-learn
python3 resume_institutional.py --bundle institutional_twse_2023_repro_bundle.zip --check-only
make test-institutional
```

既有 Python 環境可直接執行；套件安裝建議在該專案的虛擬環境內。
包 SHA-256 固定為
`2e2654a125e7b33ac284cd5796be151738101b2ecb88f8407fae0f99317c4e94`。
檢查器驗證所有來源成員；若既有同路徑檔案不同則停止，先保留差異再處理，
不覆蓋不同的研究輸入。

## 在可連線主機補抓與比較

```bash
python3 resume_institutional.py --fetch
```

先用 10 秒官方樣本檢查連線；失敗就停止，不建立年度請求佇列。
通過後：

1. 補齊官方 2024 月交易日曆，確認 242 日。
2. 用 `ALLBUT0999` 逐日抓取 T86，依既有歷史普通股池篩選。
   已保存的 raw/meta 會核對 URL 和 SHA-256 後重用；資料缺列不補零。
3. **先封存** `deliverables/institutional_twse_2024_source_checkpoint.zip`，
   驗證原始檔、meta、交易日曆及正規化輸入。此包需搭配 2023 完整重跑包。
4. 建立連續 2023–2024 特徵，執行先前固定的
   `configs/institutional_diagnostic_2024.json`，匯出每日比較、摘要與模型係數。

若下載途中停止，原命令可續抓；不要同時啟動多個下載／模型程序。
先檢查是否有原程序，程序結束後才重新執行。
新下載的抓取時間和檔案 hash 可能不同，需記錄新輸入與舊統計差異，
不能假稱還原了原先的 bytes。

如由使用者自己的主機執行，可把 source checkpoint 上傳回對話，
即可在此環境恢復法人輸入並完成／核對 2024 比較。
使用者不必傳送帳號憑證。

## 驗證範圍

本次已實際驗證：2023 包全體來源 hash／ZIP CRC、18 項邊界測試、
2023 模型重跑（指標差 0）、接續工具還原／檢查模式與編譯。
此環境尚未執行成功的 2024 下載分支及跨年模型，維持 pending。
所有結果仍是已研究歷史的報價代理，不是獨立留出、可證明成交或實股 NAV。

