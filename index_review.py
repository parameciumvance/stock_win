"""Bounded index-review source replay and descriptive quote diagnostics.

Historical announcement claims on current pages are not historical PIT proof.
"""
import argparse
from decimal import Decimal
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import statistics
import zipfile

import numpy as np
import pandas as pd

from research_reassessment import verified_bundle
from research_runtime import atomic_json, exclusive_lock, sha256, utcnow
from source_checkpoint import package_sources, readback

ROOT = Path('inputs/index_review_20261018')
OUT = Path('deliverables/index_review_20261018')
POLICY = Path('configs/index_review_protocol_20261018.json')
SOURCES = Path('configs/index_review_sources_20261018.json')


def policy():
    c = json.loads(POLICY.read_text())
    if sha256(POLICY) != json.loads((OUT / 'protocol_freeze.json').read_text())['protocol_sha256']:
        raise ValueError('Frozen event protocol drift')
    return c


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('head', 'script', 'style'):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ('head', 'script', 'style'):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def parse_notice(body, quarter):
    parser = Text()
    parser.feed(body.decode('utf-8', errors='strict'))
    text = re.sub(r'\s+', '', ''.join(parser.parts))
    title = '臺灣證券交易所與富時國際有限公司合編之臺灣指數系列及臺灣高股息指數成分股定期審核結果'
    if text.count(title) != 1:
        raise ValueError('Wrong or ambiguous review title')
    text = text[text.index(title):]
    stamps = re.findall(r'(20\d{2}/\d{2}/\d{2})(\d{2}:\d{2})', text)
    if len(stamps) != 1:
        raise ValueError('Missing/ambiguous displayed timestamp')
    date, time = stamps[0]
    published = pd.Timestamp(date + ' ' + time)
    if f'{published.year}Q{published.quarter}' != quarter:
        raise ValueError('Review quarter differs')
    dates = re.findall(r'將自(20\d{2})年(\d{1,2})月(\d{1,2})日.*?交易結束後生效.*?亦即自(20\d{2})年(\d{1,2})月(\d{1,2})日.*?起生效', text)
    if len(dates) != 1:
        raise ValueError('Missing/ambiguous implementation dates')
    nums = list(map(int, dates[0]))
    close, effective = pd.Timestamp(*nums[:3]), pd.Timestamp(*nums[3:])
    if not published.normalize() < close < effective or effective.year != published.year:
        raise ValueError('Invalid publication/implementation ordering')
    sections = re.findall(r'一、臺灣50指數(.*?)二、臺灣中型100指數', text)
    if len(sections) != 1:
        raise ValueError('Missing/ambiguous Taiwan 50 section')
    section = sections[0]
    changes = []
    for action, label, following in [('add', '納入', '刪除'), ('delete', '刪除', None)]:
        stop = r'\(二\)' if following else r'\(三\)'
        pattern = r'成分股' + label + r'[:：](.*?)' + stop
        matched = re.findall(pattern, section)
        if len(matched) != 1:
            raise ValueError('Missing/ambiguous change list')
        raw = matched[0].rstrip('。')
        if raw == '無':
            pairs = []
        else:
            pairs = re.findall(r'([^、。()]+)\((\d{4})\)', raw)
            residue = re.sub(r'[^、。()]+\(\d{4}\)', '', raw).replace('、', '').replace('。', '')
            if not pairs or residue:
                raise ValueError('Unparsed change list residue')
        changes.extend(dict(action=action, name=name, symbol=symbol) for name, symbol in pairs)
    additions = [r for r in changes if r['action'] == 'add']
    deletions = [r for r in changes if r['action'] == 'delete']
    if len(additions) != len(deletions) or len({r['symbol'] for r in changes}) != len(changes):
        raise ValueError('Unbalanced/duplicate changes need review')
    return dict(quarter=quarter, displayed_publication=str(published),
                publication_timezone='not explicitly established by page; no conversion claimed',
                implementation_close=str(close.date()), effective_from=str(effective.date()),
                changes=changes, historical_pit_verified=False, revision_history_verified=False)


