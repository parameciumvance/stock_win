"""Conditional calendar comparison only; no account, quote, order or signal approval."""
from datetime import date,timedelta
import json,hashlib,zipfile
from pathlib import Path
from source_checkpoint import readback
from research_runtime import atomic_json,sha256
import frontier_cb_calendar_completion_sources as source

OPEN_LABELS={'國曆新年開始交易日','農曆春節前最後交易日','農曆春節後開始交易日'}
HOLIDAY_LABELS={'中華民國開國紀念日','農曆除夕及春節','和平紀念日','兒童節及民族掃墓節','勞動節','端午節','中秋節','孔子誕辰紀念日/ 教師節','國慶日','臺灣光復暨金門古寧頭大捷紀念日','行憲紀念日'}

def require(v,m):
    if not v:raise ValueError(m)

def parse_calendar(payload):
    require(payload.get('stat')=='ok' and payload.get('queryYear')==2026 and payload.get('date')=='20260101'
            and payload.get('title')=='115 年市場開休市日期' and payload.get('fields')==['日期','名稱','說明'],'Calendar identity/schema differs')
    rows=payload['data'];require(type(payload.get('total')) is int and payload['total']==len(rows)>0,'Calendar declared total mismatch')
    trade=set();settle=set();seen=set();classified=[]
    for row in rows:
        require(isinstance(row,list) and len(row)==3 and all(isinstance(v,str) for v in row),'Malformed calendar row')
        day=date.fromisoformat(row[0]);require(day.year==2026 and day not in seen,'Calendar duplicate/outside year');seen.add(day)
        label=row[1]
        if label in OPEN_LABELS:kind='explicit_trading_day'
        elif label=='市場無交易，僅辦理結算交割作業':kind='settlement_only';trade.add(day)
        elif label in HOLIDAY_LABELS:kind='holiday';trade.add(day);settle.add(day)
        else:raise ValueError('Unknown calendar status needs explicit review')
        classified.append(dict(source_row=row,kind=kind))
    return dict(year=2026,rows=classified,trade_closed=trade,settlement_closed=settle)


def is_open(day,calendar,kind='trade',extra_closed=frozenset()):
    require(day.year==calendar['year'] and kind in ('trade','settlement'),'Unknown calendar scope/kind')
    # Regular weekends are an explicit scenario convention; new emergency closures remain possible.
    closed=calendar['trade_closed'] if kind=='trade' else calendar['settlement_closed']
    return day.weekday()<5 and day not in closed and day not in extra_closed


def next_day(day,calendar,kind='trade',extra_closed=frozenset(),inclusive=False):
    current=day if inclusive else day+timedelta(days=1)
    while not is_open(current,calendar,kind,extra_closed):current+=timedelta(days=1)
    return current


def lag_day(entry,lag,calendar,kind='settlement',extra_closed=frozenset()):
    require(type(lag) is int and lag>=0 and is_open(entry,calendar,'trade',extra_closed),'Lag requires a trading entry and nonnegative integer')
    result=entry
    for _ in range(lag):result=next_day(result,calendar,kind,extra_closed)
    return result


def scenarios(calendar,observation_day,extra_closed,notice_cases):
    require({c['bond_code'] for c in notice_cases}=={'99587','68351'},'Retain both available notices')
    entry=next_day(observation_day,calendar,'trade',extra_closed);settled=lag_day(entry,2,calendar,'settlement',extra_closed)
    cases=[]
    for c in notice_cases:
        end=date.fromisoformat(c['broker_end'])
        cases.append(dict(bond_code=c['bond_code'],notice_broker_end=c['broker_end'],notice_expected_payment=c['expected_payment_date'],
            next_scheduled_observation_day=entry.isoformat(),explicit_assumed_settlement_lag=2,assumed_T2_settlement_day=settled.isoformat(),
            T2_date_comparison_only_reaches_broker_end=settled<=end,
            actual_settlement_and_available_balance_verified=False,broker_intraday_acceptance_verified=False,
            alternative_earlier_negotiated_delivery_verified=False,net_proceeds_verified=False,signal_valid=False))
    return dict(status='conditional_calendar_scenarios_only',observation_day=observation_day.isoformat(),next_scheduled_market_observation=entry.isoformat(),
        assumptions=['Regular Saturday/Sunday closures','Additional2026-10-23closurefromtwo providers','No later unobserved emergency closure','T+2 is an explicit illustrative scenario, not verification of a broker/venue/account arrangement'],
        original_controls=['99587','68351','68741'],cases=cases,unresolved_control='68741',
        earliest_verified_executable_entry=None,valid_prospective_signal_date=None,source_gate_passed=False,cash_claim_source_gate_passed=False,profit_edge_proven=False,orders_authorized=False)


def replay():
    source.plan();p,_=readback(source.OUT,'calendar')
    with zipfile.ZipFile(p['retrieved']) as z:
        cfg=json.loads(z.read('requests.json'));meta=json.loads(z.read('raw/twse_calendar_2026.json.meta.json'));raw=z.read('raw/twse_calendar_2026.json')
        require(meta['request']==cfg['requests'][0] and meta['http_status']==200 and meta['exit_code']==0
                and meta['sha256']==hashlib.sha256(raw).hexdigest() and meta['curl']['url_effective']==cfg['requests'][0]['url'],'Calendar transport/request mismatch')
        cal=parse_calendar(json.loads(raw))
    old,_=readback('deliverables/frontier_cb_operations_20261023','pages');evidence=[]
    with zipfile.ZipFile(old['retrieved']) as z:
        for name,anchor in [('kgi_service_closures.html','115年10月23日（星期五）台北股、期市休市一天'),('landbank_service_closures.html','證券、期貨交易市場115年10月23日(星期五)全日休市')]:
            from cash_merger_document_lookup import inventory_html
            body=z.read('raw/'+name);full,_=inventory_html(body)
            require(''.join(anchor.split()) in ''.join(full['page_text'].split()),'Provider closure exact anchor absent')
            evidence.append(dict(member='raw/'+name,body_sha256=hashlib.sha256(body).hexdigest(),anchor=anchor,source_kind='provider_own_service_announcement'))
    notice=json.loads(Path('deliverables/frontier_cb_material_rows_20261023/put_notice_annotation.json').read_bytes())
    result=scenarios(cal,date(2026,10,23),{date(2026,10,23)},notice['cases'])
    result.update(calendar_archive_sha256=p['sha256'],calendar_body_sha256=meta['sha256'],calendar_observed_at=meta['observed_at'],
        annual_rows=cal['rows'],annual_declared_total=27,closure_evidence=evidence,closure_archive_sha256=old['sha256'],notice_annotation_sha256=sha256('deliverables/frontier_cb_material_rows_20261023/put_notice_annotation.json'))
    atomic_json(source.OUT/'calendar_and_entry_scenarios.json',result)
    return result

if __name__=='__main__':
    r=replay();print(json.dumps(dict(next_scheduled_observation=r['next_scheduled_market_observation'],valid_signal_date=None,source_gate_passed=False)))
