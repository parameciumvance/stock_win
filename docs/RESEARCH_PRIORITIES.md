# 研究優先序與 Tasks（2026-10-05）

- [x] 以同一股票池、同日封存分數，比較 20 日波動率和 ATR 單獨排序的飆股命中率及提升倍數。見 `deliverables/volatility_and_entry_barriers_report_2026_v81.md`。
- [x] 建立次日開盤進場、+20%／−10% 先觸及及 20 日固定持有的價格路徑與保守成本標籤；維持「報價代理、非可證明成交」標記。
- [x] 實作月營收「已核實公告時間 → 下一市場日才可使用」的特徵介面及邊界測試，見 `twse_history/asof_revenue.py`。
- [ ] 蒐集逐公司歷史月營收公告時刻與原始快照；再補法人買賣超、融資融券，評估增量價值，不用 2024–2026 反覆調參聲稱獨立改善。
- [x] 寫明更早年度行情的下載與完整年度檢核順序，見 `docs/DATA_SETUP.md`。
- [x] 取得 2015 年全年官方行情與公司行動，並與 2016 跨年建置；見 `deliverables/history_2015_acquisition_report.md`。
- [x] 取得 2016 年全年官方行情與公司行動，並與 2017 跨年建置；見 `deliverables/history_2016_acquisition_report.md`。
- [x] 取得 2017 年全年官方行情與公司行動，並與 2018 跨年建置；見 `deliverables/history_2017_acquisition_report.md`。
- [x] 取得並核對 2018 全年官方上市行情、公司行動與普通股池；見 `deliverables/history_2018_acquisition_report.md`。
- [x] 取得並核對 2022 全年官方行情及公司行動，與 2023 原始行情共同建置跨年價格；見 `deliverables/history_2022_acquisition_report.md`。
- [x] 取得 2021 全年行情及公司行動，並與 2022 共同建置；見 `deliverables/history_2021_acquisition_report.md`。
- [x] 取得 2020 全年行情及公司行動，並與 2021 共同建置；見 `deliverables/history_2020_acquisition_report.md`。
- [x] 取得 2019 年全年上市行情與公司行動，並與 2020 共同建置；見 `deliverables/history_2019_acquisition_report.md`。
- [x] 將 2015–2026 原始年度在連續區間共同建置並稽核例外；見 `deliverables/long_history_2015_2026_report.md`。上櫃 TPEx 仍需另建股票池、公司行動和授權檢核。
- [x] 以固定的次日開盤／20 日持有口徑壓力測試 2015–2023 波動基準；見 `deliverables/long_volatility_2015_2023_report.md`，九年中八年的成本後相對報價代理為負、九年的每日 rank IC 均值為負。不得稱獨立留出。
- [x] 核對免費月營收 OpenAPI 與 2024-01 官方靜態歷史表：均沒有逐公司公告時刻；保存原始樣本，見 `docs/MONTHLY_REVENUE_SOURCE_DECISION.md`。
- [x] 完成官方營收公告來源試點：台積電 2024-01～03 的新聞稿、SEC 6-K、兩份接受時間來源及交易日曆已核對，六項邊界測試通過；見 `deliverables/revenue_source_pilot_report.md`。
- [ ] 月營收正式特徵維持 pending：尚缺台灣首次公開時刻與完整修正歷史。要採用日期精度或延遲靜態代理須另行決定；TPEx 留在另案資料工程。
- [x] 免費法人 T86 三年度來源驗證、加總與普通股覆蓋試點、可續抓工具和 1／5／20 日因果特徵介面完成；見 `docs/INSTITUTIONAL_DATA.md`。
- [x] 2023 全年法人日報與因果特徵完成並封存重跑包；239 日、226,920 筆普通股流量、平均每日覆蓋 96.92%。
- [x] 同池、固定成本與 purged 標籤的 2023 內部 Ridge 增量比較完成；法人將 Top10% 平均相對報價代理由 −1.592% 改善至 −1.403%，只有 17 個訓練訊號日；見 `deliverables/institutional_increment_report_2023.md`。
- [x] 2024 免費法人 242 日、241,431 筆普通股正規化紀錄與連續 2023–2024 特徵生成完成；見 `deliverables/institutional_acquisition_2024.json`。
- [x] 2026-10-05 晚間恢復執行環境；由已保存重跑包驗證 506 個來源檔，18 項測試通過，2023 摘要與原結果完全一致，模型係數已匯出。見 `deliverables/institutional_recovery_20261005.json`。
- [x] 2026-10-09 由 ref 中的 2023 包恢復，補抓 2024 全年並先封存來源；509 個 manifest 成員 hash／CRC 核對通過。見 `deliverables/institutional_recovery_20261009.json`。
- [x] 固定 2023 訓練、2024 比較完成：237 個有效訊號日，法人 Top 10% 平均相對報價報酬較量價模型降低 0.126 個百分點；歷史結果不是獨立留出。見 `deliverables/institutional_increment_report_2024.md`。
- [x] 主要分類評估加上「前 10% 命中率 ÷ 當日股票池正例率」和逐年度相對報酬排名相關性。
- [ ] 暫緩繼續深挖無明顯優勢策略的逐檔公司權益；先用帶成本的還原價代理淘汰研究方向，若有穩定增益再核精確持股與現金帳。
- [x] v79–v81 診斷加入三份上游大檔的 SHA-256 驗證與 `make diagnostics` 重算入口；缺檔即停止。
- [ ] 舊版腳本與證據檔逐步改由 Git/tag 管理，拆出規格與 CHANGELOG；其餘上游重建仍需自動化，大型檔案的 GitHub Releases／DVC 使用方式待設計。

2024–2026 已用於模型研究；2015–2023 的資料健康與標籤統計也已查看，不能因其剛下載就稱獨立留出。**後續模型選擇須預先固定並等新市場期間評估**。30 萬元仍是虛擬本金，沒有可宣稱的實股 NAV。

