"""Annual source readiness and unresolved membership/action evidence; no model training."""
import argparse,json
from pathlib import Path
import pandas as pd
from research_runtime import atomic_json,sha256

def main():
 p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);a=p.parse_args();root=Path(f'deliverables/tpex_{a.year}');flow=Path(f'deliverables/tpex_flow_{a.year}')
 quote_file=root/f'quotes_with_type_{a.year}.csv.gz';flow_file=flow/f'institutional_tpex_{a.year}.csv.gz'
 qv=json.loads((root/'annual_verification.json').read_text());fv=json.loads((flow/'acquisition.json').read_text());ev=json.loads((root/'event_coverage_summary.json').read_text());cal=json.loads((root/'calendar_audit.json').read_text());days=[d for m in cal['months'] for d in m['dates']]
 if sha256(quote_file)!=qv['output_sha256'] or sha256(flow_file)!=fv['normalized_sha256']:raise ValueError('Annual normalized hash mismatch')
 q=pd.read_csv(quote_file,dtype={'code':str});f=pd.read_csv(flow_file,dtype={'code':str})
 if len(q)!=qv['all_security_rows'] or len(f)!=fv['rows']:raise ValueError('Annual summary row count differs')
 if sorted(q.date.unique())!=days or sorted(f.date.unique())!=days:raise ValueError('Annual source/calendar dates differ')
 if q.duplicated(['date','code']).any() or f.duplicated(['date','code']).any():raise ValueError('Duplicate annual keys')
 joined=q[['date','code','primary_pool','confirmed_subset','type_evidence']].merge(f[['date','code']],on=['date','code'],how='outer',indicator=True,validate='one_to_one')
 primary=q[q.primary_pool];confirmed=q[q.confirmed_subset];candidate=q[q.type_evidence.eq('ordinary_stock_rule_candidate')];unknown=q[q.type_evidence.str.startswith('unresolved')]
 missing=joined[joined.primary_pool.eq(True)&joined._merge.eq('left_only')];unquoted=joined[joined._merge.eq('right_only')]
 for name,frame in [('unresolved_type_rows.csv',unknown[['date','code','historical_name','type_evidence']]),('candidate_type_rows.csv',candidate[['date','code','historical_name','type_evidence']]),('missing_institutional_primary_rows.csv',missing[['date','code','type_evidence']])]:
  temp=root/(name+'.pending');frame.to_csv(temp,index=False);temp.replace(root/name)
 report=dict(year=a.year,market_days=len(days),quote_rows=len(q),institutional_rows=len(f),unique_quote_securities=int(q.code.nunique()),primary_pool_rows=len(primary),confirmed_ordinary_rows=len(confirmed),rule_candidate_rows=len(candidate),unresolved_type_rows=len(unknown),unresolved_type_codes=sorted(unknown.code.unique()),rule_candidate_codes=sorted(candidate.code.unique()),primary_institutional_missing_rows=len(missing),institutional_rows_without_quote=len(unquoted),event_quote_bridge=ev,all_source_checks_passed=True,model_training_started=False,
  limitations=['Historical daily quote presence establishes observed membership only; full suspended-security master is pending.','Current ISIN evidence is retrospective classification, not original publication-time evidence. No current membership deletion is applied.',
   'Historical source snapshots were retrieved now and may contain later revisions; original publication snapshots are not established.','Missing institutional rows stay unknown, not zero; reports must precede signal day.','Event quote bridge is not verified reference-price formula, full split/merger/suspension coverage, adjusted price, or a cash ledger.',f'Prior-year quotes are not supplied for this standalone {a.year} bridge; missing preceding prices remain flagged.',f'{a.year} is a historical research year; earlier diagnostics have been seen, so this is not a new untouched holdout.'])
 atomic_json(root/'readiness.json',report)
 lines=[f'# TPEx {a.year} 全年來源與缺口驗收','','| 項目 | 結果 |','|---|---:|',f'| 官方交易日 | {len(days)} |',f'| 全證券行情列 | {len(q):,} |',f'| 法人日報列 | {len(f):,} |',f'| 已核實普通股列 | {len(confirmed):,} |',f'| 規則候選普通股列 | {len(candidate):,} |',f'| 未解證券分類列 | {len(unknown):,} |',f'| 主要探索池法人缺列（未知） | {len(missing):,} |',f"| 公司行動事件 | {ev['events']:,} |",'','全年來源日期／鍵／雜湊通過；分級股票池與缺列清單保留。來源包已分開保存取回，尚未建立本年度還原價或模型回測。','','公司行動對應狀態：'+json.dumps(ev['by_status'],ensure_ascii=False),'','限制：']
 lines.extend('- '+s for s in ['行情出現只能建立可觀察股票池；完整停牌證券主檔仍pending。','分類證據為回溯資料，不聲稱原始公告時點；保留候選與未解證券。','法人缺列保留未知，使用時至少落後一個交易日。','公司行動只完成前收盤對應；參考價公式、取整、全事件／停復牌及還原價仍pending。',f"本年度獨立驗收未接入{a.year-1}前期行情；實際缺前收盤事件{ev['by_status'].get('missing_prior_quote',0)}筆，缺口保留未知。",f'{a.year}不是未觸碰的新留出；本輪不調參、不訓練模型。'])
 (root/'readiness.md').write_text('\n'.join(lines)+'\n');print(json.dumps({k:report[k] for k in ['year','market_days','quote_rows','institutional_rows','primary_institutional_missing_rows','all_source_checks_passed']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
