"""Render the limited 2025 merger-ledger result from reproducible outputs."""
from pathlib import Path
import pandas as pd


def main():
    root = Path(__file__).parent
    out = root / "output_research_v5"
    comparison = pd.read_csv(out / "comparison_v4_v5.csv").set_index("method")
    rights = pd.read_csv(out / "merger_rights_ledger.csv", dtype={"predecessor": str})
    names = {"0050_hold": "0050 買入持有", "equal": "普通股等權",
             "momentum_60_skip5": "60 日扣 5 日動能", "logistic": "Logistic Top 10%",
             "hist_gradient_boosting": "梯度樹 Top 10%"}
    table = ["| 選法 | v4 下市歸零 | v5 合併權益 | 差額（百分點） |",
             "|---|---:|---:|---:|"]
    for key, label in names.items():
        r = comparison.loc[key]
        table.append(f"| {label} | {r.total_return_proxy_v4:+.2%} | "
                     f"{r.total_return_proxy_v5:+.2%} | {r.delta_percentage_points:+.2f} |")
    tree_gap = 100 * (comparison.loc["hist_gradient_boosting", "total_return_proxy_v5"] -
                      comparison.loc["0050_hold", "total_return_proxy_v5"])
    contents = f"""# 台股飆股模型：2025 合併權益修正 v5

更新日期：2026-09-29。沿用 v4 的 2024 訓練資料、2025 留出樣本、模型分數、每月選股及交易成本，將實際持有的三起合併事件改為已核實對價。**這仍是價格與小數持股的代理回測，不能視為完整股東總報酬。**

## Tasks 本輪進度

- [x] 對照 v4 交易紀錄，找出 5 筆下市歸零：2888 一筆、6288 三筆、2809 一筆
- [x] 從發行公司／證交所查核生效日期、換股比例、辛種特別股和現金支付日期
- [x] 建立逐筆權益轉換紀錄；合併交付後的 2887I 特別股只供估值及退出，不進普通股選股池
- [x] 京城銀現金對價按 0.3% 證交稅扣減；生效當日開盤前不得動用新股和現金
- [x] 重跑五種方法，與 v4 對比；35 項測試通過
- [ ] 建立全部股息、減資退現、認股款及零碎股實際結算的股東現金流帳
- [ ] 補齊多年度資料與逐年 walk-forward，驗證跨市場狀態穩健性

## 官方對價與帳務時點

| 原股票 | 生效日 | 每一原普通股取得 | 本版資料來源 |
|---|---|---|---|
| 2888 新光金 | 2025-07-24 | 2887 普通股 0.672 股＋2887I 辛種特別股 0.175 股 | [台新新光金最終發行公告](https://www.tsholdings.com.tw/tsh/relations/major/1752058440000/)；[證交所 2887I 掛牌公告](https://www.twse.com.tw/rwd/zh/announcement/announcement_detail?id=47CFA14B66E411F0AC832D9568472C08&response=html) |
| 6288 聯嘉 | 2025-08-15 | 3717 聯嘉投控普通股 1 股 | [證交所股份轉換公告](https://wwwc.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d697fc438f01989dc23d80029a.pdf) |
| 2809 京城銀 | 2025-10-01 | 2890 永豐金普通股 1.2375 股＋新臺幣 26.75 元現金，現金先扣 0.3% 證交稅 | [京城銀股東權益問答](https://customer.ktb.com.tw/new/note/c32432b0) |

京城銀公告指出，股票與扣稅後現金同日入帳。為避免當日開盤交易先花用後到的權益，程式在當日開盤委託之後才轉換持股；當日收盤以接續股票行情估值，現金自下一個開盤開始可投資。股東匯款手續費及零碎股結算沒有可用的逐戶資料，未納入。2887I 的官方 2025 行情有 110 個交易日，僅用於原 2888 持股換得權益的估值及往後賣出。

## 2025 留出結果

{chr(10).join(table)}

五筆原先歸零的持股已逐筆轉為可追蹤權益，沒有尚未核實而被持有的下市事件。新舊模型機率與 2025 留出 PR-AUC 完全相同；本輪只改了組合權益。梯度樹仍比 0050 少 **{abs(tree_gap):.2f} 個百分點**。`merger_rights_ledger.csv` 保留每筆原股合成單位、轉換時已知價格因子、換得實股數、稅及現金；`comparison_v4_v5.csv` 保留逐法差額。

## 解讀邊界

舊版累積價格因子創造的是參考價連續「合成單位」。轉換當日以原持股單位乘當時已知因子還原成對價計算用股數，再按新股票當日因子回到估值單位；此法維持 v4 的價格代理口徑。除了上述三起合併，持股股息、減資退現、現增認股、實際整張／零股結算、最低手續費、真實委託佇列和價格衝擊仍未建立。停牌缺價仍沿用先前最近行情估值；沒有估價模型。條件式收益及 Sharpe 不能稱為實盤可實現績效，也不是投資建議。

單一 2025 年留出尚無跨年度穩健性證據。下一階段應補完整持股現金流與更長行情，再做 expanding walk-forward；不能用這一年挑參數後宣稱樣本外績效。
"""
    (root / "research_report_2025_v5.md").write_text(contents)


if __name__ == "__main__":
    main()
