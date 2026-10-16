"""Preserve a user-supplied UMC index before candidate discovery and source probes."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from prospective_sources import verify_archive
from research_runtime import atomic_json,exclusive_lock,sha256,utcnow
from sec_submissions_index import locate_candidates

ROOT=Path('inputs/operating_pilot_20261016/umc_index_20261016')
OUT=Path('deliverables/operating_umc_locator_20261016')
PROTOCOL=Path('configs/research_reassessment_20261016.json')
SOURCE='https://data.sec.gov/submissions/CIK0001033767.json'
EXPECTED='c63c1f0e8187cf01dcd59d0aabd1e676f073e117023e30cadd94016016d50a7c'
FROZEN='b939e4271b1e3eca3757d8968a335b9f8902d0a870fbf33fd4b855d25942092b'


def make_package(tag,entries):
    if sha256(PROTOCOL)!=FROZEN:raise ValueError('Frozen pilot protocol drift')
    OUT.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(ROOT.parent/'acquisition.lock'):
        entries={**entries,'protocol.json':PROTOCOL}
        manifest={name:sha256(p) for name,p in entries.items()}
        archive=ROOT/(tag+'_checkpoint.zip')
        with zipfile.ZipFile(archive.with_suffix('.pending'),'w',zipfile.ZIP_DEFLATED) as z:
            # Source bytes determine the archive, never mutable filesystem mtimes.
            for name,p in sorted(entries.items()):
                z.writestr(zipfile.ZipInfo(name,(1980,1,1,0,0,0)),p.read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
            z.writestr(zipfile.ZipInfo('manifest.json',(1980,1,1,0,0,0)),json.dumps(manifest,sort_keys=True),compress_type=zipfile.ZIP_DEFLATED)
        archive.with_suffix('.pending').replace(archive)
        digest=sha256(archive);verify_archive(archive,digest)
        receipt=OUT/(tag+'_package.json')
        if receipt.exists() and json.loads(receipt.read_text()).get('sha256')==digest:return
        atomic_json(receipt,dict(archive=str(archive),sha256=digest,manifest_files=len(manifest),created_at=utcnow(),
                    retrieved=str(ROOT/(tag+'_checkpoint.retrieved.zip')),transfer_receipt=str(ROOT/(tag+'_transfer.json')),backup_label='operating_umc_'+tag+'_20261016'))


def verified_package(tag):
    package=json.loads((OUT/(tag+'_package.json')).read_text());transfer=json.loads(Path(package['transfer_receipt']).read_text())
    if transfer['sha256']!=package['sha256'] or transfer.get('roundtrip_verified') is not True:raise ValueError('Stale transfer receipt')
    verify_archive(Path(package['retrieved']),package['sha256'])
    return package,transfer


def package_index():
    source=ROOT/'CIK0001033767.json';meta=json.loads((ROOT/'import.json').read_text())
    if sha256(source)!=EXPECTED or meta['sha256']!=EXPECTED or source.stat().st_size!=meta['size_bytes']:raise ValueError('Imported index hash/size mismatch')
    if meta.get('zone_host_url','').removeprefix('HostUrl=').rstrip('\x00')!=SOURCE:raise ValueError('Download origin mismatch')
    make_package('index',{'raw/CIK0001033767.json':source,'import.json':ROOT/'import.json'})


def locate():
    package,_=verified_package('index')
    with zipfile.ZipFile(package['retrieved']) as z:
        body=z.read('raw/CIK0001033767.json')
        if hashlib.sha256(body).hexdigest()!=EXPECTED:raise ValueError('Index bytes drift')
        result=locate_candidates(body,cik='0001033767',filing_date='2025-01-21')
    result.update(source_sha256=EXPECTED,source_url=SOURCE,checkpoint_sha256=package['sha256'])
    atomic_json(OUT/'candidates.json',result)
    # Every matched filing remains a candidate until its original earnings exhibit is checked.
    if not 1<=len(result['candidates'])<=2:raise ValueError('Zero or too many candidates; review archived coverage/ambiguity before acquisition')
    requests=[]
    for i,candidate in enumerate(result['candidates']):
        requests.extend([dict(filename=f'candidate_{i}_complete.body',url=candidate['complete_submission_url']),dict(filename=f'candidate_{i}_index.body',url=candidate['index_url'])])
    atomic_json(ROOT/'candidate_requests.json',dict(output_directory=str(ROOT/'candidate_probe'),requests=requests))


def package_probe():
    package,_=verified_package('index')
    entries={'index/source_archive.zip':Path(package['retrieved']),'index/package.json':OUT/'index_package.json',
             'candidate_requests.json':ROOT/'candidate_requests.json','candidates.json':OUT/'candidates.json'}
    for p in (ROOT/'candidate_probe').iterdir():
        if p.is_file() and p.name!='acquisition.lock':entries['probe/'+p.name]=p
    make_package('probe',entries)


def report():
    package,transfer=verified_package('probe')
    with zipfile.ZipFile(package['retrieved']) as z:
        candidates=json.loads(z.read('candidates.json'));requests=json.loads(z.read('candidate_requests.json'))
        result=json.loads(z.read('probe/results.json'))
        if hashlib.sha256(z.read('candidate_requests.json')).hexdigest()!=result['config_sha256']:raise ValueError('Probe source manifest drift')
        if result['workers']!=2 or sorted((r['filename'],r['url']) for r in result['requests'])!=sorted((r['filename'],r['url']) for r in requests['requests']):raise ValueError('Missing/duplicate source probe')
        probes=[]
        for row in result['requests']:
            meta=json.loads(z.read('probe/'+row['filename']+'.meta.json'));body=z.read('probe/'+row['filename'])
            if row!=meta or hashlib.sha256(body).hexdigest()!=meta['sha256'] or len(body)!=meta['size_bytes']:raise ValueError('Probe response hash/metadata mismatch')
            probes.append({k:meta.get(k) for k in ['filename','url','http_status','sha256','size_bytes','request_started_at','observed_at','transport']})
    atomic_json(OUT/'transport_inventory.json',dict(records=probes))
    available=any(r['http_status']==200 and r['filename'].endswith('_complete.body') for r in probes)
    atomic_json(OUT/'checkpoint.json',dict(package,backup_path=transfer['backup_path'],roundtrip_verified=True,crc_verified=True,verified_at=utcnow()))
    atomic_json(OUT/'summary.json',dict(status='candidate_original_obtained_pending_audit' if available else 'umc_candidate_located_original_download_blocked',
                index_verified=True,index_source_sha256=EXPECTED,candidates=candidates['candidates'],original_submission_obtained=available,
                sec_time_verified=False,ready_for_model=False,models_fitted=0,seven_rule_daily_plan='stopped_by_user_no_resume',checkpoint_sha256=package['sha256']))
    urls='\n'.join('- [完整申報原文]('+c['complete_submission_url']+')；[申報索引]('+c['index_url']+')；主文件 `'+c['primary_document']+'`。' for c in candidates['candidates'])
    outcomes='、'.join(str(r['http_status']) for r in probes)
    (OUT/'report.md').write_text(f'''# 聯電SEC索引匯入與候選申報定位

使用者提供`CIK0001033767.json`，原樣匯入119,674 bytes，SHA `{EXPECTED}`；Windows來源與WSL保存雜湊一致，Zone.Identifier HostUrl符合官方submissions URL。先封存、Windows備份取回並核驗SHA／manifest／CRC，再讀取索引。未變更凍結研究協定，亦未替換既有原文。

CIK及公司名稱、recent陣列長度及accession唯一性驗收通過；共{candidates['recent_rows']}列，定位2025-01-21的6-K候選{len(candidates['candidates'])}份。這是以已知2024Q4盈餘公告日期定位候選，不是靠索引即宣稱財務季度已驗證；reportDate及acceptanceDateTime原樣保留在candidates.json。尤其JSON的Z標記不直接升為已核實UTC，仍需原始SGML／索引交叉核對。

{urls}

使用Desktop Commander與兩個worker，對候選的完整申報與索引做一次有界下載；實際HTTP結果：{outcomes}。原始回應、headers、時間及雜湊再打包，Windows備份取回、manifest與CRC核對通過。checkpoint SHA `{package['sha256']}`，同電腦不同檔案系統，不宣稱離機備份。HTTP403原文只作錯誤證據，不當成SEC文件。

是否取得可待核驗完整原文：{available}。索引本身不是盈餘附件／6-K原文，也不足以驗證接受時間、首次公開或修訂歷程。已取得數值的公司季仍是兩家公司2024Q4；台積電完整SEC匯入的先前結果維持，聯電仍未通過SEC原文／時間核對，未新增建模資料或計算預測誤差，七規則每日計畫仍停止。

若下載仍被拒，請只將上述候選完整申報`.txt`由一般瀏覽器存到Downloads後提供路徑；聯電PDF、這份JSON與已驗收台積電檔案不需重傳。拿到原文後須核對CIK、主文件與EX附件、實際財務季度及毛利率／EPS／營收，再核對接受時間。
''')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['package_index','locate','package_probe','report']);a=p.parse_args();globals()[a.stage]()