def package():
    policy()
    cfg = json.loads(SOURCES.read_text())
    result = json.loads((ROOT / 'raw/results.json').read_text())
    if result['config_sha256'] != sha256(SOURCES) or result['workers'] != 2 or [r['request'] for r in result['requests']] != cfg['requests']:
        raise ValueError('Acquisition request/configuration drift')
    entries = {'protocol.json': POLICY, 'request_config.json': SOURCES}
    for row in result['requests']:
        dest = ROOT / 'raw' / row['request']['filename']
        if json.loads(dest.with_name(dest.name + '.meta.json').read_text()) != row:
            raise ValueError('Response metadata differs')
        if row.get('sha256') and sha256(dest) != row['sha256']:
            raise ValueError('Raw source hash differs')
    for file in (ROOT / 'raw').iterdir():
        if file.is_file():
            entries['raw/' + file.name] = file
    with exclusive_lock(ROOT / 'acquisition.lock'):
        package_sources(ROOT, OUT, 'sources', entries)


def replay():
    c = policy()
    archive, transfer = readback(OUT, 'sources')
    records, gaps = [], []
    with zipfile.ZipFile(archive['retrieved']) as z:
        if hashlib.sha256(z.read('protocol.json')).hexdigest() != sha256(POLICY) or hashlib.sha256(z.read('request_config.json')).hexdigest() != sha256(SOURCES):
            raise ValueError('Archived protocol/request list differs')
        requests = json.loads(z.read('raw/results.json'))['requests']
        for review in c['reviews']:
            filename = review['quarter'] + '.html'
            matches = [r for r in requests if r['request'] == dict(filename=filename, url=review['url'])]
            if len(matches) != 1:
                raise ValueError('Missing/duplicate request record')
            record = matches[0]
            try:
                if record.get('http_status') != 200 or record.get('exit_code') != 0:
                    raise ValueError('Source transport failed: ' + str(record.get('http_status')))
                body = z.read('raw/' + filename)
                if hashlib.sha256(body).hexdigest() != record['sha256']:
                    raise ValueError('Archived response drift')
                row = parse_notice(body, review['quarter'])
                row.update(source_url=review['url'], source_sha256=record['sha256'], retrieved_at=record['observed_at'])
                records.append(row)
            except (ValueError, UnicodeError) as error:
                gaps.append(dict(quarter=review['quarter'], url=review['url'], reason=str(error)))
    atomic_json(OUT / 'source_ledger.json', dict(records=records, gaps=gaps,
                current_vintage_source_gate_passed=len(records) == 4 and not gaps,
                historical_pit_gate_passed=False, first_publication_proven=False,
                original_versions_proven=False, archive_sha256=archive['sha256'],
                backup_path=transfer['backup_path'], roundtrip_verified=True, crc_manifest_verified=True,
                actual_transport=[dict(quarter=r['request']['filename'][:6], status=r.get('http_status'), exit_code=r.get('exit_code'), stderr=r.get('stderr')) for r in requests]))


def event_endpoints(calendar, effective, horizon):
    clock = pd.DatetimeIndex(calendar)
    if clock.has_duplicates or not clock.is_monotonic_increasing or horizon < 1:
        raise ValueError('Invalid market clock/horizon')
    first = clock.searchsorted(pd.Timestamp(effective)) + 1  # one additional market-session delay
    last = first + horizon - 1
    if first >= len(clock) or last >= len(clock):
        raise ValueError('Insufficient forward market sessions')
    return clock[first], clock[last]


def quote_return(entry, exit_, cost):
    if not all(np.isfinite(x) for x in (entry, exit_, cost)) or min(entry, exit_) <= 0 or not 0 <= cost < 1:
        raise ValueError('Invalid quote/cost')
    return float(exit_ / entry * (1 - cost) / (1 + cost) - 1)


