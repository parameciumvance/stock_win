"""Audit TPEx event bridge; adjustment factor is a quote proxy, not total shareholder return."""
import concurrent.futures, datetime, hashlib, json, pathlib, re, urllib.request
from tpex_source_pilot import fetch, validate_quotes

ROOT=pathlib.Path('deliverables/tpex_pilot')

def number(s):
    return float(str(s).replace(',', '').strip())

def detail(html, label):
    pairs=re.findall(r'<th>(.*?)</th>\s*<td>(.*?)</td>', html, re.S)
    for k,v in pairs:
        if label in re.sub('<[^>]+>','',k):
            return re.sub('<[^>]+>','',v).replace('&nbsp','').strip().rstrip(';')
    raise ValueError('Missing detail: '+label)

def lookup(doc, code):
    table=doc['tables'][0]
    matches=[r for r in table['data'] if r[0]==code]
    if len(matches)!=1: raise ValueError('Missing or duplicate quote '+code)
    return dict(zip([x.strip() for x in table['fields']],matches[0]))

def run():
    p=ROOT/'event_bridge';p.mkdir(exist_ok=True)
    dates=['2023-01-04','2023-01-05','2023-02-01','2023-02-02','2023-02-13','2024-08-28','2024-08-29','2024-09-09']
    def get(date):
        dest=p/('quotes_'+date.replace('-','')+'.json')
        doc=json.loads(dest.read_bytes()) if dest.exists() else fetch('https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date='+date.replace('-','/')+'&type=EW&response=json',dest)
        validate_quotes(doc,date)
        return date,doc
    docs=dict(concurrent.futures.ThreadPoolExecutor(3).map(get, dates))
    ex=json.loads((ROOT/'excal_history.json').read_bytes())['tables'][0]
    reduction=json.loads((ROOT/'reduction_history.json').read_bytes())['tables'][0]
    change=json.loads((ROOT/'change_history_2024.json').read_bytes())['tables'][0]
    output=[]
    for code,typ,prev,stopped,resumed,table in [('6488','cash_dividend','2023-01-04',None,'2023-01-05',ex),('3085','capital_reduction','2023-02-01','2023-02-02','2023-02-13',reduction),('6763','face_value_change','2024-08-28','2024-08-29','2024-09-09',change)]:
        rows=[r for r in table['data'] if r[1]==code and r[0] in {'112/01/05','1120213','1130909'}]
        if len(rows)!=1:raise ValueError('Ambiguous event')
        event=rows[0];last=number(lookup(docs[prev],code)['收盤']);quote=lookup(docs[resumed],code)
        if abs(last-number(event[3]))>1e-8:raise ValueError('Last close mismatch')
        ref=number(event[4]);ratio=1.0;cash=0.0
        if typ=='cash_dividend':
            cash=number(event[13]);assert abs(last-cash-ref)<1e-8
        elif typ=='capital_reduction':
            ratio=number(re.match(r'[0-9.]+',detail(event[-1],'每壹仟股換發新股票'))[0])/1000
            cash=number(re.match(r'[0-9.]+',detail(event[-1],'每股退還股款'))[0]);assert abs((last-cash)/ratio-ref)<1e-8
        else:
            ratio=number(detail(event[-1],'變更股票面額換股率'));assert abs(last/ratio-ref)<1e-8
        suspended=None
        if stopped:
            rows_on_stop=[r for r in docs[stopped]['tables'][0]['data'] if r[0]==code]
            if not rows_on_stop:
                suspended=True
            else:
                stopped_quote=lookup(docs[stopped],code)
                try: number(stopped_quote['收盤']);suspended=False
                except ValueError:suspended=True
            if not suspended:raise ValueError('Expected suspension boundary has price')
        output.append({'code':code,'type':typ,'last_trade_date':prev,'resume_or_ex_date':resumed,'last_close':last,'reference_price':ref,'share_ratio':ratio,'cash_per_old_share':cash,'quote_proxy_multiplier_from_event':last/ref,'resumed_close':number(quote['收盤']),'suspension_observed':suspended,'status':'reference_identity_and_quote_bridge_pass','limitation':'not actual cash payment ledger; selected event pilot only'})
    (p/'validation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(json.dumps(output,ensure_ascii=False))

if __name__=='__main__':run()
