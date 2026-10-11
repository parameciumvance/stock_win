# 固定上櫃事件研究重跑入口

本分支保留營收45／60日延遲代理、前五市場日連續法人買超、價格帶量突破、交集及既有量價Ridge。没有門檻搜尋、模型調參或實際成交帳。資料截至2026-10-02。

## 最小封存輸入

從已保存的資料包下載以下兩檔，再於Git checkout根目錄執行。持久資料識別與完整驗收紀錄見 `deliverables/tpex_features/saved_checkpoint.json` 及 `deliverables/tpex_flow_2026/event_saved_checkpoint.json`。

| 檔名 | SHA-256 |
|---|---|
| tpex_features_rules_ridge_2023_2026_checkpoint.zip | 17b48b2adaae713592245b6cdd5a6e4db146a793c2f54bbc096553700a56b7ac |
| tpex_flow_events_2026_checkpoint.zip | 21e4eaf93412aa6e58c4ff3abee50c218a6008abd311cf50255ab0d243a95325 |

第一檔供應凍結量價特徵、Ridge係數摘要與0050基準，第二檔供應四年正規化法人、月營收、日曆和已驗收事件輸出。原始法人來源逐筆重建需另取各年原始來源包；這兩檔不含所有年份的法人原始快照。

```sh
python3 -m pip install -r requirements_tpex.txt
python3 restore_tpex_checkpoint.py /path/tpex_features_rules_ridge_2023_2026_checkpoint.zip --sha256 17b48b2adaae713592245b6cdd5a6e4db146a793c2f54bbc096553700a56b7ac --destination .
python3 restore_tpex_checkpoint.py /path/tpex_flow_events_2026_checkpoint.zip --sha256 21e4eaf93412aa6e58c4ff3abee50c218a6008abd311cf50255ab0d243a95325 --destination .
make test-tpex
make tpex-event-verify TPEX_END_YEAR=2026
```

還原工具先核對整包及每個成員雜湊，保留Git中的程式與配置；已存在且不同的資料會停止，請使用空白資料目錄的checkout。

## 從凍結輸入重新計算

```sh
make tpex-event-comparison TPEX_END_YEAR=2026
make tpex-event-verify TPEX_END_YEAR=2026
make tpex-event-report TPEX_END_YEAR=2026
make tpex-sample-health TPEX_END_YEAR=2026
```

輸出先寫暫存檔，關閉並完整讀回後才發布；summary記錄輸入／輸出SHA，完成標記避免中途結果被當成驗收完成。逐筆重播核對每個共同池、選股代號、固定分數、端點、未知數和每日均值。

`tpex-long-history-probe`會重新存取公共來源，僅抽查2015／2018／2020／2022四日，不會建立八年完整股票池或宣稱新的留出績效。2015／2018法人舊16欄格式尚未進入生產解析器。

## 解讀

主要結果見 `crossyear_review_through_2026.md`，樣本限制見 `sample_health_through_2026.md`。區間為已知選股日的條件重疊窗口均值；持股數不同、未知端點和修訂營收代理仍是限制。六個三規則交集主區間都涵蓋零，不能稱穩定勝過0050，也不能換算成30萬元實際帳戶績效。
