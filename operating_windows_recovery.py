"""Replay a bounded Windows transport recovery from archived original responses."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import zipfile

from prospective_sources import verify_archive
from research_runtime import atomic_json, exclusive_lock, sha256, utcnow

ROOT=Path('inputs/operating_pilot_20261016/windows_probe_20261016')
OUT=Path('deliverables/operating_windows_recovery_20261016')
CONFIG=Path('configs/research_reassessment_20261016.json')
PDF='curl/tsmc_2024Q4.pdf'
URL='https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2025-01/cc4e1dec3474f69109d5455fbf8939c3e3cd5a71/4Q24EarningsRelease.pdf'


def validated_pdf(body, metadata):
    if metadata.get('exit_code')!=0 or metadata.get('curl',{}).get('http_code')!=200:
        raise ValueError('Response is not a successful source acquisition')
    if metadata.get('url')!=URL or metadata['curl'].get('url_effective')!=URL:
        raise ValueError('Unexpected issuer document URL')
    if hashlib.sha256(body).hexdigest()!=metadata.get('sha256') or len(body)!=metadata.get('size_bytes'):
        raise ValueError('Original response hash/size mismatch')
    if not body.startswith(b'%PDF-'):
        raise ValueError('Expected original PDF, not HTML/error body')
    return body


def extract_tsmc_text(text):
    text=' '.join(text.split())
    if not all(s in text for s in ['fourth quarter ended December 31, 2024','January 16, 2025','TSMC','TIFRS','consolidated']):
        raise ValueError('Issuer/period/date/accounting basis not confirmed')
    def unique(pattern):
        values=re.findall(pattern,text)
        if len(set(values))!=1:raise ValueError('Missing or conflicting financial value')
        return float(values[0])
    margin=unique(r'Gross margin for the quarter was ([\d.]+)%')
    revenue=unique(r'consolidated revenue of NT\$([\d.]+) billion')
    eps=unique(r'diluted earnings per share of NT\$([\d.]+)')
    if not 0<=margin<=100 or revenue<=0:raise ValueError('Invalid financial value')
    return dict(gross_margin_pct=margin,revenue_twd_billions=revenue,eps_twd=eps,accounting_basis='TIFRS consolidated')


def checkpoint():
    OUT.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(ROOT.parent/'acquisition.lock'):
        files=[p for p in ROOT.rglob('*') if p.is_file() and p.suffix not in ('.zip','.pending') and 'pipeline' not in p.parts]
        entries={str(p.relative_to(ROOT)):p for p in files}
        entries['frozen_protocol.json']=CONFIG
        manifest={name:sha256(p) for name,p in entries.items()}
        archive=ROOT/'windows_recovery.zip'
        with zipfile.ZipFile(archive.with_suffix('.pending'),'w',zipfile.ZIP_DEFLATED) as z:
            for name,path in sorted(entries.items()):z.write(path,name)
            z.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
        archive.with_suffix('.pending').replace(archive)
        backup=ROOT.parents[1]/'backups'/'operating_pilot_20261016'/'windows_recovery.zip'
        backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(archive,backup)
        retrieved=ROOT/'windows_recovery.retrieved.zip';shutil.copyfile(backup,retrieved)
        digest=sha256(archive);verify_archive(retrieved,digest)
        atomic_json(OUT/'checkpoint.json',dict(sha256=digest,manifest_files=len(manifest),archive=str(archive),backup=str(backup),retrieved=str(retrieved),roundtrip_verified=True,crc_verified=True,protocol_sha256=sha256(CONFIG),verified_at=utcnow(),storage='Local persistent copies on same filesystem; no off-device backup claimed'))


def replay():
    from pypdf import PdfReader
    cp=json.loads((OUT/'checkpoint.json').read_text())
    verify_archive(Path(cp['retrieved']),cp['sha256'])
    with zipfile.ZipFile(cp['retrieved']) as z:
        body=validated_pdf(z.read(PDF),json.loads(z.read(PDF+'.meta.json')))
        meta=json.loads(z.read(PDF+'.meta.json'))
        probes=[json.loads(z.read(name)) for name in z.namelist() if name.endswith('.meta.json') and name.startswith(('curl/','sec_archive/'))]
        if hashlib.sha256(z.read('frozen_protocol.json')).hexdigest()!=cp['protocol_sha256']:
            raise ValueError('Frozen protocol hash mismatch')
    reader=PdfReader(io.BytesIO(body));text=' '.join(reader.pages[0].extract_text().split())
    values=extract_tsmc_text(text)
    atomic_json(OUT/'replay.json',dict(**values,issuer='2330',quarter='2024Q4',source_url=URL,source_sha256=meta['sha256'],source_size_bytes=len(body),request_started_at=meta['request_started_at'],observed_at=meta['observed_at'],visible_release_date='2025-01-16',document_pages=len(reader.pages),source_page=1,sec_accepted_at=None,taiwan_first_published_at=None,ready_for_model=False,raw_retrieval_and_pdf_replay_verified=True,windows_requests=len(probes),http_200=sum(p['curl']['http_code']==200 for p in probes),http_403=sum(p['curl']['http_code']==403 for p in probes),checkpoint_sha256=cp['sha256']))


def report():
    r=json.loads((OUT/'replay.json').read_text())
    atomic_json(OUT/'summary.json',dict(r,status='partial_recovery_sec_time_gate_closed',original_documents_obtained_total=2,issuer_quarters_required=24,issuer_quarters_ready_for_model=0,desktop_commander_device='LAPTOP-HQTVA3O0',desktop_commander_status_observed='offline',desktop_status_note='Connection observation only, not device root-cause diagnosis',can_operate_windows_commands=True,can_operate_desktop_gui=False))
    (OUT/'report.md').write_text(f'''# Windows 本機來源恢復

使用者授權操作電腦後，從 WSL 呼叫 Windows 內建 curl 8.21.0，兩個下載 worker 共用 acquisition.lock。Desktop Commander 裝置 LAPTOP-HQTVA3O0 顯示離線；目前確認能執行 Windows 命令，尚未建立桌面 GUI 操作連線。

原先 Windows PowerShell `.ps1` 受到執行政策拒絕；保留實際錯誤，不變更執行政策。改用內建 curl 成功取得台積電2024Q4官方盈餘公告，HTTP200、{r['source_size_bytes']:,} bytes、SHA256 `{r['source_sha256']}`。實際取得時間 `{r['observed_at']}`，不是歷史公告時刻。

本輪共5個 Windows HTTP 請求，台積電PDF成功，兩家公司SEC submissions及已知台積電6-K原文、索引共4次HTTP403；原始403回應及headers亦保存，不解析為JSON索引或有效申報。本輪只測指定路徑，不能推論所有來源不可取得。

先封存原文、metadata、headers、失敗觀察、取得腳本及凍結協定，再備份取回驗證整包SHA、manifest與CRC，最後才從取回包解析PDF。封存SHA `{r['checkpoint_sha256']}`。備份位於同檔案系統，沒有宣稱已具離機災難恢復。

PDF第1頁確認TSMC、2024Q4及可見日期2025-01-16，並重播毛利率{r['gross_margin_pct']}%、EPS新台幣{r['eps_twd']}元、合併營收新台幣{r['revenue_twd_billions']}十億元，共{r['document_pages']}頁。未以PDF內可見日期、下載時間或HTTP修改時間補造首次公開時刻；SEC接受時間仍空白。此輪沒有財務預測、建模、訊號或績效宣稱。

累計兩家公司2024Q4原始盈餘公告皆已取得，24公司季中仍有22季缺原文，全部仍未通過完整時點／版本驗收。原先[來源試點報告](../operating_pilot_20261016/report.md)是此輪之前的觀察快照。

## 使用者提供電腦的方式

目前已有Windows命令操作通道，無需再給帳密。若要改由Desktop Commander連線，在Windows開啟已安裝的Desktop Commander，登入原帳號並保持程式運作；於 https://mcp.desktopcommander.app/ 確認該裝置Online，再回覆「已上線」。工具連線不等於已有瀏覽器點擊能力；上線後仍須以實際可用工具確認。

若一般瀏覽器可以正常下載SEC文件，也可將原始文件放在 `inputs/operating_pilot_20261016/incoming/`，由後續流程驗證，無需先自行改名、解析或壓縮。本機目前遇到的403是來源取得阻礙，增加操作授權本身不保證解除。
''')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['checkpoint','replay','report']);args=parser.parse_args();globals()[args.stage]()
