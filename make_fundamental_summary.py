"""Join fixed study results without choosing settings from historical outcomes."""
from pathlib import Path
import json

def run():
    years=[2024,2025,2026];rows=[]
    for year in years:
        revenue=json.loads(Path(f'deliverables/revenue_proxy/summary_{year}_lag45.json').read_text())
        credit=json.loads(Path(f'deliverables/margin/summary_{year}.json').read_text())
        tree=json.loads(Path(f'deliverables/fundamental_tree/summary_{year}.json').read_text())
        rows.append(dict(year=year,revenue=revenue,credit=credit,tree=tree))
    out=Path('deliverables/fundamental_tree/research_conclusion.md')
    lines=['# 月營收與信用特徵：固定研究結論','','本輪完成免費資料取得與三年度模型比較，尚未找到穩定的成本後相對優勢。',
        '原本 20 日飆股分類研究保留；此輪回歸目標是次日開盤至第 20 市場日收盤的成本後相對 0050 端點代理，分數不是飆股機率。',
        '', '| 年度 | 45 日延遲營收增量 | 信用增量 | 全特徵樹−量價樹 | 全特徵樹平均成本後相對代理 |',
        '|---|---:|---:|---:|---:|']
    for x in rows:
        r=x['revenue']['price_revenue_minus_price']['mean'];c=x['credit']['primary']['mean'];t=x['tree']['primary']['mean'];m=x['tree']['methods']['all_margin_tree']['mean_relative_quote_proxy']
        lines.append(f"| {x['year']} | {r*100:+.3f} pp | {c*100:+.3f} pp | {t*100:+.3f} pp | {m*100:+.3f}% |")
    lines+=['','各增量是在各自研究的相同當時共同股票池／同日已知完整選股結果上計算；營收、信用和樹研究的共同池不同，不能把三欄相加。',
        '詳細區塊區間、有效日期及未知結果數見各研究 JSON／報告；平均代理不是年度報酬，不能據此推算 30 萬本金盈虧。',
        '', '## 下一個需要決定的研究範圍',
        '', '建議保留原本 20 日飆股目標，同時另開「60 市場日相對報酬、每月換股」研究支線，測試較慢更新的月營收資訊。理由是特徵更新頻率與持有期的配合，並不保證提高報酬。',
        '這會改變標籤與換股規則，需要使用者決定後才固定新設計。採用後先寫下共同池、重疊持股批次、成本、未知端點及時間切分規則，再比較同池量價／全特徵 Ridge／固定梯度樹；不以當前較好的年度挑設定。',
        '本輪所有年份已研究，任何新持有期比較也只能稱探索；正式升級排名需要等事先固定後的新市場期間。',
        '', '## 完成與限制',
        '', '月營收代理、信用來源、十項信用因果特徵、年度 Ridge 與固定梯度樹、來源包與模型／選股明細包均已完成並核對。',
        '嚴格月營收首次公告時間及完整修訂歷史、TPEx、精確股權現金帳維持各自 pending。來源可能事後修訂；端點代理不能證明成交。',
        '復原順序見 `docs/FUNDAMENTAL_RESEARCH_RESUME.md`，進度見 `docs/RESEARCH_PRIORITIES.md`。','']
    out.write_text('\n'.join(lines))

if __name__=='__main__':run()
