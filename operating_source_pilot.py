"""Bounded source-feasibility audit; never fills missing historical release evidence."""
import argparse
import io
import json
from pathlib import Path
import re
import shutil
import zipfile

import numpy as np
import pandas as pd

from prospective_sources import verify_archive
from research_runtime import atomic_json, sha256, utcnow, exclusive_lock

ROOT=Path('inputs/operating_pilot_20261016')
OUT=Path('deliverables/operating_pilot_20261016')
CONFIG=Path('configs/research_reassessment_20261016.json')


def candidate_fields_complete(record):
    """Schema screening only; does not verify raw documents or authorize model use."""
    required=['issuer','quarter','gross_margin_pct','release_document_sha256','version_evidence','sec_accepted_at']
    if any(pd.isna(record.get(k)) or record.get(k)=='' for k in required):
        return False
    if record['version_evidence']!='sec_archived_document_verified':
        return False
    value=float(record['gross_margin_pct'])
    if not np.isfinite(value) or not 0<=value<=100:
        return False
    stamp=pd.Timestamp(record['sec_accepted_at'])
    if stamp.tzinfo is None:
        return False
    digest=record['release_document_sha256']
    return len(digest)==64 and all(c in '0123456789abcdef' for c in digest)


def extract_umc_text(text):
    text=' '.join(text.split())
    if 'UMC Reports Fourth Quarter 2024 Results' not in text or 'TWSE: 2303' not in text or 'TIFRS' not in text:
        raise ValueError('Wrong issuer/quarter/accounting basis')
    def unique(pattern):
        values=re.findall(pattern,text)
        if len(set(values))!=1:
            raise ValueError('Missing or conflicting financial field')
        return float(values[0])
    margin=unique(r'Gross margin:\s*([\d.]+)%')
    eps=unique(r'Earnings per share:\s*NT\$([\d.]+)')
    revenue=unique(r'Revenue:\s*NT\$([\d.]+) billion')
    if 'January 21, 2025' not in text or not 0<=margin<=100:
        raise ValueError('Missing release date or invalid margin')
    return dict(issuer='2303',quarter='2024Q4',gross_margin_pct=margin,eps_twd=eps,
                revenue_twd_billions=revenue,visible_release_date='2025-01-21',
                accounting_basis='TIFRS consolidated as described in the release')


def parse_sample():
    from pypdf import PdfReader
    cp=json.loads((OUT/'checkpoint.json').read_text())
    verify_archive(Path(cp['retrieved_path']),cp['sha256'])
    with zipfile.ZipFile(cp['retrieved_path']) as z:
        body=z.read('raw/umc_2024Q4_report.pdf')
        meta=json.loads(z.read('raw/umc_2024Q4_report.pdf.meta.json'))
        official=z.read('raw/umc_2024Q4_official.pdf')
        official_meta=json.loads(z.read('raw/umc_2024Q4_official.pdf.meta.json'))
    import hashlib
    if hashlib.sha256(body).hexdigest()!=meta['sha256']:
        raise ValueError('Financial PDF source drift')
    if official!=body or hashlib.sha256(official).hexdigest()!=official_meta['sha256']:
        raise ValueError('Issuer official PDF and CDN version differ')
    reader=PdfReader(io.BytesIO(body))
    values=extract_umc_text(reader.pages[0].extract_text(extraction_mode='layout'))
    values.update(source_sha256=meta['sha256'],source_url=meta['url'],source_observed_at=meta['observed_at'],
                  official_source_url=official_meta['url'],official_observed_at=official_meta['observed_at'],official_pdf_matches_saved_cdn=True,
                  source_page=1,document_pages=len(reader.pages),sec_accepted_at=None,
                  taiwan_first_published_at=None,version_evidence='issuer_linked_pdf_not_full_revision_history',
                  ready_for_model=False)
    atomic_json(OUT/'extracted_sample.json',values)


