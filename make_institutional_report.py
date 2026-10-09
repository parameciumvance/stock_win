"""Render a verified annual research report from acquisition and diagnostic outputs."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', required=True, type=int)
    args = parser.parse_args(); year = args.year
    out = Path('deliverables')
    summary = json.loads((out / f'institutional_increment_summary_{year}.json').read_text())
    acquisition = json.loads((out / f'institutional_acquisition_{year}.json').read_text())
    uncertainty = json.loads((out / f'institutional_uncertainty_{year}.json').read_text())
    pool = json.loads((out / f'institutional_pool_audit_{year}.json').read_text())
    if not acquisition['normalized_rows_equal_reparsed_raw'] or summary['config']['study_name'] != str(year):
        raise ValueError('Source/year verification missing')
    if summary['test_dates'] != uncertainty['observed_dates']:
        raise ValueError('Uncertainty date count differs from model output')
    primary = uncertainty['intervals'][str(uncertainty['config']['primary_block_length'])]
    delta = primary['flow_minus_price']
    metrics = summary['daily_mean_metrics']
    lines = [f'# {year} 法人特徵固定跨年比較', '',
        f"以 {summary['train_first_signal']}～{summary['train_last_signal']} 訊號訓練，"
        f"標籤最晚於 {summary['train_last_label_end']} 結束；參數與成本先固定，沒有調參。", '',
        f"{acquisition['market_days']} 個官方市場日、{acquisition['common_flow_rows']:,} 筆普通股法人紀錄已逐筆由原始 JSON 重建核對。",
        f"研究股票池平均每日來源覆蓋 {acquisition['mean_daily_coverage'] * 100:.2f}%；缺列不補零。", '',
        f"模型評估 {summary['test_dates']} 個日期、{summary['test_rows']:,} 筆共同池紀錄。",
        '市場時計使用全市場日期；0050 重新對齊，停牌缺价不補值。', '',
        '| 方法 | Top 10% 平均 20 日扣成本相對 0050 報價報酬 | 每日 rank IC 均值 |',
        '|---|---:|---:|']
    for name, label in [('price_ridge', '量價 Ridge'), ('price_flow_ridge', '量價＋法人 Ridge'), ('vol20_rank', '僅 20 日波動排序')]:
        lines.append(f"| {label} | {metrics[name + '_top_net_relative'] * 100:+.3f}% | {metrics[name + '_rank_ic']:+.5f} |")
    lines += [f"| 同池等權 | {metrics['pool_net_relative'] * 100:+.3f}% | — |", '',
        f"法人相對量價的平均差異為 {delta['mean'] * 100:+.3f} 個百分點；20 日區塊假設下 95% 區間為 "
        f"[{delta['lower_95'] * 100:+.3f}, {delta['upper_95'] * 100:+.3f}] 個百分點。",
        f"{uncertainty['months_observed']} 個月份中 {uncertainty['monthly_flow_improvement_count']} 月改善、"
        f"{uncertainty['monthly_flow_decline_count']} 月下降。",
        '配對 circular block bootstrap 固定 5,000 次與 10／20／40 日區塊，區間只代表重抽樣假設。', '',
        '## 當時股票池與缺價', '']
    for scope, s in pool['summary'].items():
        lines += [f"- {scope}：{s['signal_dates']} 訊號日，其中 {s['dates_with_any_label']} 日有可比較標籤；"
            f"法人特徵不完整 {s['flow_missing_rows']:,} 列；已有標籤日期的未來報價條件剔除 "
            f"{s['future_label_removed_on_observed_dates']:,} 列。"]
    lines += ['', '原結果使用未來標籤完整的共同池；當時排名另封存，未知结果不補零、不事後換股。',
        '標籤缺失的明細見 `institutional_pool_unknown_top_' + str(year) + '.csv' + ('.gz' if pool['config'].get('compress_unknown_top') else '') + '`。', '',
        '## 口徑與限制', '',
        '特徵只使用訊號當日量價與前一市場日及更早的法人資料；1／5／20 日窗口須完整。',
        '次市場日還原開盤進場、t+20 還原收盤出場，買賣手續費各 0.1425%、卖出稅 0.3%、兩邊滑價各 0.5%。',
        '0050 對照為同窗口毛報酬；個股已扣上述成本，股票與基準的未來報價條件均須完整。',
        '每日選股的 20 日窗口重疊，以上是每日等權的報價代理平均，不能累加為年度報酬或視為可成交 NAV。',
        '這些年份已用於歷史研究；固定方法也不能讓既有資料變成新獨立留出。',
        '法人來源於目前回抓，不能證明完整的首次公告時刻與修正歷史，使用前一市場日是研究約定。', '',
        '來源、固定配置、模型係數、每日比較、區塊診斷與股票池稽核均有各自檔案；原始包另封存。', '']
    path = out / f'institutional_increment_report_{year}.md'
    path.write_text('\n'.join(lines)); print(path)


if __name__ == '__main__':
    main()