def diagnose():
    c = policy()
    ledger = json.loads((OUT / 'source_ledger.json').read_text())
    if not ledger['current_vintage_source_gate_passed']:
        atomic_json(OUT / 'diagnostic.json', dict(status='stopped_source_gap', source_gaps=ledger['gaps'], rows=[], continuation_gate_passed=False, historical_pit_gate_passed=False))
        return
    manifest = verified_bundle(c['price_archive'], c['price_archive_sha256'])
    if manifest[c['price_member']] != c['price_sha256']:
        raise ValueError('Frozen price hash differs')
    selected = {'0050'} | {s['symbol'] for r in ledger['records'] for s in r['changes']}
    days, pieces = set(), []
    with zipfile.ZipFile(c['price_archive']) as z, z.open(c['price_member']) as stream:
        for chunk in pd.read_csv(stream, compression='gzip', dtype={'symbol': str}, chunksize=200000):
            days.update(chunk.date)
            pieces.append(chunk[chunk.symbol.isin(selected)][['date', 'symbol', 'adj_open', 'adj_close']])
    prices = pd.concat(pieces, ignore_index=True)
    if prices.duplicated(['date', 'symbol']).any():
        raise ValueError('Duplicate frozen quote')
    prices['date'] = pd.to_datetime(prices.date)
    clock = pd.DatetimeIndex(sorted(days))
    indexed = prices.set_index(['date', 'symbol'])
    rows = []
    for review in ledger['records']:
        start, end = event_endpoints(clock, review['effective_from'], c['horizon_market_sessions'])
        for change in review['changes']:
            row = dict(quarter=review['quarter'], **change, entry_date=str(start.date()), exit_date=str(end.date()),
                       implementation_close=review['implementation_close'], source_sha256=review['source_sha256'],
                       historical_pit_verified=False, status='ok')
            try:
                entry, exit_ = indexed.loc[(start, change['symbol']), 'adj_open'], indexed.loc[(end, change['symbol']), 'adj_close']
                bm_entry, bm_exit = indexed.loc[(start, '0050'), 'adj_open'], indexed.loc[(end, '0050'), 'adj_close']
                quote_return(entry, exit_, 0)
                quote_return(bm_entry, bm_exit, 0)
                row.update(entry_proxy=float(entry), exit_proxy=float(exit_), benchmark_entry_proxy=float(bm_entry), benchmark_exit_proxy=float(bm_exit))
                row['scenarios'] = [dict(one_way_cost=cost, net_quote_change=quote_return(entry, exit_, cost),
                                         benchmark_net_quote_change=quote_return(bm_entry, bm_exit, cost),
                                         relative_quote_change=quote_return(entry, exit_, cost) - quote_return(bm_entry, bm_exit, cost))
                                    for cost in c['one_way_hypothetical_costs']]
            except (KeyError, ValueError) as error:
                row.update(status='endpoint_gap', reason=str(error), scenarios=[])
            rows.append(row)
    complete = all(r['status'] == 'ok' for r in rows)
    primary = [dict(quarter=r['quarter'], value=s['relative_quote_change']) for r in rows if r['action'] == 'delete'
               for s in r['scenarios'] if s['one_way_cost'] == c['primary_one_way_cost']]
    quarters = [r['quarter'] for r in c['reviews']]
    means = {q: statistics.mean(r['value'] for r in primary if r['quarter'] == q) for q in quarters if any(r['quarter'] == q for r in primary)}
    median = statistics.median(r['value'] for r in primary) if primary else None
    passed = complete and len(means) == 4 and sum(v > 0 for v in means.values()) >= 3 and median is not None and median > 0
    atomic_json(OUT / 'diagnostic.json', dict(status='exploratory_quote_changes_only', protocol_sha256=sha256(POLICY),
                rows=rows, endpoints_complete=complete, primary_deletion_quarter_means=means, primary_deletion_median=median,
                continuation_gate_passed=passed, historical_pit_gate_passed=False,
                decision='separate_independent_event_proposal_only' if passed else 'close_fixed_pilot_no_tuning',
                price_archive_sha256=c['price_archive_sha256'], price_member_sha256=c['price_sha256'],
                limitations=['Current pages do not establish original historical versions or first public time',
                            'Only four review clusters; correlated names not independent trials',
                            'Market-adjusted comparisons do not control industry, size, momentum or concurrent news',
                            'Forward-reference adjusted quotes are not cash-account total returns or executable fills',
                            'Matched hypothetical costs cancel in relative comparisons up to common scale; not investor-specific edge',
                            'No annualization or portfolio NAV; no missing-event replacement']))