def inventory():
    c=json.loads(CONFIG.read_text())['operating_pilot']
    errors=[]
    for path in sorted((ROOT/'errors').glob('*.json')):
        record=json.loads(path.read_text())
        if record.get('exit_code')!=22 or '403' not in record.get('stderr',''):
            raise ValueError('Unexpected source probe result; review it explicitly')
        errors.append(dict(path=str(path),sha256=sha256(path),**record))
    if not errors:raise ValueError('No actual transport observations found')
    successful=[]
    for path in sorted((ROOT/'raw').glob('*.pdf')):
        meta=json.loads(path.with_name(path.name+'.meta.json').read_text())
        if sha256(path)!=meta['sha256'] or not path.read_bytes().startswith(b'%PDF-'):
            raise ValueError('Raw financial PDF hash/format differs')
        successful.append(dict(file=str(path),**meta))
    rows=[]
    for issuer in c['issuers']:
        for quarter in pd.period_range('2023Q1','2025Q4',freq='Q'):
            rows.append(dict(issuer=issuer['code'],company=issuer['name'],quarter=str(quarter),gross_margin_pct=None,release_document_sha256=None,version_evidence=None,sec_accepted_at=None,taiwan_first_published_at=None,status='missing_original_document_and_time',ready_for_model=False))
    for row in rows:
        if row['issuer']=='2303' and row['quarter']=='2024Q4' and successful:
            sample=next(doc for doc in successful if Path(doc['file']).name=='umc_2024Q4_report.pdf')
            row.update(release_document_sha256=sample['sha256'],version_evidence='issuer_dated_pdf_pending_time_validation',status='raw_document_obtained_missing_publication_evidence')
    OUT.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT/'source_ledger.csv',index=False)
    atomic_json(OUT/'transport_inventory.json',dict(records=errors,successful_documents=successful,recorded_at=utcnow(),user_agent_retry='A separate direct SEC submissions retry using project-identifying User-Agent also returned curl exit22 HTTP403; exact request time was not retained, so no historical request timestamp is invented'))
    atomic_json(ROOT/'acquisition.json',dict(status='partial_documents_missing_time_evidence',observed_at=utcnow(),config_sha256=sha256(CONFIG),official_source_successes=len({d['sha256'] for d in successful}),successful_source_routes=len(successful),recorded_failed_requests=len(errors),required_quarters=len(rows),source_rows_ready=0,can_fit_model=False,source_gate='closed',additional_network_retries=False))


def checkpoint():
    with exclusive_lock(ROOT/'acquisition.lock'):
        files=sorted((ROOT/'raw').glob('*'))+sorted((ROOT/'errors').glob('*.json'))+[ROOT/'acquisition.json',CONFIG,OUT/'transport_inventory.json',OUT/'source_ledger.csv']
        # Keys are logical package names; error observations are not official source bodies.
        entries={(p.parent.name+'/'+p.name if p.parent.name in ('errors','raw') else p.name):p for p in files}
        if len(entries)!=len(files):raise ValueError('Duplicate checkpoint name')
        manifest={name:sha256(p) for name,p in entries.items()}
        archive=ROOT/'source_probe_checkpoint.zip'
        with zipfile.ZipFile(archive.with_suffix('.pending'),'w',zipfile.ZIP_DEFLATED) as z:
            for name,p in entries.items():z.write(p,name)
            z.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
        archive.with_suffix('.pending').replace(archive)
        backup=ROOT.parent/'backups'/ROOT.name/archive.name;backup.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(archive,backup)
        retrieved=ROOT/'source_probe_checkpoint.retrieved.zip';shutil.copyfile(backup,retrieved)
        digest=sha256(archive);verify_archive(retrieved,digest)
        atomic_json(OUT/'checkpoint.json',dict(sha256=digest,manifest_files=len(manifest),backup_path=str(backup),retrieved_path=str(retrieved),roundtrip_verified=True,crc_verified=True,verified_at=utcnow(),content='Transport errors, saved UMC quarterly PDF versions and metadata, config and incomplete source ledger',storage='local persistent copy; same filesystem'))


