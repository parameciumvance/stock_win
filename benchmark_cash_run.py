"""Archive-first accounting audit of one fixed ETF benchmark; no orders."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

from cash_benchmark import parse_distributions, parse_split, physical_ledger, audit_ledger, csv12_product_matches
from research_reassessment import verified_bundle

from research_runtime import atomic_json, exclusive_lock, sha256
from source_checkpoint import package_sources, readback

ROOT = Path('inputs/benchmark_cash_20261019')
OUT = Path('deliverables/benchmark_cash_20261019')
POLICY = Path('configs/benchmark_cash_protocol_20261019.json')
REQUESTS = Path('configs/benchmark_cash_sources_20261019.json')


def policy():
    if sha256(POLICY) != json.loads((OUT / 'protocol_freeze.json').read_text())['protocol_sha256']:
        raise ValueError('Frozen cash benchmark protocol drift')
    return json.loads(POLICY.read_text())


def package():
    policy()
    cfg = json.loads(REQUESTS.read_text())
    result = json.loads((ROOT / 'raw/results.json').read_text())
    if result['config_sha256'] != sha256(REQUESTS) or result['workers'] != 2 or [r['request'] for r in result['requests']] != cfg['requests']:
        raise ValueError('Source request list differs')
    entries = {'protocol.json': POLICY, 'requests.json': REQUESTS}
    for record in result['requests']:
        path = ROOT / 'raw' / record['request']['filename']
        if json.loads(path.with_name(path.name + '.meta.json').read_text()) != record:
            raise ValueError('Metadata differs')
        if record.get('sha256') and sha256(path) != record['sha256']:
            raise ValueError('Source bytes differ')
    entries.update({'raw/' + p.name: p for p in (ROOT / 'raw').iterdir() if p.is_file()})
    with exclusive_lock(ROOT / 'acquisition.lock'):
        package_sources(ROOT, OUT, 'sources', entries)


def replay():
    c = policy()
    package, transfer = readback(OUT, 'sources')
    distributions = []
    sources = []
    with zipfile.ZipFile(package['retrieved']) as z:
        if hashlib.sha256(z.read('protocol.json')).hexdigest() != sha256(POLICY) or hashlib.sha256(z.read('requests.json')).hexdigest() != sha256(REQUESTS):
            raise ValueError('Archived policy/request bytes differ')
        results = json.loads(z.read('raw/results.json'))
        if results['config_sha256'] != sha256(REQUESTS) or results['workers'] != 2 or [r['request'] for r in results['requests']] != json.loads(REQUESTS.read_text())['requests']:
            raise ValueError('Archived source cohort differs')
        for record in results['requests']:
            if record['http_status'] != 200 or record['exit_code'] != 0:
                raise ValueError('Official source unavailable; no accounting promotion')
            name = record['request']['filename']
            body = z.read('raw/' + name)
            if hashlib.sha256(body).hexdigest() != record['sha256']:
                raise ValueError('Archived source hash differs')
            evidence = dict(source_url=record['request']['url'], source_sha256=record['sha256'])
            sources.append(dict(**evidence, filename=name, http_status=200))
            if name.startswith('dividends_'):
                year = int(name[10:14])
                distributions.extend(dict(**r, **evidence) for r in parse_distributions(body, year))
            else:
                split = dict(**parse_split(body), **evidence)
    distributions.sort(key=lambda r: r['ex_date'])
    manifest = verified_bundle(c['frozen_price_archive'], c['frozen_price_archive_sha256'])
    if manifest[c['frozen_price_member']] != c['frozen_price_sha256']:
        raise ValueError('Frozen price member differs')
    days, pieces = set(), []
    with zipfile.ZipFile(c['frozen_price_archive']) as z, z.open(c['frozen_price_member']) as stream:
        for chunk in pd.read_csv(stream, compression='gzip', dtype={'symbol': str}, chunksize=200000):
            days.update(chunk.date)
            pieces.append(chunk[chunk.symbol.eq('0050')][['date', 'open', 'close', 'adj_open', 'adj_close', 'causal_factor']])
    quotes = pd.concat(pieces, ignore_index=True)
    if quotes.date.duplicated().any():
        raise ValueError('Duplicate benchmark quotes')
    frame = quotes.set_index('date').reindex(sorted(days)).rename_axis('date').reset_index()
    frame = frame[frame.date.between(c['start'], c['end'])]
    valid = frame.dropna(subset=['close']).copy()
    previous = valid.shift(1)
    changes = valid.causal_factor.div(previous.causal_factor).sub(1).abs().gt(1e-12)
    actual = valid.loc[changes, 'date'].tolist()
    expected = sorted([r['ex_date'] for r in distributions] + [split['date']])
    if actual != expected:
        raise ValueError('Unexplained or missing corporate action')
    action_checks = []
    for r in distributions:
        row = valid.loc[valid.date.eq(r['ex_date'])].iloc[0]
        prior = previous.loc[row.name]
        implied = prior['close'] * (1 - prior.causal_factor / row.causal_factor)
        if abs(implied - r['cash_per_unit']) > .011:
            raise ValueError('Dividend units conflict with frozen raw reference adjustment')
        action_checks.append(dict(ex_date=r['ex_date'], official_cash_per_unit=r['cash_per_unit'], reference_implied_cash_per_unit=float(implied)))
    split_index = valid.index[valid.date.eq(split['date'])][0]
    if not csv12_product_matches(previous.loc[split_index, 'causal_factor'], split['ratio'], valid.loc[split_index, 'causal_factor']):
        raise ValueError('Split units conflict with frozen factor')
    frame.to_csv(ROOT / 'market.csv.gz', index=False, compression={'method': 'gzip', 'mtime': 0}, float_format='%.17g')
    atomic_json(OUT / 'source_ledger.json', dict(status='passed_for_realized_gross_accounting', sources=sources,
                distributions=distributions, split=split, action_checks=action_checks,
                market_sessions=len(frame), raw_quote_sessions=int(frame.close.notna().sum()),
                calendar_basis='Observed dates in exact frozen multi-security panel, not a newly acquired independent official calendar',
                stale_market_dates=frame.loc[frame.close.isna(), 'date'].tolist(),
                frozen_price_sha256=c['frozen_price_sha256'], extracted_market_sha256=sha256(ROOT / 'market.csv.gz'),
                archive_sha256=package['sha256'], roundtrip_verified=True, crc_manifest_verified=True,
                factor_precision='Frozen build_history.py writes %.12g; product checks use propagated half-step bounds for those rounded inputs. Official share ratio remains exactly 4.',
                historical_pit_verified=False, actual_broker_credits_verified=False, backup=transfer))


def ledger():
    c = policy()
    source = json.loads((OUT / 'source_ledger.json').read_text())
    if sha256(ROOT / 'market.csv.gz') != source['extracted_market_sha256'] or not source['roundtrip_verified']:
        raise ValueError('Accounting input drift')
    daily, claims, initial = physical_ledger(pd.read_csv(ROOT / 'market.csv.gz'), source['distributions'], source['split'], c['start'], c['end'], c['initial_physical_units'])
    daily.to_csv(OUT / 'daily.csv.gz', index=False, compression={'method': 'gzip', 'mtime': 0}, float_format='%.17g')
    atomic_json(OUT / 'claims.json', claims)
    last = daily.iloc[-1]
    atomic_json(OUT / 'summary.json', dict(status='gross_physical_accounting_only', initial_quote_cost=initial,
                calendar_days=len(daily), market_sessions=int(daily.market_session.sum()), stale_market_sessions=int(daily.stale_market_quote.sum()),
                ending_units=float(last.physical_units), settled_gross_cash=float(last.settled_cash), unpaid_gross_receivable=float(last.dividend_receivable),
                ending_gross_wealth=float(last.gross_wealth), gross_physical_change=float(last.gross_nav - 1),
                frozen_adjusted_quote_change=float(last.frozen_adjusted_quote_ratio - 1),
                difference_pp=float((last.gross_nav - last.frozen_adjusted_quote_ratio) * 100),
                input_sha256=sha256(ROOT / 'market.csv.gz'), daily_sha256=sha256(OUT / 'daily.csv.gz'),
                claims_sha256=sha256(OUT / 'claims.json'), protocol_sha256=sha256(POLICY), profit_edge_proven=False))


def audit():
    c = policy()
    source = json.loads((OUT / 'source_ledger.json').read_text())
    s = json.loads((OUT / 'summary.json').read_text())
    for path, key in [(ROOT / 'market.csv.gz', 'input_sha256'), (OUT / 'daily.csv.gz', 'daily_sha256'), (OUT / 'claims.json', 'claims_sha256')]:
        if sha256(path) != s[key]:
            raise ValueError('Accounting artifact differs')
    daily = pd.read_csv(OUT / 'daily.csv.gz')
    result = audit_ledger(pd.read_csv(ROOT / 'market.csv.gz'), source['distributions'], source['split'], c['start'], c['end'], c['initial_physical_units'], daily, json.loads((OUT / 'claims.json').read_text()))
    initial = float(daily.iloc[0].physical_units * pd.read_csv(ROOT / 'market.csv.gz').iloc[0].open)
    last = daily.iloc[-1]
    expected = dict(initial_quote_cost=initial, calendar_days=len(daily), market_sessions=int(daily.market_session.sum()), stale_market_sessions=int(daily.stale_market_quote.sum()),
                    ending_units=float(last.physical_units), settled_gross_cash=float(last.settled_cash), unpaid_gross_receivable=float(last.dividend_receivable),
                    ending_gross_wealth=float(last.gross_wealth), gross_physical_change=float(last.gross_nav-1), frozen_adjusted_quote_change=float(last.frozen_adjusted_quote_ratio-1),
                    difference_pp=float((last.gross_nav-last.frozen_adjusted_quote_ratio)*100))
    if any(abs(s[k] - v) > 1e-8 for k, v in expected.items()) or s['profit_edge_proven'] is not False or s['protocol_sha256'] != sha256(POLICY):
        raise ValueError('Summary differs from independently audited ledger')
    result['summary_sha256'] = sha256(OUT / 'summary.json')
    atomic_json(OUT / 'independent_audit.json', result)


def report():
    c = policy()
    source = json.loads((OUT / 'source_ledger.json').read_text())
    s = json.loads((OUT / 'summary.json').read_text())
    a = json.loads((OUT / 'independent_audit.json').read_text())
    if a['status'] != 'passed' or a['summary_sha256'] != sha256(OUT / 'summary.json'):
        raise ValueError('Independent audit required')
    claims = json.loads((OUT / 'claims.json').read_text())
    lines = ['# 0050跨年股數／應收／付款日現金對帳', '',
             '本輪補上衡量基準的會計缺口，沒有另選策略、調參或重寫舊結果。既有2025單年PhysicalBook元件重用，新增2023～2025跨年及全部日曆日對帳；六筆配息和一次分割皆由新封存的官方原文驗證，不把舊程式常數當成來源。', '',
             f'固定期間{c["start"]}～{c["end"]}；第一日以原始開盤報價假設取得1,000單位，初始金額{s["initial_quote_cost"]:,.2f}元；不再買賣、不把配息再投入、現金零息。共{s["calendar_days"]}個日曆日、{s["market_sessions"]}個市場日，其中{s["stale_market_sessions"]}日因分割停牌以末次報價估值。', '',
             '## 配息與股數', '', '| 除息日 | 發放日 | 每當時單位毛額 | 有權單位 | 毛額應收／後續現金 |', '|---|---|---:|---:|---:|']
    for r in claims:
        lines.append(f'| {r["ex_date"]} | {r["payment_date"]} | {r["cash_per_unit"]:.2f} | {r["entitled_units"]:,.0f} | {r["gross_claim"]:,.2f} |')
    lines += ['', '2025-06-18依官方4：1分割，1,000單位變4,000單位；先前已入現金與應收不乘4。除息日開盤買入不取得該次權利；付款即使在休市日也只在真正日曆付款日轉入現金，不提前給可用資金。', '',
              '## 期末對帳', '',
              f'- 股數：{s["ending_units"]:,.0f}；已發放毛額現金：{s["settled_gross_cash"]:,.2f}元；未發放應收：{s["unpaid_gross_receivable"]:,.2f}元。',
              f'- 原始收盤市值＋毛額現金＋應收：{s["ending_gross_wealth"]:,.2f}元，相對初始報價金額變化{s["gross_physical_change"]:.2%}。',
              f'- 同期間既有參考價調整報價變化{s["frozen_adjusted_quote_change"]:.2%}；兩種口徑差{s["difference_pp"]:+.3f}百分點。', '',
              '這個差額是不同現金持有／調整慣例的結果，不能歸因於選股能力，也不代表所有差額皆是可實現再投入收益。調整因子檢核只證明六次除息與一次分割的參考價算術一致；沒有證明實際再投入成交。舊研究的原始hash、協定和結果全部保留，沒有將新口徑偷偷代入。', '',
              f'獨立Decimal直接按持有單位、除息權利與累計發放金額重算{a["calendar_days"]}日及{a["claims"]}筆權益，金額最大誤差{a["max_money_error_twd"]:.3g}元、淨值比值最大誤差{a["max_nav_ratio_error"]:.3g}；另核對每日資產等式、付款日期及期末摘要。來源先封存、Windows備份取回，SHA／CRC／manifest通過。', '',
              '## 範圍與入口', '',
              '這是歷史已實現分配條件的毛額會計重建，不是券商對帳單，也沒有證明歷史首次公開或完整修訂版本。未扣交易費、滑價、個人稅務、補充保費或匯款費，沒有期末賣出；不可稱投資人實得淨報酬。停牌估值無法觀測真實當下價值。只有0050基準，股票策略的公司行動與可成交性仍未完成。', '',
              '市場日曆沿用凍結全市場面板的可觀測日期，未另取得獨立官方日曆。舊CSV以12位有效數字保存因子，乘積檢核使用該格式的捨入誤差上界；沒有修改官方股數比例或策略參數。', '',
              '官方配息來源：' + '、'.join(f'[{year}年](https://www.twse.com.tw/en/ETFortune-institute/dividendList?endDate={year}&startDate={year}&stkNo=0050)' for year in [2023,2024,2025]) + '；[分割原文](' + source['split']['source_url'] + ')。', '',
              '見[來源及公司行動核對](source_ledger.json)、[逐筆權益](claims.json)、[摘要](summary.json)、[獨立重算](independent_audit.json)。重播使用research_pipeline與固定source／replay plan；原始大型價格包沿用本地備份，新小型官方來源包另外備份，不提交Git。', '',
              '此成果可作後續研究的獨立衡量基準，尚不構成任何新策略值得投入的證據；不恢復七規則每日計畫、無訊號或訂單。']
    (OUT / 'report.md').write_text('\n'.join(lines) + '\n')
    atomic_json(OUT / 'next_tasks.json', dict(status='completed_gross_benchmark_accounting',
                old_protocols_changed=False, strategy_reruns_authorized_by_this_output=False, profit_edge_proven=False,
                manual_download_requests=[], daily_validation=False, seven_rule_daily_plan='stopped',
                remaining_limits=['Actual fills and investor net deductions absent', 'Stock portfolio corporate-action accounting not generalized', 'Original first-publication/version history not proven'],
                next_use='Use only through an explicitly frozen future protocol; never silently replace earlier benchmark inputs'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['package', 'replay', 'ledger', 'audit', 'report'])
    globals()[parser.parse_args().stage]()