def audit_rows(s, ledger, c, indexed, clock):
    expected = {(r['quarter'], item['action'], item['symbol']) for r in ledger['records'] for item in r['changes']}
    actual = [(r['quarter'], r['action'], r['symbol']) for r in s['rows']]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError('Event cohort differs')
    checked, worst = 0, 0.
    for row in s['rows']:
        review = next(r for r in ledger['records'] if r['quarter'] == row['quarter'])
        # Independent endpoint selection with a Python list, no event_endpoints call.
        eligible = [d for d in clock if d.strftime('%Y-%m-%d') >= review['effective_from']]
        start, end = eligible[1], eligible[c['horizon_market_sessions']]
        if row['entry_date'] != str(start.date()) or row['exit_date'] != str(end.date()) or row['source_sha256'] != review['source_sha256']:
            raise ValueError('Independent endpoint/source identity differs')
        if row['status'] != 'ok':
            if row['status'] != 'endpoint_gap' or row['scenarios']:
                raise ValueError('Invalid retained gap record')
            # A gap may not hide a perfectly valid quote endpoint.
            try:
                values = [indexed.loc[(day, sym), field] for day, sym, field in
                          [(start, row['symbol'], 'adj_open'), (end, row['symbol'], 'adj_close'),
                           (start, '0050', 'adj_open'), (end, '0050', 'adj_close')]]
            except KeyError:
                values = [np.nan]
            if all(np.isfinite(v) and v > 0 for v in values):
                raise ValueError('False endpoint gap')
            continue
        if row['entry_date'] <= row['implementation_close'] or row['exit_date'] < row['entry_date']:
            raise ValueError('Invalid delayed endpoints')
        if [v['one_way_cost'] for v in row['scenarios']] != c['one_way_hypothetical_costs']:
            raise ValueError('Scenario list differs')
        for key, day, symbol, field in [('entry_proxy', start, row['symbol'], 'adj_open'),
                                       ('exit_proxy', end, row['symbol'], 'adj_close'),
                                       ('benchmark_entry_proxy', start, '0050', 'adj_open'),
                                       ('benchmark_exit_proxy', end, '0050', 'adj_close')]:
            value = indexed.loc[(day, symbol), field]
            if not np.isfinite(value) or value <= 0 or row[key] != float(value):
                raise ValueError('Frozen quote provenance differs')
        D = lambda key: Decimal(str(row[key]))
        for scenario in row['scenarios']:
            cost = Decimal(str(scenario['one_way_cost']))
            stock = D('exit_proxy') / D('entry_proxy') * (1 - cost) / (1 + cost) - 1
            bench = D('benchmark_exit_proxy') / D('benchmark_entry_proxy') * (1 - cost) / (1 + cost) - 1
            for key, value in [('net_quote_change', stock), ('benchmark_net_quote_change', bench), ('relative_quote_change', stock - bench)]:
                error = abs(float(value) - scenario[key])
                if not np.isfinite(error) or error > 1e-12:
                    raise ValueError('Independent Decimal return differs')
                worst = max(worst, error)
            checked += 1
    if s['historical_pit_gate_passed'] or any(r['historical_pit_verified'] for r in s['rows']):
        raise ValueError('Unproven PIT promotion')
    primary = {q['quarter']: [] for q in c['reviews']}
    for row in s['rows']:
        if row['action'] == 'delete' and row['status'] == 'ok':
            primary[row['quarter']].append(next(x['relative_quote_change'] for x in row['scenarios'] if x['one_way_cost'] == c['primary_one_way_cost']))
    means = {q: float(sum(map(lambda v: Decimal(str(v)), values)) / len(values)) for q, values in primary.items() if values}
    pooled = [v for values in primary.values() for v in values]
    median = statistics.median(pooled) if pooled else None
    if s['primary_deletion_quarter_means'] != means or s['primary_deletion_median'] != median:
        raise ValueError('Independent aggregate differs')
    complete = all(r['status'] == 'ok' for r in s['rows'])
    passed = complete and len(means) == 4 and sum(v > 0 for v in means.values()) >= 3 and median is not None and median > 0
    if s['endpoints_complete'] != complete or s['continuation_gate_passed'] != passed or s['decision'] != ('separate_independent_event_proposal_only' if passed else 'close_fixed_pilot_no_tuning'):
        raise ValueError('Independent continuation gate differs')
    return dict(status='passed', events=len(actual), scenarios=checked,
                max_absolute_error=worst, method='Independent Decimal quote-change arithmetic and full-cohort identity',
                quote_provenance_verified=True, market_calendar_endpoints_verified=True, decision_gate_verified=True)


