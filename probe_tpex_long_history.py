"""Bounded free-source availability probe; no annual coverage or ordinary-pool claim."""
import concurrent.futures,json,urllib.parse
from pathlib import Path
from tpex_source_pilot import fetch,validate_quotes
from tpex_flow_pilot import parse

def main():
 root=Path('deliverables/tpex_long_history_probe');raw=root/'raw';raw.mkdir(parents=True,exist_ok=True)
 tasks=[(date,kind) for date in ['2015-01-05','2018-01-02','2020-01-02','2022-01-03'] for kind in ['quotes','institutional']]
 def one(task):
  day,kind=task;endpoint='afterTrading/otc' if kind=='quotes' else 'insti/dailyTrade';args=dict(date=day.replace('-','/'),type='EW' if kind=='quotes' else 'Daily',response='json');url='https://www.tpex.org.tw/www/zh-tw/'+endpoint+'?'+urllib.parse.urlencode(args);path=raw/f'{kind}_{day}.json';result=dict(date=day,kind=kind)
  try:
   doc=fetch(url,path);result['download_ok']=True;result['source_sha256']=json.loads(path.with_suffix('.json.meta.json').read_text())['sha256'];result['fields']=[t.get('fields',[]) for t in doc.get('tables',[]) if t.get('data')]
   try:
    if kind=='quotes':result['validation']=validate_quotes(doc,day)
    else:result['validation']={'rows':len(parse(doc,day))}
    result['current_parser_passed']=True
   except Exception as e:result['current_parser_passed']=False;result['validation_error']=type(e).__name__+': '+str(e)
  except Exception as e:result['download_ok']=False;result['download_error']=type(e).__name__+': '+str(e)
  return result
 results=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  for start in range(0,len(tasks),2):
   for r in pool.map(one,tasks[start:start+2]):results.append(r);print({k:r.get(k) for k in ['date','kind','download_ok','current_parser_passed']},flush=True)
 report=dict(samples=results,limitation='Only four historical dates, not complete annual source coverage, historical ordinary-stock membership, or corporate-action replay. Raw snapshots are retained; never classify download/parse failure as a holiday.')
 (root/'availability.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 lines=['# 上櫃長歷史免費來源可用性試點','','| 日期 | 來源 | 下載成功 | 現有解析器通過 |','|---|---|---|---|']
 for r in results:lines.append(f"| {r['date']} | {r['kind']} | {r['download_ok']} | {r.get('current_parser_passed','未執行')} |")
 lines+=['','本次僅驗證四個歷史日期。全年交易日、原始普通股股票池、公司行動還原及缺失事件尚未建立，不能據此稱八年資料已完成。來源與原始回應雜湊見 availability.json。']
 (root/'report.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__':main()
