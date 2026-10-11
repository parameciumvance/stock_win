# 上櫃量價研究重跑

來源：2023–2026截至2026-10-02官方行情及政策A逐列分類。四年905市場日、758,875筆探索池列。`summary.json`描述第一階段未扣成本特徵輸出；其未完成清單不代表後續比較仍未完成。

已完成：`rule_comparison.md`為原成本／0050端點比較；`ridge_report.md`為前一年年底已結束標籤訓練之固定Ridge、同池規則及配對區塊診斷。29項來源／量價／比較測試通過。日訊號端點均值不是投資組合累積報酬。

## 重跑

1. 按四年 `saved_checkpoint.json` 還原行情／分類原始包；先核對包及每個來源SHA。三類公司行動完整解析器及例外仍留在來源報告，不作精確股東現金帳。
2. 若重新產生特徵，執行 `python3 tpex_proxy_features.py`；此步需要四年行情與 `event_coverage.json`，2026和2025應使用有前一年行情的事件核對結果。
3. 本目錄的 `saved_checkpoint.json` 指向已保存取回驗證的特徵／模型重跑包。解壓後含 `features_and_gross_labels.csv.gz`、完整標準 `benchmark_restore/prices_adjusted_2023_2026.csv.gz`、配置、程式、排名、係數、每日明細與SHA manifest；可直接執行 `python3 tpex_rule_comparison.py` 及 `python3 tpex_ridge_baseline.py`。
4. `python3 -m unittest test_tpex_proxy_features test_tpex_rule_comparison test_tpex_ridge_baseline` 驗證特徵時點、未知結果、基準停牌日期和區塊缺值。新增上櫃法人及事件特徵测试另列，須先還原原始試點來源。

資料／係數／每日明細已保存；大型檔不入Git。價格源SHA與既有上市60日規格完全一致，未另選對模型有利的基準。所有年度均為研究資料，沒有新獨立留出。

空白資料目錄還原後，規則摘要、Ridge摘要、每日結果及全部排名四份檔案SHA完全一致，見 `clean_restore_replay.json`；此檢核不是重新下載原始來源。固定依賴見 `requirements_tpex.txt`。

下載資料包後，在空白checkout以 `python3 restore_tpex_checkpoint.py ARCHIVE --sha256 EXPECTED_SHA --destination .` 還原固定量價／0050／法人／營收重跑包；年度行情包用 `--destination deliverables/tpex_YYYY`。工具先核對整包及所有manifest檔案，再還原資料，保留Git的程式與配置；遇到不同的既有資料就停止。

`make tpex-fixed-comparison` 重跑規則與固定Ridge；`make tpex-event-comparison TPEX_END_YEAR=2023` 重跑已還原年度的事件規則，`make tpex-event-verify TPEX_END_YEAR=2023` 核對全部選股。`make test-tpex` 目前43項通過，真實来源小型fixture已放repo，測試不需網路。
