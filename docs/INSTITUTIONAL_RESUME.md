# 2024 法人比較接續方式

2026-10-09 已依本文件完成本機接續：2023 重跑包驗證還原、2024 全年補抓、
來源先行封存、連續特徵與固定跨年模型均已完成。18 項測試通過。
結果見 `deliverables/institutional_increment_report_2024.md`，完整性紀錄見
`deliverables/institutional_recovery_20261009.json`。

2024 普通股流量 241,431 列，與舊統計一致；此次為重新抓取，不能宣稱還原了
遺失的原始 bytes。舊平台備份請求的結果仍未確認；本次 ZIP 已保存於本機。
本機 TWSE 連線已通過，未進行實股交易，未更改固定模型選擇或成本。
以下保留重跑步驟；本機資料包位於 `ref/institutional_twse_2023_repro_bundle.zip`。

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
2026-10-09 本機已成功執行 2024 下載、來源封存及跨年模型；來源核對與結果詳見上述報告。
所有結果仍是已研究歷史的報價代理，不是獨立留出、可證明成交或實股 NAV。

## 2026-10-09 初次檢查紀錄（提供資料包前）

- 已準備專案 `.venv`（Python 3.14.4、numpy 2.5.3、pandas 3.0.6、scikit-learn 1.9.1）。
  系統缺少 ensurepip，改用 `uv pip install --python .venv/bin/python numpy pandas scikit-learn` 安裝依賴。
- `make test-institutional PYTHON=.venv/bin/python`：18 項測試全部通過。
- 本機取得網路執行權限後，10 秒 T86 樣本請求成功：2024-01-05、
  `ALLBUT0999`，回應 `stat=OK`、1,154 列；此為連線檢查，尚未完成年度來源驗證。
- 專案、Linux 家目錄及 Windows 使用者的 Downloads/Desktop/Documents 搜尋未找到
  指定的 `institutional_twse_2023_repro_bundle.zip`；需要提供該包的路徑或下載連結。
- `.venv/bin/python resume_institutional.py --check-only` 停在
  `Restore the verified price input first`。未啟動年度下載或模型程序，2024 結果仍為 pending。

取得原包後，先執行上述 `--bundle ... --check-only` 核對，再執行 `--fetch`。
既有 ref 資料不能替代指定 hash 的研究輸入；本次未修改固定配置或既有研究結果。

## 2026-10-09 完成紀錄

使用者將原包放入 `ref/` 後，已驗證並還原全部來源，執行 `--fetch` 成功。
2024 source checkpoint 為 19,407,580 bytes，511 members，CRC 與 509 個
manifest 成員 hash 均通過。新來源與舊取得統計的差異全為零，逐欄核對
正規化資料與 raw 重建結果一致；新舊 hash 保留在完整性紀錄中。

固定模型比較 237 個有效訊號日：量價 Top 10% 平均成本後相對報價報酬
−4.591%，加入法人為 −4.717%，降低 0.126 個百分點；不支持此次法人增量改善。
最後五個 2024 訊號日因固定讀取範圍缺完整未來 20 日標籤而未納入。
來源 ZIP 已存本機 deliverables，依既有 `.gitignore` 不納入 Git。



## 接收上傳包後及 2025 接續

2024 上傳包已完成雲端來源重跑與模型核對。恢復既有資料可用：

```bash
python3 resume_institutional.py --bundle ref/institutional_twse_2023_repro_bundle.zip --checkpoint-2024 deliverables/institutional_twse_2024_source_checkpoint.zip --check-only
make institutional-pool-audit
```

2025 固定設定沿用相同特徵、Ridge alpha、選股比例與成本，
訓練只納入標籤於 2024-12-31 結束前已知的 2023–2024 訊號。
官方日曆須與封存價格的市場交易日聯集完全一致；未知法人列不補零。
2025 已研究過，這仍是探索性歷史比較。

```bash
python3 resume_institutional.py --year 2025 --check-only
python3 resume_institutional.py --year 2025 --fetch
```

只做連線檢查可用 `--year 2025 --probe-only`；使用 2025-01-06 交易日，
HTTP 狀態、最終 URL、日期及法人加總通過才啟動全年佇列。
來源包將先寫入 `deliverables/institutional_twse_2025_source_checkpoint.zip`，
再建 2023–2025 特徵、執行固定配置。此包依賴既有 2023 完整包與 2024 checkpoint，
不是單獨包含所有價格／前年度來源的完整研究包。
來源 ZIP 不納入 Git；程式與小型成果由 Git 追蹤。


2025 官方日曆為 243 日，但 0050 因分割在 6/11–6/17 停止交易，
只剩 238 個實際報價日期。模型的市場時計改用全市場觀察日期聯集，
0050 重新對齊，缺價不補值；仍依原完整未來報價條件留下可比較標籤。
這項修正發生在 2025 模型結果產生前，並有停牌邊界測試。
官方來源：[2025-05-14 證交所新聞稿](https://www.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d696b406fc0196ce27c2e90063.pdf)。
