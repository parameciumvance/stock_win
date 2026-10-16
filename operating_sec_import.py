"""SEC complete-submission import; source bytes and historical clocks stay distinct."""
import argparse
import json
from pathlib import Path
import zipfile
from prospective_sources import verify_archive
from research_runtime import atomic_json, exclusive_lock, sha256, utcnow

ROOT=Path('inputs/operating_pilot_20261016/sec_import_20261016')
OUT=Path('deliverables/operating_sec_import_20261016')
CONFIG=Path('configs/operating_sec_import_20261016.json')
PROTOCOL=Path('configs/research_reassessment_20261016.json')


def package():
    cfg=json.loads(CONFIG.read_text())
    if sha256(PROTOCOL)!=cfg['frozen_protocol_sha256']:raise ValueError('Frozen protocol drift')
    source=ROOT/cfg['source_filename'];meta=json.loads((ROOT/'import.json').read_text())
    if sha256(source)!=cfg['source_sha256'] or meta['sha256']!=cfg['source_sha256'] or source.stat().st_size!=meta['size_bytes']:
        raise ValueError('User-provided original drift')
    prior=Path('deliverables/operating_remote_20261016/checkpoint.json');receipt=json.loads(prior.read_text())
    verify_archive(Path(receipt['retrieved_path']),receipt['sha256'])
    OUT.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(ROOT.parent/'acquisition.lock'):
        entries={'raw/'+source.name:source,'import.json':ROOT/'import.json','source_config.json':CONFIG,'protocol.json':PROTOCOL,
                 'prior/checkpoint.json':prior,'prior/source_archive.zip':Path(receipt['retrieved_path'])}
        manifest={name:sha256(path) for name,path in entries.items()}
        archive=ROOT/'source_checkpoint.zip'
        with zipfile.ZipFile(archive.with_suffix('.pending'),'w',zipfile.ZIP_DEFLATED) as z:
            for name,path in sorted(entries.items()):z.write(path,name)
            z.writestr(zipfile.ZipInfo('manifest.json',(1980,1,1,0,0,0)),json.dumps(manifest,sort_keys=True),compress_type=zipfile.ZIP_DEFLATED)
        archive.with_suffix('.pending').replace(archive)
        digest=sha256(archive);verify_archive(archive,digest)
        atomic_json(OUT/'package.json',dict(archive=str(archive),sha256=digest,manifest_files=len(manifest),created_at=utcnow(),
                    retrieved=str(ROOT/'source_checkpoint.retrieved.zip'),transfer_receipt=str(ROOT/'transfer.json'),backup_label='operating_sec_import_20261016'))


