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
- [ ] 先補已核實公告時點的免費月營收原始快照，再評估法人及融資融券特徵；維持 TPEx 在另案資料工程中。
- [x] 主要分類評估加上「前 10% 命中率 ÷ 當日股票池正例率」和逐年度相對報酬排名相關性。
- [ ] 暫緩繼續深挖無明顯優勢策略的逐檔公司權益；先用帶成本的還原價代理淘汰研究方向，若有穩定增益再核精確持股與現金帳。
- [x] v79–v81 診斷加入三份上游大檔的 SHA-256 驗證與 `make diagnostics` 重算入口；缺檔即停止。
- [ ] 舊版腳本與證據檔逐步改由 Git/tag 管理，拆出規格與 CHANGELOG；其餘上游重建仍需自動化，大型檔案的 GitHub Releases／DVC 使用方式待設計。

2024–2026 已用於模型研究；2015–2023 的資料健康與標籤統計也已查看，不能因其剛下載就稱獨立留出。**後續模型選擇須預先固定並等新市場期間評估**。30 萬元仍是虛擬本金，沒有可宣稱的實股 NAV。
