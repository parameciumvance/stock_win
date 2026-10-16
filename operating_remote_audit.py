"""Archive and replay the bounded remote source pilot; missing timing stays a gap."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from prospective_sources import verify_archive
from research_runtime import atomic_json, exclusive_lock, sha256, utcnow

ROOT=Path('inputs/operating_pilot_20261016')
OUT=Path('deliverables/operating_remote_20261016')
CONFIG=Path('configs/research_reassessment_20261016.json')
FROZEN_SHA='b939e4271b1e3eca3757d8968a335b9f8902d0a870fbf33fd4b855d25942092b'
BATCHES=['remote_probe_20261016','remote_followup_20261016']
ARCHIVE=ROOT/'remote_checkpoint.zip'
RETRIEVED=ROOT/'remote_checkpoint.retrieved.zip'
TRANSFER=ROOT/'remote_transfer_receipt.json'


def validate_observation(body, record):
    if hashlib.sha256(body).hexdigest()!=record.get('sha256') or len(body)!=record.get('size_bytes'):
        raise ValueError('Remote response bytes/hash mismatch')
    if not record.get('request_started_at') or not record.get('observed_at'):
        raise ValueError('Missing actual request clock')
    from datetime import datetime
    stamps=[datetime.fromisoformat(record[k].replace('Z','+00:00')) for k in ['request_started_at','observed_at']]
    if any(s.tzinfo is None for s in stamps) or stamps[1]<stamps[0]:
        raise ValueError('Invalid request clock')
    status=record.get('http_status')
    if not isinstance(status,int) or not 100<=status<=599:
        raise ValueError('Unknown HTTP outcome; explicit review required')
    return dict(url=record['url'],http_status=status,sha256=record['sha256'],size_bytes=len(body),
                request_started_at=record['request_started_at'],observed_at=record['observed_at'],
                transport=record['transport'],valid_source_response=status==200)


def guidance_tsmc(text):
    text=' '.join(text.split())
    if 'for first quarter 2025 to be as follows:' not in text:
        raise ValueError('Wrong management guidance target quarter')
    ranges=re.findall(r'Gross profit margin is expected to be between ([\d.]+)% and ([\d.]+)%',text)
    if len(ranges)!=1:raise ValueError('Missing or ambiguous guidance range')
    lower,upper=map(float,ranges[0])
    if not 0<=lower<=upper<=100:raise ValueError('Invalid guidance range')
    return dict(target_quarter='2025Q1',gross_margin_lower_pct=lower,gross_margin_upper_pct=upper,
                timing_verified=False,ready_for_evaluation=False)


def package():
    if sha256(CONFIG)!=FROZEN_SHA:raise ValueError('Frozen pilot protocol drift')
    OUT.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(ROOT/'acquisition.lock'):
        entries={'protocol.json':CONFIG,'code/operating_remote_sources.mjs':Path('operating_remote_sources.mjs'),'code/operating_remote_backup.mjs':Path('operating_remote_backup.mjs')}
        for batch in BATCHES:
            folder=ROOT/batch
            for file in folder.iterdir():
                if file.is_file() and file.name!='acquisition.lock':entries[f'{batch}/{file.name}']=file
        for name in ['operating_remote_sources.json','operating_remote_followup_sources.json']:
            entries['configs/'+name]=Path('configs')/name
        for tag,path,key in [('umc','deliverables/operating_pilot_20261016/checkpoint.json','retrieved_path'),('tsmc','deliverables/operating_windows_recovery_20261016/checkpoint.json','retrieved')]:
            receipt=json.loads(Path(path).read_text());prior=Path(receipt[key])
            verify_archive(prior,receipt['sha256'])
            entries[f'prior/{tag}.zip']=prior;entries[f'prior/{tag}_receipt.json']=Path(path)
        manifest={name:sha256(path) for name,path in entries.items()}
        with zipfile.ZipFile(ARCHIVE.with_suffix('.pending'),'w',zipfile.ZIP_DEFLATED) as z:
            for name,path in sorted(entries.items()):z.write(path,name)
            # A rerun with identical sources must not change the package hash.
            info=zipfile.ZipInfo('manifest.json',date_time=(1980,1,1,0,0,0))
            z.writestr(info,json.dumps(manifest,sort_keys=True),compress_type=zipfile.ZIP_DEFLATED)
        ARCHIVE.with_suffix('.pending').replace(ARCHIVE)
        verify_archive(ARCHIVE,sha256(ARCHIVE))
        atomic_json(OUT/'package.json',dict(archive=str(ARCHIVE),sha256=sha256(ARCHIVE),manifest_files=len(manifest),protocol_sha256=FROZEN_SHA,created_at=utcnow()))


def audit():
    from pypdf import PdfReader
    from operating_source_pilot import extract_umc_text
    from operating_windows_recovery import extract_tsmc_text,validated_pdf
    package=json.loads((OUT/'package.json').read_text());transfer=json.loads(TRANSFER.read_text())
    if transfer.get('sha256')!=package['sha256'] or transfer.get('roundtrip_verified') is not True:
        raise ValueError('Windows transfer receipt mismatch')
    verify_archive(RETRIEVED,package['sha256'])
    records=[]
    with zipfile.ZipFile(RETRIEVED) as z:
        if hashlib.sha256(z.read('protocol.json')).hexdigest()!=FROZEN_SHA:
            raise ValueError('Archived frozen protocol drift')
        for batch in BATCHES:
            results=json.loads(z.read(batch+'/results.json'))
            if results['workers']!=2:raise ValueError('Unexpected acquisition concurrency')
            name='operating_remote_sources.json' if batch==BATCHES[0] else 'operating_remote_followup_sources.json'
            source_config=z.read('configs/'+name)
            if hashlib.sha256(source_config).hexdigest()!=results['config_sha256']:
                raise ValueError('Acquisition manifest drift')
            expected=json.loads(source_config)['requests']
            actual=results['requests']
            if sorted((r['filename'],r['url']) for r in actual)!=sorted((r['filename'],r['url']) for r in expected):
                raise ValueError('Missing/duplicate acquisition observations')
            for record in actual:
                meta=json.loads(z.read(batch+'/'+record['filename']+'.meta.json'))
                if record!=meta:raise ValueError('Acquisition metadata/results disagree')
                records.append(validate_observation(z.read(batch+'/'+record['filename']),record))
        prior={}
        for issuer in ['umc','tsmc']:
            body=z.read('prior/'+issuer+'.zip');receipt=json.loads(z.read('prior/'+issuer+'_receipt.json'))
            if hashlib.sha256(body).hexdigest()!=receipt['sha256']:raise ValueError('Prior archive drift')
            prior[issuer]=body
        with zipfile.ZipFile(io.BytesIO(prior['umc'])) as nested:
            umc_body=nested.read('raw/umc_2024Q4_official.pdf');umc_meta=json.loads(nested.read('raw/umc_2024Q4_official.pdf.meta.json'))
            if hashlib.sha256(umc_body).hexdigest()!=umc_meta['sha256']:raise ValueError('UMC PDF drift')
        with zipfile.ZipFile(io.BytesIO(prior['tsmc'])) as nested:
            tsmc_meta=json.loads(nested.read('curl/tsmc_2024Q4.pdf.meta.json'))
            tsmc_body=validated_pdf(nested.read('curl/tsmc_2024Q4.pdf'),tsmc_meta)
        archived_config=json.loads(z.read('protocol.json'))['operating_pilot']
    umc_text=PdfReader(io.BytesIO(umc_body)).pages[0].extract_text(extraction_mode='layout')
    tsmc_text=PdfReader(io.BytesIO(tsmc_body)).pages[0].extract_text()
    samples={'2303':dict(extract_umc_text(umc_text),source_sha256=umc_meta['sha256'],source_url=umc_meta['url'],source_page=1),
             '2330':dict(extract_tsmc_text(tsmc_text),source_sha256=tsmc_meta['sha256'],source_url=tsmc_meta['url'],source_page=1)}
    import pandas as pd
    rows=[]
    for issuer in archived_config['issuers']:
        for period in pd.period_range('2023Q1','2025Q4',freq='Q'):
            code=issuer['code'];quarter=str(period);sample=samples[code] if quarter=='2024Q4' else {}
            rows.append(dict(issuer=code,company=issuer['name'],quarter=quarter,gross_margin_pct=sample.get('gross_margin_pct'),
                             eps_twd=sample.get('eps_twd'),revenue_twd_billions=sample.get('revenue_twd_billions'),
                             release_document_sha256=sample.get('source_sha256'),source_url=sample.get('source_url'),source_page=sample.get('source_page'),
                             sec_accepted_at=None,taiwan_first_published_at=None,version_evidence='issuer_pdf_only' if sample else None,
                             status='numeric_source_verified_missing_time_and_sec_version' if sample else 'missing_original_document_and_time',ready_for_model=False))
    with (OUT/'source_ledger.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
    atomic_json(OUT/'extracted_samples.json',dict(issuer_samples=samples,tsmc_guidance=guidance_tsmc(tsmc_text),timing_verified=False))
    atomic_json(OUT/'transport_inventory.json',dict(observations=records,windows_transfer=transfer))
    atomic_json(OUT/'checkpoint.json',dict(package,backup_path=transfer['backup_path'],retrieved_path=str(RETRIEVED),roundtrip_verified=True,crc_verified=True,verified_at=utcnow(),storage='WSL ext4 source -> Windows NTFS user backup -> WSL retrieval; same computer, not off-device disaster recovery'))


def report():
    records=json.loads((OUT/'transport_inventory.json').read_text())['observations']
    with (OUT/'source_ledger.csv').open() as f:rows=list(csv.DictReader(f))
    if len(rows)!=24 or any(row['ready_for_model']!='False' for row in rows):raise ValueError('No model promotion authorized')
    counts={str(status):sum(r['http_status']==status for r in records) for status in sorted({r['http_status'] for r in records})}
    cp=json.loads((OUT/'checkpoint.json').read_text())
    atomic_json(OUT/'summary.json',dict(status='blocked_on_original_sec_and_historical_timing',connected_device='LAPTOP-HQTVA3O0',remote_operational=True,
                windows_remote_requests=len(records),http_counts=counts,issuer_quarters=24,numeric_original_documents=2,missing_original_quarters=22,
                timing_verified_quarters=0,models_fitted=0,evaluation_rows=0,checkpoint_sha256=cp['sha256'],seven_rule_daily_plan='stopped_by_user_no_resume',
                required_external_input='Original SEC complete submissions (.txt) or index + primary 6-K + earnings exhibits + submissions acceptance index for 2330 and 2303, 2024Q4. The issuer PDFs are already available. Keep source URL and original bytes.'))
    (OUT/'report.md').write_text(f'''# Desktop Commander 續作：原文重播與時間證據關卡

已確認裝置LAPTOP-HQTVA3O0上線，Windows命令能存取實際WSL專案。起始本地與遠端main為`3fefca9`且工作目錄乾淨；舊原始包、CRC／manifest及凍結協定雜湊核對通過。未變更研究參數，七規則每日驗證維持停止。

## 本輪來源結果

兩個worker與獨立acquisition.lock執行兩批共{len(records)}個公開來源請求。HTTP結果：`{json.dumps(counts)}`。包含兩家SEC submissions、台積電申報索引、盈餘附件、完整申報文字檔、SEC 2025-01-21每日索引，以及兩家公司2024Q4季報頁。所有回應原文、headers、實際時間、metadata及來源manifest保存在本地。沒有將403 HTML解析為有效申報或索引，沒有改安全政策、代理或讀取瀏覽器帳密。

另檢查本地ref下七個ZIP的目錄與雜湊，沒有符合SEC／2024Q4命名的原文成員；只表示這次具體檢查未找到，未宣稱所有未命名檔案均不存在。官網與搜尋可辨認來源，但解析過的網頁內容／搜尋摘錄不能補成原始HTTP bytes。已知台積電`a4q24e_withguidancexfinal.htm`實際為EX-99.1盈餘附件，不能代替6-K主文件或接受時間索引。

## 可重播資料

從整包取回後，再從兩份既有封存內的原始PDF重播，統一24列來源ledger。數值只有2024Q4：台積電毛利率59.0%、EPS14.45元、合併營收868.46十億元；聯電毛利率30.4%、EPS0.68元、合併營收60.39十億元。其餘22公司季仍缺原文。

另外從台積電同份公告抽出2025Q1毛利率財測區間57%～59%，保留目標季度、來源與不可使用標記；沒有把財測或PDF日期當作已驗證歷史資訊，也沒有計算預測誤差。全部24列SEC接受時間／台灣首次公開時間仍為空、ready_for_model=False。未擬合模型、產生交易訊號或宣稱獲利優勢。

## 封存與恢復

原文、失敗回應、來源manifest、取得程式、協定與兩份既有原始包先打包，再由Desktop Commander複製到Windows使用者專用備份資料夾並取回WSL。整包SHA、所有manifest成員及CRC驗證通過，封存SHA `{cp['sha256']}`。備份路徑見checkpoint.json；跨WSL／Windows檔案系統仍是同一台電腦，不宣稱離機備份。

research_pipeline.py負責package → 等待實際備份取回 → audit → report；僅hash吻合才跳過完成階段。首次執行停在缺少transfer receipt，完成取回後續跑；不是新的使用者批准流程。

## 真正外部依賴

目前阻礙是取得SEC原始版本與可核對的歷史接受時間，不是缺少本機執行權限。不再重試同一批被拒URL。若一般瀏覽器能下載，先提供2330與2303之2024Q4完整SEC申報`.txt`，或索引＋6-K主文件＋盈餘附件＋submissions接受時間索引，放入`inputs/operating_pilot_20261016/incoming/`；另留下載來源URL。兩家公司盈餘PDF已有，不需重傳，也不需提供帳密。完整SEC申報是另一種待核驗原文格式，不預先假定其足以證明台灣首次公告或完整修訂歷程。

資料／時間關卡未通過前，維持兩組驗證範圍，不擴大到其餘22季大量下載或模型比較。歷史歸因與七規則的既有負面結果不因連線恢復而改變。
''')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['package','audit','report']);args=parser.parse_args();globals()[args.stage]()