def audit():
    c = policy()
    ledger = json.loads((OUT / 'source_ledger.json').read_text())
    s = json.loads((OUT / 'diagnostic.json').read_text())
    if not ledger['current_vintage_source_gate_passed']:
        atomic_json(OUT / 'independent_audit.json', dict(status='not_scored_source_gap', rows=0, diagnostic_sha256=sha256(OUT / 'diagnostic.json')))
        return
    verified_bundle(c['price_archive'], c['price_archive_sha256'])
    # Read frozen bytes again, rather than auditing against saved diagnostic prices.
    selected = {r['symbol'] for r in s['rows']} | {'0050'}
    days, pieces = set(), []
    with zipfile.ZipFile(c['price_archive']) as z, z.open(c['price_member']) as stream:
        for chunk in pd.read_csv(stream, compression='gzip', dtype={'symbol': str}, chunksize=200000):
            days.update(chunk.date)
            pieces.append(chunk[chunk.symbol.isin(selected)][['date', 'symbol', 'adj_open', 'adj_close']])
    prices = pd.concat(pieces, ignore_index=True)
    prices['date'] = pd.to_datetime(prices.date)
    result = audit_rows(s, ledger, c, prices.set_index(['date', 'symbol']), pd.DatetimeIndex(sorted(days)))
    result['diagnostic_sha256'] = sha256(OUT / 'diagnostic.json')
    atomic_json(OUT / 'independent_audit.json', result)