def report():
    acquisition=json.loads((ROOT/'acquisition.json').read_text())
    cp=json.loads((OUT/'checkpoint.json').read_text())
    verify_archive(Path(cp['retrieved_path']),cp['sha256'])
    ledger=pd.read_csv(OUT/'source_ledger.csv',dtype={'issuer':str})
    if any(candidate_fields_complete(r) for r in ledger.to_dict('records')) or len(ledger)!=24:
        raise ValueError('Unexpected source ledger; no automatic model promotion')
    sample=json.loads((OUT/'extracted_sample.json').read_text())
    atomic_json(OUT/'summary.json',dict(acquisition,checkpoint_sha256=cp['sha256'],status='source_pilot_blocked',numeric_sample=sample,request_to_continue='Provide original issuer quarterly earnings release/report plus its SEC 6-K document and acceptance-time index. Start with 2024Q4 for 2330 and 2303; UMC issuer PDF already saved; verify time/version routes before collecting remaining issuer-quarters.',limitations=['No Taiwan first-publication timestamps inferred','Search identifies official routes; only actual saved source bodies enter raw evidence','No financial forecasts, trained model, stock signals or return claims produced']))
    (OUT/'report.md').write_text('''# 營運預測來源試點：來源關卡未通過

固定選擇台積電2330、聯電2303兩家晶圓代工公司，理由是會計營運口徑相近且有官方季報與SEC申報路徑，並非根據股價表現挑選。範圍為2023Q1～2025Q4、每家連續12季，共24個公司季。

目標固定為下一季合併毛利率；先比較上一季、去年同季及可比公司財測等簡單基準。本輪只是來源工程試點，不在最多16個可配對預測目標上訓練高維機器學習模型。若原始版本／時間不完整，停止於資料關卡，不放寬成目前網站或靜態表代理。

## 實際結果

已保存8個有時間／URL的HTTP403錯誤觀察：兩份SEC公司submissions索引、已知台積電6-K原文、台積電IR季報頁與版本化PDF、聯電IR季報頁、台積電新聞稿獨立網域的歷史索引與單篇新聞稿。另一次明示專案User-Agent的SEC重試同為403，但未保留該次精確請求時刻，不補造時間。

聯電季報的官網直接PDF及備援CDN均成功取得2024Q4原文，兩路SHA完全相同，計為一份獨立文件；其餘23個公司季尚未取得原文。全24季仍缺完整歷史時點／版本證據；沒有公告時點／版本驗收通過列，也沒有計算營運預測誤差或擬合模型。這些錯誤是本輪具體請求結果，不推論所有使用者或所有官方來源永久不可取得，不歸因OOM／配額／網站根因。

錯誤觀察、協定及缺口ledger已打包到本地持久化目錄，備份後另檔取回，整包SHA／成員hash／CRC通過。封存內容含一份聯電原始PDF、取得metadata、失敗觀察及缺口。來源位置可由官方搜尋核對，但網頁搜尋摘錄不冒充原始文件。

從取回包內PDF第1頁獨立解析：聯電2024Q4合併毛利率30.4%、EPS新台幣0.68元、營收新台幣603.9億元，原文可見發布日期2025-01-21。逐欄輸出保留原始SHA、來源頁碼及實際取得時間，見`extracted_sample.json`。可見日期沒有填成精確首次公告時刻，SEC接受時間仍為空，不視為通過建模資料關卡。

## 下一個真正依賴

若要繼續，需要能取得原始文件的傳輸路徑，或原始公司季報／盈餘公告與對應SEC 6-K原文、接受時間索引。先用2330與2303的2024Q4各一組補齊原始公告與SEC時點（聯電PDF已有）驗證路徑，再補其餘公司季；不要求先提供整個24季資料包。不需交易帳號或券商憑證。SEC接受時間另記，不能填成台灣首次公開時間，修訂歷程仍需獨立查核。
''')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['inventory','checkpoint','parse_sample','report']);a=p.parse_args();globals()[a.stage]()
