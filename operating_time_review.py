"""Bounded source-time/version audit; raw acquisition is preserved before PDF replay."""
import argparse
import json
from pathlib import Path
import zipfile
from prospective_sources import verify_archive
from research_runtime import atomic_json,exclusive_lock,sha256,utcnow

ROOT=Path('inputs/operating_pilot_20261016/time_sources_20261017')
OUT=Path('deliverables/operating_time_review_20261017')
PROTOCOL=Path('configs/research_reassessment_20261016.json')
FROZEN='b939e4271b1e3eca3757d8968a335b9f8902d0a870fbf33fd4b855d25942092b'
CONFIGS={'probe':Path('configs/operating_time_sources_20261017.json'),'curl':Path('configs/operating_time_pdf_sources_20261017.json')}


def package():
    if sha256(PROTOCOL)!=FROZEN:raise ValueError('Frozen protocol drift')
    entries={'protocol.json':PROTOCOL,'web_observations.json':ROOT/'web_observations.json','acquire_pdfs.py':ROOT/'acquire_pdfs.py'}
    for tag,config in CONFIGS.items():
        cfg=json.loads(config.read_text());result=json.loads((ROOT/tag/'results.json').read_text())
        if result['workers']!=2 or result['config_sha256']!=sha256(config):raise ValueError('Source configuration drift')
        if sorted((r['filename'],r['url']) for r in result['requests'])!=sorted((r['filename'],r['url']) for r in cfg['requests']):raise ValueError('Missing/duplicate request')
        entries['configs/'+tag+'.json']=config
        for p in (ROOT/tag).iterdir():
            if p.is_file() and p.name!='acquisition.lock':entries[tag+'/'+p.name]=p
        for row in result['requests']:
            body=ROOT/tag/row['filename'];meta=json.loads((ROOT/tag/(row['filename']+'.meta.json')).read_text())
            if row!=meta:raise ValueError('Response metadata drift')
            if 'sha256' in row:
                if sha256(body)!=row['sha256'] or body.stat().st_size!=row['size_bytes']:raise ValueError('Response byte drift')
            elif not row.get('error') or body.exists():raise ValueError('Unaccounted missing/partial response')
    for tag,receiptpath,key in [
        ('umc','deliverables/operating_umc_index_html_20261017/checkpoint.json','retrieved'),
        ('tsmc','deliverables/operating_sec_import_20261016/package.json','retrieved'),
        ('umc_index','deliverables/operating_umc_locator_20261016/index_package.json','retrieved')]:
        p=Path(receiptpath);receipt=json.loads(p.read_text());archive=Path(receipt[key]);verify_archive(archive,receipt['sha256'])
        entries['prior/'+tag+'.zip']=archive;entries['prior/'+tag+'_receipt.json']=p
    state=json.loads(Path('deliverables/operating_umc_index_html_20261017/pipeline_state.json').read_text())
    ledger=Path('deliverables/operating_umc_index_html_20261017/source_ledger.csv')
    if sha256(ledger)!=state['stages']['audit']['outputs'][str(ledger)]:raise ValueError('Latest ledger drift')
    entries['prior/source_ledger.csv']=ledger
    OUT.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(ROOT.parent/'acquisition.lock'):
        manifest={name:sha256(p) for name,p in entries.items()};archive=ROOT/'source_checkpoint.zip'
        with zipfile.ZipFile(archive.with_suffix('.pending'),'w') as z:
            for name,p in sorted(entries.items()):z.writestr(zipfile.ZipInfo(name,(1980,1,1,0,0,0)),p.read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
            z.writestr(zipfile.ZipInfo('manifest.json',(1980,1,1,0,0,0)),json.dumps(manifest,sort_keys=True),compress_type=zipfile.ZIP_DEFLATED)
        archive.with_suffix('.pending').replace(archive);digest=sha256(archive);verify_archive(archive,digest)
        receipt=OUT/'package.json'
        if receipt.exists() and json.loads(receipt.read_text())['sha256']==digest:return
        atomic_json(receipt,dict(archive=str(archive),sha256=digest,manifest_files=len(manifest),created_at=utcnow(),retrieved=str(ROOT/'source_checkpoint.retrieved.zip'),transfer_receipt=str(ROOT/'transfer.json'),backup_label=OUT.name))


def retrieved():
    receipt=json.loads((OUT/'package.json').read_text());transfer=json.loads((ROOT/'transfer.json').read_text())
    if transfer['sha256']!=receipt['sha256'] or transfer.get('roundtrip_verified') is not True:raise ValueError('Missing/stale roundtrip receipt')
    verify_archive(Path(receipt['retrieved']),receipt['sha256'])
    return receipt,transfer


def audit():
    import csv,hashlib,io
    from pypdf import PdfReader
    from operating_version_review import review_index,classify_time
    from operating_windows_recovery import extract_tsmc_text
    package,_=retrieved()
    with zipfile.ZipFile(package['retrieved']) as z:
        if hashlib.sha256(z.read('protocol.json')).hexdigest()!=FROZEN:raise ValueError('Frozen protocol drift')
        rows=list(csv.DictReader(io.StringIO(z.read('prior/source_ledger.csv').decode())))
        observations=json.loads(z.read('web_observations.json'))
        receipt=json.loads(z.read('prior/umc_index_receipt.json'));original=z.read('prior/umc_index.zip')
        if hashlib.sha256(original).hexdigest()!=receipt['sha256']:raise ValueError('Original UMC index archive drift')
        with zipfile.ZipFile(io.BytesIO(original)) as index:
            raw=index.read('raw/CIK0001033767.json')
            if hashlib.sha256(raw).hexdigest()!=json.loads(index.read('import.json'))['sha256']:raise ValueError('Index bytes drift')
        review=review_index(raw,cik='0001033767',company_fragment='UNITED MICROELECTRONICS',start='2025-01-21',end='2025-04-30',period_end='2024-12-31',anchor_accession='0000950170-25-006966')
        review.update(source_sha256=hashlib.sha256(raw).hexdigest(),checkpoint_sha256=package['sha256'])
        atomic_json(OUT/'umc_version_candidates.json',review)
        transports=[];pdfs={}
        for tag in CONFIGS:
            cfgbytes=z.read('configs/'+tag+'.json');cfg=json.loads(cfgbytes);result=json.loads(z.read(tag+'/results.json'))
            if result['workers']!=2 or hashlib.sha256(cfgbytes).hexdigest()!=result['config_sha256']:raise ValueError('Archived request config drift')
            if sorted((r['filename'],r['url']) for r in result['requests'])!=sorted((r['filename'],r['url']) for r in cfg['requests']):raise ValueError('Archived request list mismatch')
            for row in result['requests']:
                meta=json.loads(z.read(tag+'/'+row['filename']+'.meta.json'))
                if meta!=row:raise ValueError('Archived response metadata drift')
                if 'sha256' in row:
                    body=z.read(tag+'/'+row['filename'])
                    if hashlib.sha256(body).hexdigest()!=row['sha256'] or len(body)!=row['size_bytes']:raise ValueError('Archived response hash mismatch')
                elif not row.get('error'):raise ValueError('Missing response without error')
                transports.append({k:row.get(k) for k in ['filename','url','transport','http_status','error','request_started_at','observed_at','sha256','size_bytes']})
                if tag=='curl':
                    if row['exit_code']!=0 or row['http_status']!=200 or row['curl']['url_effective']!=row['url'] or not body.startswith(b'%PDF-'):raise ValueError('Official PDF not obtained')
                    reader=PdfReader(io.BytesIO(body));pdfs[row['filename']]=dict(text=' '.join(' '.join(p.extract_text().split()) for p in reader.pages),pages=len(reader.pages),sha256=row['sha256'],url=row['url'])
    if len(rows)!=24 or any(r['ready_for_model']!='False' for r in rows):raise ValueError('Pilot readiness drift')
    invitation=pdfs['umc_conference.pdf'];text=invitation['text']
    if not all(t in text for t in ['United Microelectronics Corporation','4Q 2024','January 21, 2025','05:00 PM (Taipei)','04:00 AM (New York)']):raise ValueError('Conference identity/schedule mismatch')
    variant=pdfs['tsmc_without_guidance.pdf'];values=extract_tsmc_text(variant['text'])
    tsmc=next(r for r in rows if r['issuer']=='2330' and r['quarter']=='2024Q4')
    for k in ['gross_margin_pct','eps_twd','revenue_twd_billions']:
        if float(tsmc[k])!=values[k]:raise ValueError('Same-quarter TSMC version numeric mismatch')
    if variant['sha256']==tsmc['release_document_sha256']:raise ValueError('Expected distinct PDF representation')
    time_evidence=[classify_time('conference_schedule','2025-01-21 17:00 Asia/Taipei',source_url=invitation['url'],raw_obtained=True),
                   classify_time('issuer_date','2025-01-16',source_url=variant['url'],raw_obtained=True),
                   classify_time('usual_process_duration','Usually no longer than two minutes; not a guaranteed bound',source_url=observations['observations'][0]['url'],raw_obtained=False)]
    atomic_json(OUT/'source_review.json',dict(umc_conference={k:v for k,v in invitation.items() if k!='text'},tsmc_additional_pdf=dict({k:v for k,v in variant.items() if k!='text'},financial_values=values,financial_values_match=True,
        guidance_phrase_present='Gross profit margin is expected to be between' in variant['text'],distinct_representation_not_proven_revision_order=True),time_evidence=time_evidence,
        full_revision_history_verified=False,public_dissemination_at=None,taiwan_first_published_at=None,ready_for_model=False))
    atomic_json(OUT/'transport_inventory.json',dict(records=transports,requests=len(transports),http_200=sum(r['http_status']==200 for r in transports),http_403=sum(r['http_status']==403 for r in transports),timeouts=sum((r.get('error') or {}).get('name')=='TimeoutError' for r in transports)))
    for row in rows:
        row.update(additional_source_review='',version_review_status='')
        if row['quarter']=='2024Q4':row.update(additional_source_review=str(OUT/'source_review.json'),version_review_status='additional_pdf_representation_no_revision_order' if row['issuer']=='2330' else 'ordinary_6k_later_same_period_candidate_unverified')
    with (OUT/'source_ledger.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)


def report():
    package,transfer=retrieved();review=json.loads((OUT/'umc_version_candidates.json').read_text());sources=json.loads((OUT/'source_review.json').read_text());transport=json.loads((OUT/'transport_inventory.json').read_text())
    atomic_json(OUT/'checkpoint.json',dict(package,backup_path=transfer['backup_path'],roundtrip_verified=True,crc_verified=True,verified_at=utcnow()))
    candidates=[c for c in review['candidates'] if c['relation']=='same_period_end_later_filing_candidate']
    locators=json.loads((OUT/'publication_locators.json').read_text())
    atomic_json(OUT/'next_tasks.json',dict(status='source_feasibility_gate_still_blocked',completed=['archived two additional official PDFs and six transport observations','replayed TSMC same-quarter alternate representation','inventoried ordinary filings as well as /A forms'],
        blockers=[dict(task='Obtain official originals for the two announcements located by secondary republications',locators=locators['locators'],available=False),dict(task='Review UMC later same-period filing; do not call it a correction before checking contents',candidates=candidates,available=False),
                  dict(task='Obtain document-specific public-time or authoritative release metadata and scoped version evidence for both pilot quarters',available=False,not_satisfied_by=['SEC acceptance','scheduled conference','file/PDF creation time','usual dissemination duration'])],
        next_if_sources_available='Compare exact versions and availability; only then scale the fixed 24-quarter cohort',no_existing_file_reupload_needed=True,seven_rule_daily_plan='stopped_by_user_no_resume'))
    atomic_json(OUT/'summary.json',dict(additional_original_pdfs=2,additional_issuer_quarters_with_financial_original=0,issuer_quarters_with_financial_original=2,missing_original_quarters=22,
        requests=transport['requests'],http_200=transport['http_200'],http_403=transport['http_403'],timeouts=transport['timeouts'],
        umc_window_candidate_count=len(review['candidates']),umc_explicit_amendment_candidate_count=review['explicit_amendment_candidates'],umc_later_same_period_candidates=len(candidates),
        ready_for_model=False,models_fitted=0,evaluation_rows=0,checkpoint_sha256=package['sha256']))
    (OUT/'report.md').write_text(f'''# 歷史公開時點與版本範圍續查

凍結研究協定SHA `{FROZEN}` 不變。既定關卡要求文件、版本、會計口徑與可驗證歷史時間；本輪未把嚴格「台灣第一次公開秒數／全世界所有修訂」當作已能查明的事實，也未另加可用資料的替代假設。來源時間仍有缺口，不自動升級建模。

## 實際新增

兩個worker的有界取得共6個請求：2個HTTP200、3個HTTP403、1個TimeoutError。原始成功／錯誤回應、headers、metadata、無回應逾時、web解析觀察筆記、凍結協定與先前來源包均先封存，再Windows備份取回，SHA／manifest／CRC通過後才解析PDF。checkpoint SHA `{package['sha256']}`。同電腦跨檔案系統，未宣稱離機備份。

- 聯電[2024Q4法說邀請](https://www.umc.com/upload/media/08_Investors/Financials/Quarterly_Results/Quarterly_2020-2029_English_pdf/2024/Q4_2024/UMC24Q4_conference_call.pdf)，76,263 bytes：排定2025-01-21台北17:00／紐約04:00。這是排程，不是實際舉行、新聞稿公開或首次公告的證明，不能拿來替換SEC接受時間19:03:58。
- 台積電[同季WoG文件](https://investor.tsmc.com/schinese/encrypt/files/encrypt_file/qr/phase4_reports/2025-01/4403102dcea6b02abaf1bd9778ea69e0ec6b4ab0/4Q24EarningsRelease_WoG.pdf)，163,244 bytes：毛利率59%、EPS14.45、營收868.46十億元與凍結含財測PDF一致。本份是否含財測phrase：`{sources['tsmc_additional_pdf']['guidance_phrase_present']}`。保留獨立SHA與來源，不替換舊PDF，不推斷兩者的先後／修訂順序。

## 版本盤點

重讀已封存的聯電submissions JSON（738列，1997-02-14～2026-10-13，files=[]）。在2025-01-21～2025-04-30的文件查核窗口，保留6-K、6-K/A、20-F、20-F/A全部候選；共{len(review['candidates'])}份，明示/A候選{review['explicit_amendment_candidates']}份。這個窗口只界定待查文件，不當預測截止時間或已核實財務季度。

其中2025-03-20的`0001292814-25-000981`，reportDate=2024-12-31、主文件`umcfs4q24_6k.htm`，是普通6-K後續同結束日候選。原文請求本輪403，未將它直接定性成更正或拿它覆寫1/21版本。另有4/24的20-F同結束日候選，僅憑reportDate不能把年度文件當同一季度版本。沒有/A也不代表沒有普通6-K更新、刪除或SEC接受後更正；當前JSON快照不是完整版本證明。

## 時間證據限制與下一步

[SEC歷史PDS技術規格](https://www.sec.gov/info/edgar/specifications/pds-dissemination-spec030314.pdf)區分接受、重組文件與傳播，通常兩分鐘不是逐份文件的保證上界；規格也描述PAC可更改header、刪除申報，而不更新文件內文。此項由web工具解析，直接原始PDF請求403，已明示未取得raw，不把解析文字冒充原始來源。台積電[新聞頁](https://pr.tsmc.com/english/news/3201)解析只確認2025/01/16日期，原始HTML請求403；Business Wire逾時，不能升為可驗證的精確時間。

目前新增的是兩份同季佐證文件，沒有增加財務季度：仍兩家公司2024Q4有原文、22季缺原文，全部24列ready_for_model=False，模型／評估0。接受時間與聯電JSON五小時差異原樣保留；七規則每日計畫不恢復。

另找到[台積電公告轉載定位](https://news.cnyes.com/news/print/5839133)與[聯電公告轉載定位](https://news.cnyes.com/news/print/5843049)，分別列2025/01/16 15:40:39及2025/01/21 17:00:11。這是轉載的發言時間，非官方原件／首次公開證明；只作查找原公告的線索。MOPS官方舊入口由web工具導向error頁，API入口不可存取，未推測HTTP狀態。詳見[定位筆記](publication_locators.json)。

下一個具體外部依賴是這兩筆MOPS公告原件，以及[聯電3/20完整申報](https://www.sec.gov/Archives/edgar/data/1033767/000129281425000981/0001292814-25-000981.txt)的內容核對，以及兩組季度的文件公開時點／版本涵蓋證據。現有PDF、JSON與完整申報不需重傳。見[next_tasks.json](next_tasks.json)、[候選清單](umc_version_candidates.json)、[測試](tests.json)、[階段hash](pipeline_state.json)。
''')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['package','audit','report']);globals()[parser.parse_args().stage]()
