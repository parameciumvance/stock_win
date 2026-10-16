"""Replay a user-saved SEC filing index against archived SGML and JSON."""
import argparse
import json
from pathlib import Path
import zipfile
from prospective_sources import verify_archive
from research_runtime import atomic_json, exclusive_lock, sha256, utcnow

ROOT = Path('inputs/operating_pilot_20261016/umc_index_html_20261017')
OUT = Path('deliverables/operating_umc_index_html_20261017')
PROTOCOL = Path('configs/research_reassessment_20261016.json')
FROZEN = 'b939e4271b1e3eca3757d8968a335b9f8902d0a870fbf33fd4b855d25942092b'
EXPECTED = '0fca0852e3d83b13e1131236bbc1fd9a6aa615c6ed12dd42db2382f41264a3ff'
URL = 'https://www.sec.gov/Archives/edgar/data/1033767/000095017025006966/0000950170-25-006966-index.html'
PRIOR = Path('deliverables/operating_umc_sec_import_20261016')


def package():
    source = ROOT/'0000950170-25-006966-index.saved.html'
    meta = json.loads((ROOT/'import.json').read_text())
    if sha256(source) != EXPECTED or meta['sha256'] != EXPECTED or source.stat().st_size != meta['size_bytes']:
        raise ValueError('Saved index bytes drift')
    if meta['zone_host_url'].removeprefix('HostUrl=').rstrip('\x00') != URL:
        raise ValueError('Saved index origin mismatch')
    if sha256(PROTOCOL) != FROZEN:
        raise ValueError('Frozen protocol drift')
    prior = json.loads((PRIOR/'package.json').read_text())
    verify_archive(Path(prior['retrieved']), prior['sha256'])
    state = json.loads((PRIOR/'pipeline_state.json').read_text())
    entries = {'raw/'+source.name:source, 'import.json':ROOT/'import.json', 'protocol.json':PROTOCOL,
               'prior/source.zip':Path(prior['retrieved']), 'prior/package.json':PRIOR/'package.json'}
    for name in ['sec_evidence.json', 'source_ledger.csv', 'clock_reconciliation.json']:
        p = PRIOR/name
        if sha256(p) != state['stages']['audit']['outputs'][str(p)]:
            raise ValueError('Prior audit output drift: '+name)
        entries['prior/'+name] = p
    OUT.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(ROOT.parent/'acquisition.lock'):
        manifest = {name:sha256(p) for name,p in entries.items()}
        archive = ROOT/'source_checkpoint.zip'
        with zipfile.ZipFile(archive.with_suffix('.pending'), 'w') as z:
            for name,p in sorted(entries.items()):
                z.writestr(zipfile.ZipInfo(name, (1980,1,1,0,0,0)), p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
            z.writestr(zipfile.ZipInfo('manifest.json', (1980,1,1,0,0,0)), json.dumps(manifest, sort_keys=True), compress_type=zipfile.ZIP_DEFLATED)
        archive.with_suffix('.pending').replace(archive)
        digest = sha256(archive)
        verify_archive(archive, digest)
        receipt = OUT/'package.json'
        if receipt.exists() and json.loads(receipt.read_text())['sha256'] == digest:
            return
        atomic_json(receipt, dict(archive=str(archive), sha256=digest, manifest_files=len(manifest), created_at=utcnow(),
                    retrieved=str(ROOT/'source_checkpoint.retrieved.zip'), transfer_receipt=str(ROOT/'transfer.json'), backup_label=OUT.name))


def audit():
    import csv
    import hashlib
    import io
    from sec_submission import parse_submission
    from sec_submissions_index import locate_candidates
    from sec_filing_index import parse_filing_index, corroborate_index
    package = json.loads((OUT/'package.json').read_text())
    transfer = json.loads((ROOT/'transfer.json').read_text())
    if transfer.get('sha256') != package['sha256'] or transfer.get('roundtrip_verified') is not True:
        raise ValueError('Missing/mismatched roundtrip transfer')
    verify_archive(Path(package['retrieved']), package['sha256'])
    with zipfile.ZipFile(package['retrieved']) as z:
        body = z.read('raw/0000950170-25-006966-index.saved.html')
        meta = json.loads(z.read('import.json'))
        if hashlib.sha256(body).hexdigest() != EXPECTED or meta['sha256'] != EXPECTED or len(body) != meta['size_bytes']:
            raise ValueError('Archived index drift')
        if meta['zone_host_url'].removeprefix('HostUrl=').rstrip('\x00') != URL:
            raise ValueError('Archived index provenance mismatch')
        if hashlib.sha256(z.read('protocol.json')).hexdigest() != FROZEN:
            raise ValueError('Frozen protocol drift')
        prior = z.read('prior/source.zip')
        if hashlib.sha256(prior).hexdigest() != json.loads(z.read('prior/package.json'))['sha256']:
            raise ValueError('Prior SEC archive drift')
        prior_evidence_bytes = z.read('prior/sec_evidence.json')
        prior_evidence = json.loads(prior_evidence_bytes)
        old_clock = json.loads(z.read('prior/clock_reconciliation.json'))
        rows = list(csv.DictReader(io.StringIO(z.read('prior/source_ledger.csv').decode())))
    def checked_members(data):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.testzip() is not None:
                raise ValueError('Nested archive CRC failure')
            manifest = json.loads(z.read('manifest.json'))
            if set(z.namelist()) != set(manifest) | {'manifest.json'} or len(z.namelist()) != len(set(z.namelist())):
                raise ValueError('Nested archive member mismatch')
            values = {name:z.read(name) for name in manifest}
            if any(hashlib.sha256(values[n]).hexdigest() != digest for n,digest in manifest.items()):
                raise ValueError('Nested archive SHA failure')
            return values
    prior_members = checked_members(prior)
    raw = prior_members['raw/0000950170-25-006966.txt']
    if hashlib.sha256(raw).hexdigest() != prior_evidence['source_sha256']:
        raise ValueError('Prior complete submission drift')
    index_members = checked_members(prior_members['prior/index.zip'])
    candidates = locate_candidates(index_members['raw/CIK0001033767.json'], cik='0001033767', filing_date='2025-01-21')['candidates']
    if len(candidates) != 1 or candidates[0]['accession'] != '0000950170-25-006966':
        raise ValueError('Ambiguous prior JSON candidate')
    candidate = candidates[0]
    submission = parse_submission(raw, cik='0001033767', accession=candidate['accession'], quarter='2024Q4', report_event_date=candidate['report_date_as_reported'])
    submission['source_size_bytes'] = len(raw)
    index = parse_filing_index(body, submission=submission, source_url=URL)
    clock = corroborate_index(index, submission['acceptance'], candidate['acceptanceDateTime_as_reported'])
    if old_clock['sgml_raw'] != clock['sgml_raw'] or old_clock['json_as_reported'] != clock['json_as_reported']:
        raise ValueError('Prior conflicting clocks changed')
    atomic_json(OUT/'index_evidence.json', dict(index=index, clock_reconciliation=clock, source_sha256=EXPECTED, source_url=URL,
        source_import_observed_at=meta['observed_at'], checkpoint_sha256=package['sha256'],
        prior_numeric_evidence_sha256=hashlib.sha256(prior_evidence_bytes).hexdigest(),
        prior_numeric_reconciliation_passed=prior_evidence['numeric_reconciliation_passed'], prior_snapshot_not_rewritten=True, ready_for_model=False))
    if len(rows) != 24 or any(r['ready_for_model'] != 'False' for r in rows):
        raise ValueError('Pilot coverage or readiness drift')
    for row in rows:
        row.update(sec_index_html_sha256='', sec_json_clock_conflict_retained='')
    matches = [r for r in rows if r['issuer'] == '2303' and r['quarter'] == '2024Q4']
    if len(matches) != 1:
        raise ValueError('UMC ledger row not unique')
    matches[0].update(sec_accepted_at=clock['canonical_sec_accepted_at'], sec_clock_status=clock['status'],
        sec_index_html_sha256=EXPECTED, sec_json_clock_conflict_retained=clock['json_conflict_retained'],
        status='sec_snapshot_numeric_and_index_clock_corroborated_full_time_gate_pending')
    with (OUT/'source_ledger.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def report():
    package = json.loads((OUT/'package.json').read_text())
    transfer = json.loads((ROOT/'transfer.json').read_text())
    evidence = json.loads((OUT/'index_evidence.json').read_text())
    clock = evidence['clock_reconciliation']
    verify_archive(Path(package['retrieved']), package['sha256'])
    if transfer['sha256'] != package['sha256'] or transfer.get('roundtrip_verified') is not True:
        raise ValueError('Roundtrip receipt mismatch')
    atomic_json(OUT/'checkpoint.json', dict(package, backup_path=transfer['backup_path'], roundtrip_verified=True, crc_verified=True, verified_at=utcnow()))
    atomic_json(OUT/'summary.json', dict(status=clock['status'], issuer_quarters_with_numeric_original=2,
        issuer_quarters_with_complete_sec_snapshot=2, sec_header_clock_corroborated_quarters=2,
        sec_json_clock_conflict_quarters=1 if clock['json_conflict_retained'] else 0, missing_original_quarters=22,
        full_timing_revision_gate_verified_quarters=0, models_fitted=0, evaluation_rows=0, ready_for_model=False,
        seven_rule_daily_plan='stopped_by_user_no_resume', checkpoint_sha256=package['sha256']))
    atomic_json(OUT/'next_tasks.json', dict(
        completed=['UMC saved index origin, issuer/accession/documents/size verified', 'SGML/index Accepted clocks corroborated', 'JSON discrepancy retained'],
        blocked=[dict(task='Establish historical public availability and version coverage for the two source pilots',
            evidence_available='Original issuer PDFs, complete SEC snapshots, acceptance-clock anchors; only one preserved earnings version per issuer-quarter',
            missing='Historical dissemination/first-release timing evidence and amendment/version coverage; an Accepted timestamp alone does not supply either',
            action='Obtain authoritative historical release metadata/version listing for the existing 2024Q4 releases before scaling acquisition',
            needs_credentials=False)],
        conditional_next='Only after two-issuer source gate passes, acquire remaining 22 quarters under frozen scope; then replay previous-quarter/prior-year/comparable-guidance baselines',
        no_new_download_request_for_existing_files=True))
    (OUT/'report.md').write_text(f'''# 聯電SEC索引HTML：標頭時鐘獲佐證，JSON差異保留

瀏覽器另存HTML已原樣保存：12,186 bytes，SHA `{EXPECTED}`。Zone.Identifier HostUrl與頁內saved-from註解符合指定官方索引URL。這是瀏覽器保存的HTML表示，不宣稱原始HTTP回應bytes；沒有HTTP headers，未執行頁內script或讀取旁邊資源資料夾。

## 時鐘結論

Accepted明示 **2025-01-21 06:03:58**，與完整SGML原值20250121060358一致。CIK、accession、6-K、事件日、三個文件的序號／名稱／類型／URL及完整申報55,016 bytes均對上。

按既有America/New_York解讀，UTC為 **2025-01-21 11:03:58**，台北為 **2025-01-21 19:03:58**。頁內Last-Modified metadata也寫Tue, 21 Jan 2025 11:03:58 GMT，僅記為輔助一致性，不把HTML metadata冒充HTTP header或接受／公告時間。

本輪明示來源優先序：完整申報SGML與另存申報索引兩種表示相符，採其換算作SEC接受時間錨點，不依數值較早／較晚選時間。新ledger填入該錨點，舊衝突快照原樣保留。submissions JSON仍原樣為2025-01-21T16:03:58.000Z，差18000秒；`json_conflict_retained=True`，未改寫JSON或宣稱查明SEC根因。這是接受時間獲佐證，並非三來源完全一致。

SEC接受時間仍不等於公開傳播時間或台灣首次公告。未以本次下載／檔案修改時間回填歷史公開時點；全部24列ready_for_model=False，沒有重啟每日前瞻或建模／績效。

## 封存與重播

先封存HTML、取得紀錄、凍結協定、上一輪完整來源包及證據，再經Windows備份取回；整包SHA／manifest／CRC通過。checkpoint SHA `{package['sha256']}`。備份在Windows使用者研究目錄，取回在WSL，屬同電腦跨檔案系統，不宣稱離機備份。下游僅從取回包解析，重新解析SGML與JSON候選，核對巢狀來源包SHA／CRC／manifest；未修改凍結參數或舊來源。

## 進度與外部依賴

台積電與聯電2024Q4各有官方PDF及完整SEC版本，數值一致，兩組接受時鐘均有索引佐證；聯電JSON的五小時差異仍標記。其餘22季缺原文。既定關卡所需的歷史公開／首次公告時點與版本涵蓋證據尚缺，不能只憑一份快照宣稱完整。先完成這兩組來源可行性，再擴充22季；不需使用者重傳既有檔案。

[下一步清單](next_tasks.json)明列外部證據缺口及擴充條件。七規則252日計畫保持停止；新方向尚無訓練資料集或預測誤差結果。

重播：`.venv/bin/python research_pipeline.py --plan configs/operating_sec_index_import_pipeline.json --state-dir inputs/operating_pilot_20261016/umc_index_html_pipeline`。測試與實際執行時間見[tests.json](tests.json)，階段輸出hash見[pipeline_state.json](pipeline_state.json)。
''')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['package','audit','report'])
    globals()[parser.parse_args().stage]()
