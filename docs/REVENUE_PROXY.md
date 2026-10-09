# 免費月營收延遲代理研究

使用者於 2026-10-10 採用此探索路線。它使用目前下載的歷史表，數值可能事後修訂；延遲並不等於已驗證的當時可得版本。正式公告時刻 ledger 仍 pending。

## 固定方法

來源為公開資訊觀測站 `nas/t21/sii/t21sc03_{民國年}_{月}_{0或1}.html`，分別包含國內與國外上市公司；下載區間 2022-01～2026-07。保存 HTML、URL、HTTP 狀態、下載時間與 SHA-256；以 CP950 無損解碼，檢查年月、千元單位、國內／國外分類與唯一公司月份。普通股资格由既有歷史價格股票池決定，不使用目前上市清單過濾。

月底後 45 個日曆日的下一市場日為假設可用日期，另列 60 日敏感度。單月年增、月增、連續三月合計年增、年增較三月前變化、營收對數共五個特徵；比例固定截至 −1～5。缺月不跨越，零／負當月營收不取對數，最新月不完整時不改用較舊完整月；超過月底 100 日視為過期。不把這個假設寫入 `published_at`。

共同池要求當日量價、前市場日法人及延遲營收特徵完整，選 Top10% 前不檢查未來結果。比較量價、量價＋法人、量價＋營收、三者合併 Ridge alpha=1000，並列波動及營收年增排序。缺進出場端點的選中股票保持未知；有任一未知，當日整組選股均值即缺失，不補零或替換。rank IC 僅對已知端點子池計算，明示其條件限制。

使用既有成本與 t+1 還原開盤／t+20 還原收盤，相對 0050 同期端點毛報酬。途中停牌不刪全市場交易日；無端點不填價。這與原法人報告的完整未來 20 日報價篩選不同，不把前後報告數字差異歸因於營收。

2024／2025／2026 各以前一年年底已完成標籤的 2023 起 expanding 訓練；scaler 只擬合訓練集。主比較為營收模型−量價，次比較為三者−量價法人。預先固定配對 circular block bootstrap 10／20／40 日、5000 次、seed 20261010；只用雙方選股結果完整的日期，缺日期造成時間壓縮需一併解讀。這些年份已研究，不是新的獨立留出，也不是年度 NAV 或飆股機率。

## 重建

先依 `docs/INSTITUTIONAL_RESUME.md` 取得凍結價格、2023–2026 法人流量與日曆。重建四年特徵：

```bash
python3 -m twse_history.institutional_features --years 2023 2024 2025 2026 --asof 2026-10-02 --prices twse_history/output_multiyear_2023_2026_asof_20261002/prices_adjusted_2023_2026.csv.gz --flows inputs/institutional_twse_2023.csv.gz inputs/institutional_twse_2024.csv.gz inputs/institutional_twse_2025.csv.gz inputs/institutional_twse_2026.csv.gz --output inputs/institutional_features_2023_2026_asof_20261002.csv.gz
make revenue-proxy-fetch
make revenue-proxy-diagnostics
make test-revenue-proxy
```

重建 gzip 的時間標記可能改變壓縮檔 hash；研究設定鎖定本輪實際輸入 bytes，並另存解壓 CSV hash 與舊三年重疊資料逐筆檢查。研究來源包將含本輪輸入，避免重建後任意放寬 hash 閘門。

`--fetch` 僅補缺少的來源，既有 cache 先核 checksum。封存原始快取後可離線執行 `python3 -m twse_history.revenue_proxy` 重建營收表與特徵。完整來源核對見 `deliverables/revenue_proxy/acquisition.json`；比較結果見同目錄 `report.md`。