def audit():
    import csv
    import hashlib
    import io
    import re
    from pypdf import PdfReader
    from sec_submission import parse_submission
    from twse_history.revenue_pilot import visible_text
    from operating_windows_recovery import extract_tsmc_text, validated_pdf
    from operating_remote_audit import guidance_tsmc
    package=json.loads((OUT/'package.json').read_text());transfer=json.loads((ROOT/'transfer.json').read_text())
    if transfer['sha256']!=package['sha256'] or transfer.get('roundtrip_verified') is not True:
        raise ValueError('Import archive transfer receipt mismatch')
    retrieved=Path(package['retrieved']);verify_archive(retrieved,package['sha256'])
    with zipfile.ZipFile(retrieved) as z:
        cfg=json.loads(z.read('source_config.json'));meta=json.loads(z.read('import.json'))
        body=z.read('raw/'+cfg['source_filename'])
        if hashlib.sha256(body).hexdigest()!=cfg['source_sha256'] or meta['sha256']!=cfg['source_sha256']:
            raise ValueError('SEC original hash mismatch')
        if hashlib.sha256(z.read('protocol.json')).hexdigest()!=cfg['frozen_protocol_sha256']:
            raise ValueError('Archived frozen protocol mismatch')
        host=meta.get('zone_host_url','').removeprefix('HostUrl=').rstrip('\x00')
        if host!=cfg['source_url']:raise ValueError('Download Zone HostUrl missing or different; explicit review required')
        prior_body=z.read('prior/source_archive.zip');prior_receipt=json.loads(z.read('prior/checkpoint.json'))
        if hashlib.sha256(prior_body).hexdigest()!=prior_receipt['sha256']:raise ValueError('Prior archive drift')
    submission=parse_submission(body,cik=cfg['cik'],accession=cfg['accession'],quarter=cfg['quarter'])
    docs=submission.pop('documents')
    release=[d for d in docs if d['filename']==cfg['release_exhibit_filename'] and d['type']==cfg['release_exhibit_type']]
    if len(release)!=1:raise ValueError('Expected earnings exhibit not uniquely present')
    primary=next(d for d in docs if d['filename']==submission['primary_filename'])
    primary_text=visible_text(primary['payload'].decode('utf-8'))
    if not re.search(r'Taiwan Semiconductor Manufacturing Company (?:Ltd\.|Limited)(?=\s|$)',primary_text,re.I):
        raise ValueError('Primary document issuer not confirmed')
    if cfg['release_exhibit_filename'].encode() not in primary['payload']:
        raise ValueError('Primary 6-K does not reference earnings exhibit')
    release_text=visible_text(release[0]['payload'].decode('utf-8'))
    release_text=re.sub(r'\bJan\.\s+16,\s+2025\b','January 16, 2025',release_text)
    sec_values=extract_tsmc_text(release_text);sec_guidance=guidance_tsmc(release_text)
    # Independently replay the issuer PDF from the already-verified prior archive.
    with zipfile.ZipFile(io.BytesIO(prior_body)) as prior:
        prior_tsmc=prior.read('prior/tsmc.zip')
        prior_tsmc_meta=json.loads(prior.read('prior/tsmc_receipt.json'))
        if hashlib.sha256(prior_tsmc).hexdigest()!=prior_tsmc_meta['sha256']:raise ValueError('TSMC nested archive drift')
    with zipfile.ZipFile(io.BytesIO(prior_tsmc)) as prior:
        pdf_meta=json.loads(prior.read('curl/tsmc_2024Q4.pdf.meta.json'))
        pdf=validated_pdf(prior.read('curl/tsmc_2024Q4.pdf'),pdf_meta)
    pdf_text=PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    pdf_values=extract_tsmc_text(pdf_text);pdf_guidance=guidance_tsmc(pdf_text)
    if sec_values!=pdf_values or sec_guidance!=pdf_guidance:raise ValueError('SEC exhibit and issuer PDF financial values disagree')
    observed=json.loads((OUT/'index_observation.json').read_text())
    expected=dict(accession=cfg['accession'],cik=cfg['cik'],form='6-K',accepted_as_displayed=submission['acceptance']['eastern'][:19].replace('T',' '),
                  document_count=submission['document_count'],period_of_report='2024-12-31',primary_filename=primary['filename'],exhibit_filename=release[0]['filename'],complete_submission_size_bytes=len(body))
    if any(observed.get(k)!=v for k,v in expected.items()):raise ValueError('Parsed official index observation disagrees with original SGML')
    evidence=dict(submission,source_sha256=cfg['source_sha256'],source_size_bytes=len(body),source_url=cfg['source_url'],
                  import_observed_at=meta['observed_at'],download_zone_host_matches=True,source_http_headers_available=False,
                  source_origin='User-provided browser download; Zone.Identifier HostUrl matches expected SEC URL, not a cryptographic SEC signature',
                  documents=[{k:v for k,v in d.items() if k!='payload'} for d in docs],
                  exhibit_financial_values=sec_values,issuer_pdf_sha256=pdf_meta['sha256'],issuer_pdf_financial_values=pdf_values,
                  financial_reconciliation_passed=True,management_guidance=sec_guidance,parsed_index_corroboration=observed,
                  sec_snapshot_and_header_clock_verified=True,independent_index_raw_response_available=False,
                  submissions_json_crosscheck_available=False,taiwan_first_published_at=None,public_dissemination_timestamp=None,
                  complete_revision_history_verified=False,ready_for_model=False,checkpoint_sha256=package['sha256'])
    atomic_json(OUT/'sec_evidence.json',evidence)
    prior_csv=Path('deliverables/operating_remote_20261016/source_ledger.csv')
    prior_state=json.loads(Path('deliverables/operating_remote_20261016/pipeline_state.json').read_text())
    if sha256(prior_csv)!=prior_state['stages']['audit']['outputs'][str(prior_csv)]:raise ValueError('Prior source ledger drift')
    with prior_csv.open() as f:rows=list(csv.DictReader(f))
    matches=[r for r in rows if r['issuer']==cfg['issuer'] and r['quarter']==cfg['quarter']]
    if len(rows)!=24 or len(matches)!=1:raise ValueError('Incorrect issuer-quarter ledger')
    row=matches[0]
    for key in ['gross_margin_pct','eps_twd','revenue_twd_billions']:
        if float(row[key])!=sec_values[key]:raise ValueError('Frozen PDF ledger and SEC values disagree')
    for r in rows:
        r.update(sec_submission_sha256='',sec_primary_filename='',sec_exhibit_payload_sha256='',sec_snapshot_verified=False)
    row.update(sec_accepted_at=submission['acceptance']['taipei'],version_evidence='one_original_sec_submission_and_pdf_reconciled',
               sec_submission_sha256=cfg['source_sha256'],sec_primary_filename=primary['filename'],sec_exhibit_payload_sha256=release[0]['payload_sha256'],
               sec_snapshot_verified=True,status='sec_snapshot_header_clock_verified_full_timing_revision_gate_pending',ready_for_model=False)
    with (OUT/'source_ledger.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)


def report():
    import csv
    evidence=json.loads((OUT/'sec_evidence.json').read_text());package=json.loads((OUT/'package.json').read_text());transfer=json.loads((ROOT/'transfer.json').read_text())
    verify_archive(Path(package['retrieved']),package['sha256'])
    with (OUT/'source_ledger.csv').open() as f:rows=list(csv.DictReader(f))
    if len(rows)!=24 or any(r['ready_for_model']!='False' for r in rows):raise ValueError('No automatic model promotion')
    atomic_json(OUT/'checkpoint.json',dict(package,backup_path=transfer['backup_path'],roundtrip_verified=True,crc_verified=True,verified_at=utcnow()))
    atomic_json(OUT/'summary.json',dict(status='tsmc_sec_snapshot_verified_full_pilot_gate_pending',numeric_original_quarters=2,
                sec_snapshot_header_clock_verified_quarters=1,missing_original_quarters=22,missing_sec_snapshot_quarters=23,
                full_timing_revision_gate_verified_quarters=0,models_fitted=0,evaluation_rows=0,
                sec_accepted_at=evidence['acceptance']['taipei'],source_sha256=evidence['source_sha256'],checkpoint_sha256=package['sha256'],
                seven_rule_daily_plan='stopped_by_user_no_resume',next_external_dependency='UMC 2024Q4 original complete SEC submission; independent publication/revision coverage still pending'))
    (OUT/'report.md').write_text(f'''# 台積電2024Q4完整SEC申報匯入

使用者指定Windows下載檔`0001046179-25-000004.txt`，透過Desktop Commander原樣複製至專案，Windows來源與WSL匯入SHA一致。檔案{evidence['source_size_bytes']:,} bytes，SHA256 `{evidence['source_sha256']}`。下載檔Zone.Identifier的HostUrl吻合先前提供的SEC完整申報URL；這是來源鏈證據，不是SEC數位簽章，也沒有虛構原始HTTP headers或下載時刻。

先保存原文與匯入metadata，再連同既有原始包、來源設定與凍結研究協定打包，複製至Windows研究備份目錄後取回WSL。整包SHA／manifest／CRC通過，checkpoint SHA `{package['sha256']}`。同一電腦的跨檔案系統備份，不宣稱離機備份。

## 解析與交叉核對

SGML標頭確認CIK 0001046179、accession 0001046179-25-000004、原始6-K及報告期2024-12-31。19個文件區塊的數量、sequence、檔名及完整結尾一致。主文件為`tsm-20250116x6k.htm`，有引用`a4q24e_withguidancexfinal.htm`盈餘附件EX-99.1；不是把附件當主文件。

接受時間原始欄位`{evidence['acceptance']['raw']}`，依SEC美東時間解讀為`{evidence['acceptance']['eastern']}`，換算UTC `{evidence['acceptance']['utc']}`、台北 `{evidence['acceptance']['taipei']}`。與[官方索引](https://www.sec.gov/Archives/edgar/data/1046179/000104617925000004/0001046179-25-000004-index.htm)解析文字中的接受時間、19文件、主文件與附件名、完整申報大小相符。索引只保存明示的解析觀察，沒有冒充原始HTML；submissions JSON仍未取得。

SEC盈餘附件與既有官方PDF各自解析，毛利率59.0%、EPS新台幣14.45元、合併營收868.46十億元完全一致；2025Q1毛利率財測區間57%～59%也一致。SEC內嵌文件的payload hash僅代表完整SGML中的原樣payload，不宣稱等於另一URL獨立下載HTML的hash或長度。

## 進度與限制

已取得的原始公司季仍為2330與2303之2024Q4兩季；台積電其中一季新增完整SEC版本／標頭接受時間證據。其餘22季仍缺原文，23季仍缺SEC原始版本；全部24季均維持ready_for_model=False。

SEC接受時間不等於台灣首次公告或公開傳播時間；未把檔案修改時間、匯入時間、PDF日期當作首次公開時刻，也未宣稱完整修訂歷程已驗證。沒有擬合模型、計算預測誤差、產生交易訊號或恢復七規則每日計畫。既有研究參數與原始檔案未替換。

下一個來源依賴是聯電2024Q4完整SEC申報。先完成兩組來源路徑與時間／版本核驗，再決定是否能依凍結協定推進其餘22季。不是要求重新提供台積電PDF或這份完整申報。
''')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['package','audit','report']);args=parser.parse_args();globals()[args.stage]()
