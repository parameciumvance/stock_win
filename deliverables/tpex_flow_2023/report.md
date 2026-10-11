# 上櫃2023法人全年與事件規則診斷

239個官方交易日、182,773筆法人紀錄、160,354筆探索池列有法人紀錄；探索池平均每日覆蓋82.94%。缺列維持未知，不補零。所有來源日期、七組買進減賣出、分組與最後總淨買超恒等式核對通過；正規化資料關閉後逐筆取回相符。

事件規則依事前配置，不搜尋門檻；2023沒有用同年度結果訓練Ridge。45／60日營收延遲代理，共197,047筆同池特徵、358,808筆選股與5,012組日訊號已核對。詳見 `deliverables/tpex_events/report_through_2023.md`。

2023所有單獨事件規則及交集相對波動排序的主區塊區間涵蓋零；三條件交集平均只1.47檔，不將不同已知日的正均值當成策略優勢。2024–2026來源及比較仍進行中。

重跑來源：`python3 acquire_tpex_flow_year.py --year 2023`；事件比較：`python3 tpex_event_comparison.py --end-year 2023`；核對：`python3 audit_tpex_event_comparison.py --end-year 2023`。需要先依 `deliverables/tpex_events/input_checkpoints.json` 還原固定量價／0050及月營收資料。

不是首次公布版本、實際成交或精確股東現金帳，也不是新的獨立留出。
