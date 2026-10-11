"""Replay four saved official daily samples; no annual coverage claim."""
import hashlib,json
from pathlib import Path
from research_runtime import atomic_json,sha256
from tpex_flow_pilot import parse,source_table,LEGACY_FIELDS
from tpex_source_pilot import validate_quotes

def main():
 root=Path('deliverables/tpex_long_history_probe');prior=json.loads((root/'availability.json').read_text());records=[]
 for sample in prior['samples']:
  if sample['kind']!='institutional':continue
  date=sample['date'];p=root/'raw'/f'institutional_{date}.json';meta=json.loads(p.with_suffix('.json.meta.json').read_text())
  digest=sha256(p)
  if digest!=meta['sha256'] or digest!=sample['source_sha256']:raise ValueError('Saved source hash mismatch')
  doc=json.loads(p.read_text());table=source_table(doc,date);frame=parse(doc,date);legacy=table['fields']==LEGACY_FIELDS
  # Check normalized values against positional source columns independently of parser branches.
  positions=[4,7,8,15] if legacy else [10,13,22,23]
  expected=[[int(row[i].replace(',','')) for i in positions] for row in table['data']]
  if frame[['foreign_net','trust_net','dealer_net','total_net']].values.tolist()!=expected:raise ValueError('Normalized source replay mismatch')
  quotes=root/'raw'/f'quotes_{date}.json';quote_meta=json.loads(quotes.with_suffix('.json.meta.json').read_text())
  if sha256(quotes)!=quote_meta['sha256']:raise ValueError('Saved quotes hash mismatch')
  qdoc=json.loads(quotes.read_text());qvalidation=validate_quotes(qdoc,date)
  qt=qdoc['tables'][0];fields=[str(x).replace('<br>','').strip() for x in qt['fields']];codes={r[fields.index('代號')] for r in qt['data']};flow_codes=set(frame.code)
  missing=sorted(codes-flow_codes);extra=sorted(flow_codes-codes)
  target=root/f'institutional_normalized_{date}.csv';tmp=target.with_suffix('.pending');frame.to_csv(tmp,index=False);tmp.replace(target)
  records.append(dict(date=date,schema='legacy_16' if legacy else 'modern_24',rows=len(frame),source_sha256=digest,normalized_sha256=sha256(target),source_replay_exact=True,units='shares',source_table_index=doc['tables'].index(table),quote_rows=qvalidation['rows'],quote_source_sha256=sha256(quotes),quote_codes_with_institutional=len(codes&flow_codes),quote_codes_without_institutional=missing,institutional_codes_without_quotes=extra,historical_ordinary_pool='pending; all quoted securities retained'))
 report=dict(samples=records,all_checks_passed=True,source_checkpoint='libfile_4a57a44bdfa8819189a971249a8740dc',limitation='Four source dates only; no annual completeness, historical ordinary pool, publication-time proof or profitable strategy claim. Legacy foreign net uses the official foreign/mainland aggregate; modern foreign net uses its published subtotal. Field change does not prove identical investor classification across eras. Missing stock rows remain unknown; source day must precede signal day.')
 atomic_json(root/'schema_validation.json',report)
 lines=['# 上櫃法人歷史格式驗收','','| 日期 | 格式 | 筆數 | 逐筆來源重播 |','|---|---|---:|---|']
 for r in records:lines.append(f"| {r['date']} | {r['schema']} | {r['rows']} | 通過 |")
 lines+=['','| 日期 | 全證券行情 | 法人日報有列 | 法人缺列（未知） |','|---|---:|---:|---:|']
 for r in records:lines.append(f"| {r['date']} | {r['quote_rows']} | {r['quote_codes_with_institutional']} | {len(r['quote_codes_without_institutional'])} |")
 lines+=['','已核對原始來源SHA、日期、確切欄位、逐筆買賣差額、分項合計、總額、重複代號與來源筆數。四個樣本全部通過。','','僅代表四個交易日；全年交易日覆蓋、當時普通股股票池與公司行動仍未完成。舊制外資及陸資合計與新制外資小計的投資人分類是否跨年代完全一致，仍須保留制度差異限制。缺列不當零、訊號至少落後来源日。']
 (root/'schema_validation.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