def report():
    c = policy()
    ledger = json.loads((OUT / 'source_ledger.json').read_text())
    s = json.loads((OUT / 'diagnostic.json').read_text())
    a = json.loads((OUT / 'independent_audit.json').read_text())
    if a['diagnostic_sha256'] != sha256(OUT / 'diagnostic.json'):
        raise ValueError('Diagnostic drift after audit')
    lines = ['# 臺灣50定期審核：固定一年事件試點', '',
             '研究假說：刪除股可能受到指數追蹤資金的賣壓，生效後可能反轉。這是可反駁的機制假說，沒有宣稱已識別實際ETF交易或因果效應。只取2024全年四次定期審核，納入與刪除全部保留，不挑漲跌好的股票。', '',
             '協定先於事件價格診斷凍結；未修改七規則、營運試點或風險控制協定。來源透過兩個worker自動取得，原始HTML、HTTP標頭及錯誤資料皆封存，Windows備份取回後驗證SHA、CRC、manifest才進入價格診斷。', '',
             '## 來源與時間', '', '| 季度 | 頁面標示發布時間（時區未明示） | 調整收盤／生效起日 | 納入 | 刪除 |', '|---|---|---|---|---|']
    for r in ledger['records']:
        names = {side: '、'.join(x['name'] + '(' + x['symbol'] + ')' for x in r['changes'] if x['action'] == side) or '無' for side in ('add', 'delete')}
        lines.append(f'| [{r["quarter"]}]({r["source_url"]}) | {r["displayed_publication"]} | {r["implementation_close"]}／{r["effective_from"]} | {names["add"]} | {names["delete"]} |')
    for gap in ledger['gaps']:
        lines.append(f'- 缺口：{gap["quarter"]}：{gap["reason"]}')
    lines += ['', '**目前頁面擷取／封存驗收與歷史PIT是不同關卡。** 官網標示歷史日期及名單仍不能證明原始版本、修訂完整性或首次公開時刻；本輪historical_pit_gate_passed始終為False，不產生有效歷史或前瞻訊號。', '']
    if s['rows']:
        lines += ['## 固定診斷', '',
                  '生效起日之後再多等一個市場日，以該日開盤至包含進入日的第20市場日收盤，計算調整報價變化。比對同起迄0050，兩邊使用相同假設成本。單邊0.25%／0.5%是固定情境，不宣稱真實費率；日曆不依個股有無報價壓縮，端點缺失列保留，不替換事件。', '',
                  '| 季度 | 類別 | 股票 | 固定起迄 | 代理變化扣假設成本 | 相對0050 |', '|---|---|---|---|---:|---:|']
        for r in s['rows']:
            primary = next((v for v in r['scenarios'] if v['one_way_cost'] == c['primary_one_way_cost']), None)
            value = f'{primary["net_quote_change"]:.2%}' if primary else '缺口'
            relative = f'{primary["relative_quote_change"]:+.2%}' if primary else '缺口'
            lines.append(f'| {r["quarter"]} | {r["action"]} | {r["symbol"]} | {r["entry_date"]}～{r["exit_date"]} | {value} | {relative} |')
        lines += ['', '表為單邊0.5%主情境；另一情境與所有來源SHA見[diagnostic.json](diagnostic.json)。同成本相對比較中的成本只形成共同比例縮放，不能據此證明策略對成本穩健。沒有組合淨值、年化績效、空頭或實際成交假設。', '',
                  '事前關卡要求刪除組在四季中至少三季平均相對變化為正，且全體中位數為正；即使通過，也只容許另立獨立事件提案，四個季度群集不足以證明獲利能力。', '',
                  '**' + ('通過有限探索關卡，歷史PIT仍未通過，不能升格為可交易策略。' if s['continuation_gate_passed'] else '未通過事前探索關卡，本次固定假說收束，不換持有天數、不反向挑納入股、不擴大下載或每日驗證。') + '**', '']
    elif ledger['current_vintage_source_gate_passed']:
        lines += ['完整四季沒有成分股異動，不虛構事件或進入價格比較。', '']
    else:
        lines += ['來源關卡未通過，未計算事件價格，停止此輪。沒有要求使用者補下載或以第三方名單替換原始來源。', '']
    lines += ['## 限制與交付', '',
              '2024價格已在舊研究看過，這是新的事件標籤探索，不能稱未碰過的留出樣本。比較未控制產業、規模、動能或同期消息；調整報價不是股東配息現金帳或可成交價。即使有正數，也不能推論指數造成超額報酬。', '',
              f'來源封存SHA：`{ledger["archive_sha256"]}`。逐事件來源、時間、修訂限制及實際HTTP狀態見[source_ledger.json](source_ledger.json)，獨立核對見[independent_audit.json](independent_audit.json)。大型原始檔留在本地持久化目錄與Windows備份，不提交Git。', '',
              '無有效前瞻訊號、訂單、已驗證獲利能力或每日人工任務。七規則計畫維持停止。']
    (OUT / 'report.md').write_text('\n'.join(lines) + '\n')
    atomic_json(OUT / 'next_tasks.json', dict(status=s.get('decision', 'stopped_source_gap'),
                historical_pit_passed=False, fitted_models=0, parameter_searches=0, manual_download_requests=[],
                daily_validation=False, live_signals=False, seven_rule_daily_plan='stopped',
                next_decision='Require separately frozen independent-event evidence before expanding; do not tune this pilot' if s['continuation_gate_passed'] else 'Close fixed mechanism pilot; no retuning or reversal to a winning subgroup'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['package', 'replay', 'diagnose', 'audit', 'report'])
    globals()[parser.parse_args().stage]()
