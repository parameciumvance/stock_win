"""UMC SEC snapshot reconciliation; event dates are not financial quarter ends."""
import argparse
import json
from pathlib import Path
import zipfile
from prospective_sources import verify_archive
from research_runtime import atomic_json,exclusive_lock,sha256,utcnow

ROOT=Path('inputs/operating_pilot_20261016/umc_sec_import_20261016')
OUT=Path('deliverables/operating_umc_sec_import_20261016')
PROTOCOL=Path('configs/research_reassessment_20261016.json')
EXPECTED='2c394aa58212c2edcc581bac96d91c76e6cb8082383f4a8ca178180fccd19ddd'
FROZEN='b939e4271b1e3eca3757d8968a335b9f8902d0a870fbf33fd4b855d25942092b'
SOURCE='https://www.sec.gov/Archives/edgar/data/1033767/000095017025006966/0000950170-25-006966.txt'


def package():
    source=ROOT/'0000950170-25-006966.txt';meta=json.loads((ROOT/'import.json').read_text())
    if sha256(source)!=EXPECTED or meta['sha256']!=EXPECTED or source.stat().st_size!=meta['size_bytes']:raise ValueError('Imported SEC original drift')
    if meta.get('zone_host_url','').removeprefix('HostUrl=').rstrip('\x00')!=SOURCE:raise ValueError('Download origin mismatch')
    if sha256(PROTOCOL)!=FROZEN:raise ValueError('Frozen protocol drift')
    entries={'raw/'+source.name:source,'import.json':ROOT/'import.json','protocol.json':PROTOCOL}
    for tag,receipt_path,key in [('index','deliverables/operating_umc_locator_20261016/index_package.json','retrieved'),('pdf','deliverables/operating_pilot_20261016/checkpoint.json','retrieved_path')]:
        receipt=json.loads(Path(receipt_path).read_text());archive=Path(receipt[key]);verify_archive(archive,receipt['sha256'])
        entries['prior/'+tag+'.zip']=archive;entries['prior/'+tag+'_receipt.json']=Path(receipt_path)
    previous=Path('deliverables/operating_sec_import_20261016')
    state=json.loads((previous/'pipeline_state.json').read_text())
    for filename in ['source_ledger.csv','sec_evidence.json']:
        p=previous/filename
        if sha256(p)!=state['stages']['audit']['outputs'][str(p)]:raise ValueError('Prior TSMC evidence/ledger drift')
        entries['prior/'+filename]=p
    OUT.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(ROOT.parent/'acquisition.lock'):
        manifest={name:sha256(p) for name,p in entries.items()};archive=ROOT/'source_checkpoint.zip'
        with zipfile.ZipFile(archive.with_suffix('.pending'),'w',zipfile.ZIP_DEFLATED) as z:
            for name,p in sorted(entries.items()):z.writestr(zipfile.ZipInfo(name,(1980,1,1,0,0,0)),p.read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
            z.writestr(zipfile.ZipInfo('manifest.json',(1980,1,1,0,0,0)),json.dumps(manifest,sort_keys=True),compress_type=zipfile.ZIP_DEFLATED)
        archive.with_suffix('.pending').replace(archive);digest=sha256(archive);verify_archive(archive,digest)
        receipt=OUT/'package.json'
        if receipt.exists() and json.loads(receipt.read_text()).get('sha256')==digest:return
        atomic_json(receipt,dict(archive=str(archive),sha256=digest,manifest_files=len(manifest),created_at=utcnow(),retrieved=str(ROOT/'source_checkpoint.retrieved.zip'),transfer_receipt=str(ROOT/'transfer.json'),backup_label='operating_umc_sec_import_20261016'))


def audit():
    import csv,hashlib,io
    from pypdf import PdfReader
    from sec_submission import parse_submission
    from sec_submissions_index import locate_candidates
    from umc_sec_evidence import extract_umc_sec_text,guidance_umc,reconcile_clocks
    from operating_source_pilot import extract_umc_text
    from twse_history.revenue_pilot import visible_text
    package=json.loads((OUT/'package.json').read_text());transfer=json.loads((ROOT/'transfer.json').read_text())
    if transfer['sha256']!=package['sha256'] or transfer.get('roundtrip_verified') is not True:raise ValueError('Stale UMC SEC transfer receipt')
    verify_archive(Path(package['retrieved']),package['sha256'])
    with zipfile.ZipFile(package['retrieved']) as z:
        body=z.read('raw/0000950170-25-006966.txt');meta=json.loads(z.read('import.json'))
        if hashlib.sha256(body).hexdigest()!=EXPECTED or meta['sha256']!=EXPECTED:raise ValueError('Archived original SEC drift')
        if hashlib.sha256(z.read('protocol.json')).hexdigest()!=FROZEN:raise ValueError('Frozen protocol drift')
        if meta['zone_host_url'].removeprefix('HostUrl=').rstrip('\x00')!=SOURCE:raise ValueError('Archived source URL mismatch')
        archives={}
        for tag in ['index','pdf']:
            original=z.read('prior/'+tag+'.zip');receipt=json.loads(z.read('prior/'+tag+'_receipt.json'))
            if hashlib.sha256(original).hexdigest()!=receipt['sha256']:raise ValueError('Prior archive drift')
            archives[tag]=original
        old_ledger=z.read('prior/source_ledger.csv').decode();tsmc_evidence=json.loads(z.read('prior/sec_evidence.json'))
    with zipfile.ZipFile(io.BytesIO(archives['index'])) as z:
        index_body=z.read('raw/CIK0001033767.json');index_meta=json.loads(z.read('import.json'))
        if hashlib.sha256(index_body).hexdigest()!=index_meta['sha256']:raise ValueError('Index source drift')
    candidates=locate_candidates(index_body,cik='0001033767',filing_date='2025-01-21')['candidates']
    if len(candidates)!=1 or candidates[0]['accession']!='0000950170-25-006966':raise ValueError('Ambiguous/mismatched SEC candidate')
    candidate=candidates[0]
    submission=parse_submission(body,cik='0001033767',accession=candidate['accession'],quarter='2024Q4',report_event_date=candidate['report_date_as_reported'])
    documents=submission.pop('documents');primary=next(d for d in documents if d['filename']==submission['primary_filename'])
    if primary['filename']!=candidate['primary_document']:raise ValueError('Submissions primary document mismatch')
    primary_text=visible_text(primary['payload'].decode())
    if 'United Microelectronics Corporation' not in primary_text or 'EXHIBIT INDEX' not in primary_text or '99' not in primary_text:
        raise ValueError('UMC primary identity/exhibit index not confirmed')
    release=[d for d in documents if d['filename']=='umc-ex99.htm' and d['type']=='EX-99']
    if len(release)!=1:raise ValueError('UMC original earnings exhibit not unique')
    text=visible_text(release[0]['payload'].decode());sec_values=extract_umc_sec_text(text);sec_guidance=guidance_umc(text)
    with zipfile.ZipFile(io.BytesIO(archives['pdf'])) as z:
        pdf=z.read('raw/umc_2024Q4_official.pdf');pdf_meta=json.loads(z.read('raw/umc_2024Q4_official.pdf.meta.json'))
        if hashlib.sha256(pdf).hexdigest()!=pdf_meta['sha256']:raise ValueError('UMC official PDF drift')
    reader=PdfReader(io.BytesIO(pdf));pdf_values=extract_umc_text(reader.pages[0].extract_text(extraction_mode='layout'))
    pdf_guidance=guidance_umc(reader.pages[10].extract_text())
    for key in ['issuer','quarter','visible_release_date','gross_margin_pct','eps_twd','revenue_twd_billions']:
        if sec_values[key]!=pdf_values[key]:raise ValueError('SEC exhibit and issuer PDF disagree: '+key)
    if sec_guidance!=pdf_guidance:raise ValueError('SEC/PDF guidance predicates differ')
    clock=reconcile_clocks(submission['acceptance'],candidate['acceptanceDateTime_as_reported'])
    atomic_json(OUT/'clock_reconciliation.json',clock)
    evidence=dict(submission,source_url=SOURCE,source_sha256=EXPECTED,source_size_bytes=len(body),source_origin='User browser download; Zone.Identifier HostUrl and imported hash verified, not a SEC digital signature',
                  source_http_headers_available=False,source_import_observed_at=meta['observed_at'],index_source_sha256=index_meta['sha256'],index_candidate=candidate,
                  documents=[{k:v for k,v in d.items() if k!='payload'} for d in documents],
                  financial_quarter_verified_from_exhibit=True,exhibit_financial_values=sec_values,pdf_financial_values=pdf_values,
                  pdf_sha256=pdf_meta['sha256'],pdf_source_page=1,numeric_reconciliation_passed=True,
                  guidance=sec_guidance,guidance_pdf_source_page=11,guidance_reconciliation_passed=True,
                  clock_reconciliation=clock,sec_snapshot_verified=True,sec_accepted_time_corroborated=False,
                  taiwan_first_published_at=None,public_dissemination_at=None,complete_revision_history_verified=False,ready_for_model=False,
                  checkpoint_sha256=package['sha256'])
    atomic_json(OUT/'sec_evidence.json',evidence)
    rows=list(csv.DictReader(io.StringIO(old_ledger)))
    if len(rows)!=24:raise ValueError('Wrong pilot ledger size')
    for row in rows:row.update(sec_clock_status='',sec_header_accepted_at_interpreted='',sec_json_accepted_at_as_reported='')
    tsmc=next(r for r in rows if r['issuer']=='2330' and r['quarter']=='2024Q4')
    if tsmc['sec_submission_sha256']!=tsmc_evidence['source_sha256']:raise ValueError('Prior TSMC evidence mismatch')
    tsmc.update(sec_clock_status='header_and_parsed_official_index_corroborated',sec_header_accepted_at_interpreted=tsmc['sec_accepted_at'])
    matches=[r for r in rows if r['issuer']=='2303' and r['quarter']=='2024Q4']
    if len(matches)!=1:raise ValueError('UMC issuer-quarter not unique')
    umc=matches[0]
    for key in ['gross_margin_pct','eps_twd','revenue_twd_billions']:
        if float(umc[key])!=sec_values[key]:raise ValueError('Prior PDF ledger mismatch')
    umc.update(sec_snapshot_verified=True,sec_submission_sha256=EXPECTED,sec_primary_filename=primary['filename'],
               sec_exhibit_payload_sha256=release[0]['payload_sha256'],version_evidence='one_original_sec_submission_and_pdf_reconciled',
               sec_accepted_at='',sec_clock_status=clock['status'],sec_header_accepted_at_interpreted=clock['sgml_taipei_interpretation'],
               sec_json_accepted_at_as_reported=clock['json_as_reported'],ready_for_model=False,
               status='sec_snapshot_numeric_reconciled_clock_conflict_pending' if not clock['matches'] else 'sec_snapshot_numeric_reconciled_full_time_gate_pending')
    with (OUT/'source_ledger.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)


def report():
    import csv
    evidence=json.loads((OUT/'sec_evidence.json').read_text());clock=json.loads((OUT/'clock_reconciliation.json').read_text())
    package=json.loads((OUT/'package.json').read_text());transfer=json.loads((ROOT/'transfer.json').read_text())
    verify_archive(Path(package['retrieved']),package['sha256'])
    with (OUT/'source_ledger.csv').open() as f:rows=list(csv.DictReader(f))
    if len(rows)!=24 or any(row['ready_for_model']!='False' for row in rows):raise ValueError('No automatic model promotion')
    atomic_json(OUT/'checkpoint.json',dict(package,backup_path=transfer['backup_path'],roundtrip_verified=True,crc_verified=True,verified_at=utcnow()))
    atomic_json(OUT/'summary.json',dict(status='both_issuer_sec_snapshots_reconciled_umc_clock_conflict',issuer_quarters_with_numeric_original=2,issuer_quarters_with_complete_sec_snapshot=2,
                sec_header_clock_corroborated_quarters=1,sec_clock_conflict_quarters=0 if clock['matches'] else 1,missing_original_quarters=22,
                full_timing_revision_gate_verified_quarters=0,models_fitted=0,evaluation_rows=0,ready_for_model=False,
                checkpoint_sha256=package['sha256'],seven_rule_daily_plan='stopped_by_user_no_resume',next_external_dependency='Original UMC filing index HTML Accepted field or authoritative SEC clarification to resolve the preserved five-hour SGML/JSON conflict'))
    (OUT/'report.md').write_text(f'''# 聯電2024Q4完整SEC申報：數值一致，接受時鐘衝突

使用者指定的`0000950170-25-006966.txt`已原樣匯入，55,016 bytes，SHA `{EXPECTED}`。來源與WSL複本hash一致，下載Zone.Identifier HostUrl符合指定SEC URL。先打包原文、metadata、凍結協定、已驗收聯電索引／PDF原始包與前輪台積電證據及ledger，再Windows備份取回，整包SHA／manifest／CRC通過。checkpoint SHA `{package['sha256']}`；同電腦跨檔案系統，不宣稱離機備份。

## 已核實的文件與數值

CIK 0001033767、accession 0000950170-25-006966、6-K主文件`6k_on_01212025.htm`、EX-99附件`umc-ex99.htm`及GRAPHIC共3個文件區塊均核對通過。SEC標頭report period是事件日2025-01-21；財務季度由附件的2024Q4標題、內文與既有PDF確認，未把事件日當季度末，也沒有放寬其他申報的預設季度末檢查。

SEC附件與官方PDF第1頁獨立解析，2024Q4合併毛利率30.4%、EPS新台幣0.68元、合併營收60.39十億元一致。PDF明示TIFRS合併口徑；SEC節錄明示合併，但沒有TIFRS字樣，不補造SEC原文明示會計準則的證據。

SEC與PDF第11頁的2025Q1毛利率財測也一致：在0121地震影響下「高於25%」。它是帶條件的嚴格下界，不是25%的點預測或25%～某上界；保留predicate與point_forecast=null，不自行取中點、不計算MAE。

## 5小時衝突：不自動修正

完整SGML標頭原值 `{clock['sgml_raw']}`，按SEC美東解讀為`{clock['sgml_eastern_interpretation']}`，換算UTC `{clock['sgml_utc_interpretation']}`、台北 `{clock['sgml_taipei_interpretation']}`。

已封存submissions JSON同一accession原值 `{clock['json_as_reported']}`，其Z標記宣稱UTC。兩者相差 `{clock['delta_seconds_json_minus_sgml']}` 秒。CIK、accession、主文件與reportDate均匹配，因此不能把差異當作不同申報，也不能選擇較早或較晚時間覆蓋另一來源。沒有推斷SEC網站根因。

保留兩個原值與計算差異；聯電ledger的canonical sec_accepted_at維持空白、sec_clock_status=conflict。需要[此申報的官方索引](https://www.sec.gov/Archives/edgar/data/1033767/000095017025006966/0000950170-25-006966-index.htm)原始HTML Accepted欄位或SEC權威說明再核對。本輪web工具未取得索引內容，未推測其HTTP狀態；先前已保存的直接請求HTTP403仍為歷史觀察，不算本輪重新下載。

## 目前範圍與下一步

台積電、聯電2024Q4各有官方PDF及完整SEC原始版本，兩組數值重播通過。22季原文仍缺；台積電時鐘已有官方索引解析觀察佐證，聯電有一組明確時鐘衝突。台灣首次公開／公開傳播時點與完整修訂歷程未通過，全部24列仍不可建模。

先處理這個具體衝突，不擴大22季下載、不擬合模型、不計算預測績效，七規則每日計畫維持停止。現有兩份完整申報、聯電JSON及兩家公司PDF不需重傳。若一般瀏覽器能讀取，請把上述官方索引頁另存HTML到Downloads，核對Accepted欄位，而非以瀏覽器另存／檔案修改時間作公告時間。
''')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['package','audit','report']);a=p.parse_args();globals()[a.stage]()
