# 採用 A 與上櫃 2023-01 建置

2026-10-11 使用者採用官方編碼規則候選納入探索股票池；模型與事件規則參數不變。

## 固定政策

政策入口：configs/tpex_pool_policy.json。主探索池包含 confirmed_ordinary 與 ordinary_stock_rule_candidate；已核實子集另列 confirmed_subset。個別查詢與 ISIN 證據優先；已存在且矛盾的分類不可被四位數字規則覆蓋。unknown 永遠保留，CFI／產業／原始掛牌日／公告時間不推定。歷史行情存在是本輪日股票池證據，現在存續與現在市場身分不作排除條件；完全無行情或停牌主檔仍 pending。

## 首月完成

2023-01 共 13 日、11,798 筆各類證券行情；探索池 10,498 筆、已核實子集 10,238 筆，260 筆差異為規則候選。所有日期、唯一代碼、完整價格 OHLC 檢核通過；兩個池只差證據政策，尚未加入流動性／歷史窗口條件或模型評估。

TWSE FMTQIK 月實際成交日作下载索引。另取得櫃買官方頁所宣告的開休市表：https://www.tpex.org.tw/www/zh-tw/bulletin/tradingDate?date=2023&response=json 。選用股票交易系統，不能誤用國際債券 1/16 最後交易日。1/18、1/19 股票只交割不交易，春節後 1/30 恢復交易；1 月工作日扣官方休市後的 13 日期，與下載索引及原始回應逐日一致。calendar_check_202301.json 保存獨立核對。原 summary 的 calendar limitation 是下载時狀態，本輪只解除 1 月限制；尚未確認其他月臨時休市。

資料仍為原始未還原 OHLC，尚不能直接訓練或建立報酬標籤。沒有新增回測結果。

## 工具與驗證

下載：python3 acquire_tpex_month.py --year 2023 --month 1。每月分批、每日快取／SHA／25 秒網路總時限；失敗停止，不當成休市。月輸出只在全部索引日期取得並驗證後建立。需要之前分類原始包和當前採用政策，來源類別不會自行回填。

python3 -m unittest test_tpex_pilot test_tpex_type_recovery test_tpex_pool：14 項測試通過。新測試包含規則候選 CFI 留空、特別股排除與已知分類衝突優先。

首月 source_202301.zip：899,476 bytes，SHA-256 433e0773d6b1d0a92cab09cc093e1943e427a75a7a36be50b2ec3717951bce6d。35 ZIP 成員 CRC 及 34 來源／輸出 manifest hash 核對通過。內含 13 個 raw 日行情及 meta、日曆、櫃買開休市原始回應、逐列 pool 證據 CSV 與摘要；本包不重複之前 ISIN 分類包。

下一步繼續其餘月份與全年交易日核對，再生成年度型別資料及公司行動還原；完整普通股主檔和歷史 CFI 補查繼續保留待辦。已核實子集也有證據可得性偏差，不能單獨稱完整正式股票池。
