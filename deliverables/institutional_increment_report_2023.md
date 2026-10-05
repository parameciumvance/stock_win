# 法人特徵第一輪 Ridge 診斷（2023 年內）

## Tasks

- [x] 完成 2023 全年官方法人日報與逐列恆等式檢查。
- [x] 普通股正規化 226,920 筆，無重複鍵；平均每日股票池覆蓋率 96.92%。
- [x] 產生 238,761 列、999 個代碼的因果特徵；缺列保留缺值。
- [x] 同股票池比較量價 Ridge、量價＋法人 Ridge 與波動率排序。
- [x] 18 項來源、成本、時間切分與因果邊界測試通過。
- [ ] 完成跨年比較，處理本轮只有 17 個訓練訊號日的限制；見後續 2024 study。

## 固定研究設定

設定和程式先提交至 GitHub，再執行比較。10 個量價特徵，加上外資／投信／三大法人日淨買超除以當日 raw quote volume 的 1／5／20 日值與平均；法人特徵只用前一市場日及以前的來源。所有模型以完整共同特徵股票池評估，成交價至少 10 元、20 日均成交金額至少 1,000 萬元、120 個完整市場日價格觀測。

StandardScaler 只以訓練資料擬合，Ridge alpha=1000。訓練訊號 2023-07-11～08-02，共 11,135 列但只有 **17 個訊號日**；所有標籤窗口在 08-31 前結束。測試 09-01～12-29，共 83 日、49,908 列，平均每日池 601.3 檔，每日取前 10%。這些年月的行情和結果已有其他研究查看，**不是新獨立留出**。

目標：訊號日後第 1 市場日一般市場開盤報價進場、第 20 市場日收盤報價退出的個股淨報酬，減同期 0050 毛報酬。要求股票與 0050 未來 20 日均有完整正價格；佣金每邊 0.1425%、賣出稅 0.3%、滑價每邊 0.5%。報價還原採既有 2023–2026 連續輸入，SHA-256 已固定，來源是此次恢復的既有建置，不能說使用了本機不存在的最新 2015–2026 中間檔。

## 結果

| 方法 | 每日 Top 10% 的平均 20 日成本後相對報價報酬 | 每日 rank IC 均值 |
|---|---:|---:|
| 量價 Ridge | −1.592% | 0.1082 |
| 量價＋法人 Ridge | −1.403% | 0.1189 |
| 僅 20 日波動排序 | −1.593% | −0.0829 |
| 同股票池等權均值 | −2.302% | — |

加入法人改善約 **0.190 個百分點**，仍落後 0050 毛報酬。訓練日期太少，不能判定改善穩定。83 個測試日期的持有窗口重疊，不是 83 組獨立交易；表格數字不能累加為年度策略報酬、CAGR 或實際 30 萬資產淨值。這也不適合與全年、不同池的 long-volatility 表直接相比。

這是預測成本後相對報酬的迴歸診斷，不是校準過的飆股機率。既有飆股模組仍為另一個研究目標。下一階段先核對跨年增量，才評估是否足以改變正式排名用途。

## 再現

`institutional_twse_2023_repro_bundle.zip` 已封存：239 日 T86 raw/meta、2023 calendar/meta、正規化法人、特徵、此次使用的價格與歷史普通股池。508 members；114,495,119 bytes；SHA-256 `2e2654a125e7b33ac284cd5796be151738101b2ecb88f8407fae0f99317c4e94`。ZIP CRC 和每個 manifest 成員的 SHA-256 均通過。

解壓到 repo 根目錄後可執行：

```bash
python audit_institutional_increment.py --config configs/institutional_diagnostic_2023.json
python -m unittest test_institutional_increment twse_history.test_institutional twse_history.test_institutional_features twse_history.test_revenue_pilot -v
```

來源與完整性：`deliverables/institutional_acquisition_2023.json`。結果：`deliverables/institutional_increment_daily_2023.csv`、`deliverables/institutional_increment_summary_2023.json`。檔案識別：`libfile_df964b26b35881919117da1cebe40e77`。
