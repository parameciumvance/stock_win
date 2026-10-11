"""Independent TPEx monthly date audit; dates never filtered by index-price completeness."""
import concurrent.futures,datetime,json,pathlib
from acquire_tpex_month import fetch

def run(year=2023):
    root=pathlib.Path(f'deliverables/tpex_{year}');raw=root/'raw'
    def one(month):
        path=raw/f'tpex_index_{year}{month:02}.json'
        j=fetch(f'https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date={year}/{month:02}/01&response=json',path)
        if j.get('stat')!='ok' or not j.get('tables'):raise ValueError('TPEx calendar source unavailable')
        t=j['tables'][0]
        if t.get('date')!=f'{year-1911}/{month:02}' or '日期' not in t.get('fields',[]):raise ValueError('Wrong month or schema')
        dates=[datetime.date.fromisoformat(r[0].replace('/','-')).isoformat() for r in t['data']]
        if not dates or len(dates)!=len(set(dates)) or any(not d.startswith(f'{year}-{month:02}') for d in dates):raise ValueError('Calendar dates malformed')
        cp=raw/f'calendar_{year}{month:02}.json'
        comparison=[]
        if cp.exists():
            c=json.loads(cp.read_bytes())
            for row in c['data']:
                yy,mm,dd=map(int,row[0].split('/'));comparison.append(datetime.date(yy+1911,mm,dd).isoformat())
            if comparison!=dates:raise ValueError('TWSE/TPEx date difference needs review')
        summary=root/f'summary_{year}{month:02}.json';downloaded=[]
        if summary.exists():downloaded=[r['requested_date'] for r in json.loads(summary.read_text())['daily']]
        if downloaded and downloaded!=dates:raise ValueError('Quote-date coverage differs')
        result={'month':month,'dates':dates,'tpex_days':len(dates),'twse_comparison_verified':bool(comparison),'quote_month_complete':bool(downloaded)}
        print(month,len(dates),'quotes',bool(downloaded),flush=True)
        return result
    months=list(concurrent.futures.ThreadPoolExecutor(2).map(one,range(1,13)))
    (root/'calendar_audit.json').write_text(json.dumps({'year':year,'tpex_trading_days':sum(m['tpex_days'] for m in months),'date_source':'official TPEx monthly index records; no index-price filtering','months':months},indent=2))
if __name__=='__main__':run()
