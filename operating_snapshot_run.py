"""Automated current-vintage panel, separate from frozen strict PIT research."""
import argparse
import json
from pathlib import Path
import zipfile
from research_runtime import atomic_json,exclusive_lock,sha256
from prospective_sources import verify_archive
from source_checkpoint import package_sources,readback

ROOT=Path('inputs/operating_replan_20261018')
OUT=Path('deliverables/operating_replan_20261018')
POLICY=Path('configs/operating_snapshot_protocol_20261018.json')
OLD=Path('configs/research_reassessment_20261016.json')
OVERRIDES=Path('configs/operating_pdf_discovery_overrides_20261018.json')


def policy():
    if sha256(POLICY)!='05ab2445ac9ff35be9f63640bf8399384903135b83325f81ec629119fb9fb5b7':raise ValueError('Frozen snapshot protocol drift')
    p=json.loads(POLICY.read_text())
    if sha256(OLD)!=p['original_protocol_sha256']:raise ValueError('Frozen original protocol drift')
    return p


def package(tag):
    policy();entries={'new_protocol.json':POLICY,'old_protocol.json':OLD}
    config=Path('configs/operating_blocker_probes_20261018.json') if tag=='probe' else ROOT/(tag+'_requests.json')
    cfg=json.loads(config.read_text());folder=Path(cfg['output_directory']);result=json.loads((folder/'results.json').read_text())
    if result['config_sha256']!=sha256(config) or result['workers']!=2:raise ValueError('Request configuration drift')
    if [r['request'] for r in result['requests']]!=cfg['requests']:raise ValueError('Unexpected request list')
    entries['request_config.json']=config
    for r in result['requests']:
        name=r['request']['filename'];meta=folder/(name+'.meta.json')
        if json.loads(meta.read_text())!=r:raise ValueError('Request metadata differs')
        if 'sha256' in r and sha256(folder/name)!=r['sha256']:raise ValueError('Source response drift')
    for f in folder.iterdir():
        if f.is_file() and f.name!='acquisition.lock':entries['raw/'+f.name]=f
    if tag=='pdf':
        for t in ['probe','pages']:
            p,_=readback(OUT,t);entries['prior/'+t+'.zip']=Path(p['retrieved']);entries['prior/'+t+'_package.json']=OUT/(t+'_package.json')
        for label,rpath,key in [('umc','deliverables/operating_pilot_20261016/checkpoint.json','retrieved_path'),('tsmc','deliverables/operating_sec_import_20261016/package.json','retrieved')]:
            receipt=json.loads(Path(rpath).read_text());verify_archive(Path(receipt[key]),receipt['sha256'])
            entries['prior/'+label+'.zip']=Path(receipt[key]);entries['prior/'+label+'_receipt.json']=Path(rpath)
        entries['selected_sources.json']=ROOT/'selected_sources.json'
        entries['discovery_overrides.json']=OVERRIDES
    with exclusive_lock(ROOT/'acquisition.lock'):package_sources(ROOT,OUT,tag,entries)


def discover():
    from html.parser import HTMLParser
    from urllib.parse import urljoin
    p=policy();sources=[]
    class Links(HTMLParser):
        def __init__(self):super().__init__();self.links=[]
        def handle_starttag(self,tag,attrs):
            if tag=='a':self.links.append(dict(attrs).get('href',''))
    archives={t:readback(OUT,t)[0] for t in ['probe','pages']}
    for q in p['quarters']:
        if q=='2024Q4':
            for issuer in p['issuers']:sources.append(dict(issuer=issuer,quarter=q,kind='frozen_reuse',source='prior/'+('umc' if issuer=='2303' else 'tsmc')+'.zip'))
            continue
        year,quarter=int(q[:4]),int(q[-1])
        sources.append(dict(issuer='2303',quarter=q,kind='download',filename='umc_'+q+'.pdf',url=f'https://www.umc.com/upload/media/08_Investors/Financials/Quarterly_Results/Quarterly_2020-2029_English_pdf/{year}/Q{quarter}_{year}/UMC{year%100:02d}Q{quarter}_report.pdf'))
        tag='probe' if q=='2023Q1' else 'pages';name='tsmc_discovery.html' if tag=='probe' else 'tsmc_'+q+'.html'
        with zipfile.ZipFile(archives[tag]['retrieved']) as z:
            records=json.loads(z.read('raw/results.json'))['requests'];record=next(r for r in records if r['request']['filename']==name)
            if record['http_status']==200:
                body=z.read('raw/'+name).decode();links=Links();links.feed(body)
                candidates=sorted(set(urljoin(record['request']['url'],link) for link in links.links if f'{quarter}Q{year%100:02d}EarningsRelease' in link and link.endswith('.pdf')))
            else:
                override=json.loads(OVERRIDES.read_text()).get(q)
                if not override or override['page_url']!=record['request']['url']:raise ValueError('Official TSMC page unavailable with no verified URL discovery: '+q)
                candidates=[override['pdf_url']]
            if len(candidates)!=1:raise ValueError('Missing/ambiguous official earnings PDF: '+q+repr(candidates))
            sources.append(dict(issuer='2330',quarter=q,kind='download',filename='tsmc_'+q+'.pdf',url=candidates[0],discovery_page=record['request']['url'],discovery_page_response_sha256=record['sha256'],discovery_method='raw_official_html' if record['http_status']==200 else 'web_parsed_official_link_explicit_override'))
    if len(sources)!=24:raise ValueError('Incomplete fixed cohort')
    atomic_json(ROOT/'selected_sources.json',sources)
    atomic_json(ROOT/'pdf_requests.json',dict(output_directory=str(ROOT/'pdf'),allowed_hosts=['www.umc.com','investor.tsmc.com'],requests=[{k:s[k] for k in ['filename','url']} for s in sources if s['kind']=='download']))


def package_final():
    policy();prior,_=readback(OUT,'pdf');cfg=ROOT/'fallback_requests.json';result=json.loads((ROOT/'fallback/results.json').read_text())
    if result['config_sha256']!=sha256(cfg) or result['workers']!=2:raise ValueError('Fallback acquisition drift')
    entries={'new_protocol.json':POLICY,'old_protocol.json':OLD,'prior/pdf.zip':Path(prior['retrieved']),'prior/pdf_package.json':OUT/'pdf_package.json','fallback_policy.json':Path('configs/operating_source_fallback_20261018.json'),'fallback_requests.json':cfg}
    for f in (ROOT/'fallback').iterdir():
        if f.is_file() and f.name!='acquisition.lock':entries['fallback/'+f.name]=f
    with exclusive_lock(ROOT/'acquisition.lock'):package_sources(ROOT,OUT,'final',entries)


def audit():
    import csv,hashlib,io
    from pypdf import PdfReader
    from operating_snapshot import extract_financials,extract_guidance,arithmetic
    p=policy();receipt,_=readback(OUT,'final')
    def members(data):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.testzip() is not None:raise ValueError('Nested archive CRC failure')
            manifest=json.loads(z.read('manifest.json'))
            if set(z.namelist())!=set(manifest)|{'manifest.json'} or len(z.namelist())!=len(set(z.namelist())):raise ValueError('Nested manifest members mismatch')
            result={n:z.read(n) for n in manifest}
            if any(hashlib.sha256(result[n]).hexdigest()!=digest for n,digest in manifest.items()):raise ValueError('Nested manifest hash mismatch')
            return result
    top=members(Path(receipt['retrieved']).read_bytes())
    if hashlib.sha256(top['new_protocol.json']).hexdigest()!=sha256(POLICY):raise ValueError('Snapshot protocol drift')
    expected=json.loads(top['prior/pdf_package.json'])['sha256']
    if hashlib.sha256(top['prior/pdf.zip']).hexdigest()!=expected:raise ValueError('PDF package drift')
    pack=members(top['prior/pdf.zip']);selected=json.loads(pack['selected_sources.json'])
    if json.loads(pack['new_protocol.json'])!=p:raise ValueError('Panel source cohort protocol mismatch')
    results=json.loads(pack['raw/results.json']);records={r['request']['filename']:r for r in results['requests']}
    fallback=json.loads(top['fallback/results.json'])['requests'][0]
    inventory=[];panel=[]
    for source in selected:
        issuer,q=source['issuer'],source['quarter'];management=False
        row=dict(issuer=issuer,quarter=q,gross_margin_pct=None,eps_twd=None,revenue_twd_billions=None,ready_for_historical_model=False,accounting_standard_explicit=False,status='missing')
        if source['kind']=='frozen_reuse':
            rawpack=members(pack[source['source']])
            if issuer=='2303':
                pdf=rawpack['raw/umc_2024Q4_official.pdf'];meta=json.loads(rawpack['raw/umc_2024Q4_official.pdf.meta.json']);url=meta['url']
            else:
                # The SEC archive contains the original Windows PDF checkpoint, not a new download.
                remote=members(rawpack['prior/source_archive.zip'])
                windowspack=members(remote['prior/tsmc.zip'])
                pdf=windowspack['curl/tsmc_2024Q4.pdf'];meta=json.loads(windowspack['curl/tsmc_2024Q4.pdf.meta.json']);url=meta['url']
            expected=meta['sha256'];observed=meta.get('observed_at')
        else:
            record=records[source['filename']];meta=record;url=source['url'];observed=record['observed_at']
            if record['http_status']!=200:
                if (issuer,q)==('2330','2023Q2') and fallback['http_status']==200:
                    pdf=top['fallback/tsmc_2023Q2_management.pdf'];meta=fallback;url=fallback['request']['url'];observed=fallback['observed_at'];management=True
                else:
                    row['status']='source_unavailable';panel.append(row);inventory.append(dict(source=source,http_status=record['http_status'],parsed=False));continue
            else:pdf=pack['raw/'+source['filename']]
            expected=meta['sha256']
        if hashlib.sha256(pdf).hexdigest()!=expected or not pdf.startswith(b'%PDF-'):raise ValueError('PDF bytes/type mismatch')
        reader=PdfReader(io.BytesIO(pdf));texts=[page.extract_text() for page in reader.pages]
        try:
            values=extract_financials(texts[0],issuer=issuer,quarter=q,management=management)
        except ValueError as e:
            row.update(status='parse_or_basis_gap',source_sha256=expected,source_url=url,error=str(e));panel.append(row);inventory.append(dict(source=source,parsed=False,error=str(e),sha256=expected));continue
        guidance=extract_guidance('\n'.join(texts),issuer,q)
        row.update(values,status='numeric_snapshot_only_basis_unstated' if management else 'numeric_snapshot_only',source_sha256=expected,source_url=url,source_page=1,source_observed_at=observed,source_kind='management_report_fallback' if management else source['kind'],guidance_json=json.dumps(guidance,sort_keys=True))
        panel.append(row);inventory.append(dict(issuer=issuer,quarter=q,sha256=expected,url=url,pages=len(reader.pages),parsed=True,source_kind=row['source_kind'],accounting_standard_explicit=values['accounting_standard_explicit']))
    if len(panel)!=24:raise ValueError('Fixed cohort changed')
    errors,summary=arithmetic(panel,p)
    fields=list(dict.fromkeys(k for row in panel for k in row))
    with (OUT/'panel.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(sorted(panel,key=lambda r:(r['issuer'],r['quarter'])))
    with (OUT/'arithmetic_errors.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(errors[0]) if errors else ['issuer','target_quarter'],lineterminator='\n');writer.writeheader();writer.writerows(errors)
    atomic_json(OUT/'arithmetic_summary.json',dict(summary,quarter_rows=len(panel),numeric_rows=sum(r.get('gross_margin_pct') is not None for r in panel),full_source_gate_passed=False,checkpoint_sha256=receipt['sha256']))
    atomic_json(OUT/'source_inventory.json',dict(records=inventory,gaps=[r for r in panel if r.get('gross_margin_pct') is None],current_vintage_only=True))
    probes=members(pack['prior/probe.zip']);probe_results=json.loads(probes['raw/results.json']);diagnosis=[]
    for r in probe_results['requests']:
        name=r['request']['filename'];body=probes.get('raw/'+name,b'');security=b'THIS PAGE CAN NOT BE ACCESSED' in body
        diagnosis.append(dict(filename=name,url=r['request']['url'],http_status=r['http_status'],size_bytes=len(body),semantic_security_denial=security,usable_original=bool(r['http_status']==200 and not security and name=='tsmc_discovery.html'),sha256=r.get('sha256')))
    atomic_json(OUT/'blocker_diagnosis.json',dict(actual_requests=diagnosis,origin_root_cause='Not established; do not infer account/IP/browser-session causes from status codes',method_problem='A low-cost quarterly source pilot became coupled to exact first disclosure/full revision reconstruction and repeated manual-file requests before testing extraction coverage.',strict_pit_route='Stopped this acquisition attempt, gate remains unpassed',replacement='Automated official as-retrieved quarterly snapshots plus explicitly retrospective arithmetic; never re-label as strict PIT',manual_download_requests=0,seven_rule_daily_plan='stopped_by_user_no_resume'))


def report():
    from research_runtime import utcnow
    r,t=readback(OUT,'final');summary=json.loads((OUT/'arithmetic_summary.json').read_text());inventory=json.loads((OUT/'source_inventory.json').read_text())
    atomic_json(OUT/'checkpoint.json',dict(r,backup_path=t['backup_path'],roundtrip_verified=True,crc_verified=True,verified_at=utcnow()))
    atomic_json(OUT/'next_tasks.json',dict(status='automated_snapshot_pilot_completed' if summary['numeric_rows']==24 else 'automated_snapshot_pilot_partial_stop_no_manual_download_loop',manual_download_requests=[],strict_historical_time_gate='not_passed_preserved',
        done=['automated official acquisition and source archival','fixed cohort numeric replay and arithmetic baselines','specific security-denial and 403 diagnosis'],
        next='Use the retained panel as a reproducible company-research/data-extraction tool; any forecast-skill claim needs a separately frozen model and independent point-in-time or future observations, no year-long manual plan',
        dependencies_for_this_completed_snapshot_run=[],remaining_scientific_limits=['Tiny two-issuer sample','Current-vintage/revision uncertainty','One management source lacks explicit accounting-standard wording','No fitted model or out-of-sample proof'],seven_rule_daily_plan='stopped_by_user_no_resume'))
    table='\n'.join(f"| {x['issuer']} | {x['method']} | {x['paired_targets']} | {x['mae_pp']:.3f} | {x['median_ae_pp']:.3f} |" for x in summary['results'] if x['mae_pp'] is not None)
    (OUT/'report.md').write_text(f'''# 自動化來源方案替換與本次取得版本試點

本輪依使用者2026-10-18指示，停止反覆要求手動下載。原嚴格時點研究協定及來源未變更；新增獨立協定`configs/operating_snapshot_protocol_20261018.json`，同樣固定2330／2303、2023Q1～2025Q4各12季與上一季／去年同季基準，沒有調參或新模型。

## 阻礙的實際原因與界線

MOPS兩個有界POST均回HTTP200、800 bytes，但本文明示因安全性考量無法呈現，故是內容層拒絕而非成功公告。SEC聯電後續原文仍403。這些是實際觀察，沒有證據判斷是帳號、IP、機器人偵測或網站永久故障；也沒有進行驗證碼繞過或讀取瀏覽器憑證。原工具可操作命令／檔案，並不提供瀏覽器GUI點擊。

另一個問題是研究流程：在尚未測試24季數值資料能否低成本取得前，就把季度來源試點綁在精確首次公開與完整修訂重建，再逐份請使用者補檔。這不符合低成本篩選目的。本輪保留該嚴格研究的未通過狀態，停止這條取得嘗試，改做目的不同、標示清楚的本次取得版本資料試點；不以降級資料冒充PIT通過。

## 已實際完成的替代方案

由可取得的官方季報頁自動解析PDF連結；一個頁面403時，以web工具讀取同一官方頁的連結並明示記錄URL發現方式，不把web解析當原始HTML或數值輸入。22份新盈餘PDF請求中21份200、1份403；兩份已驗證2024Q4 PDF從凍結checkpoint重用。台積電2023Q2另使用同頁明列的官方管理報告，一次請求200；保留不同來源標記，不重試被拒URL。

成功取得的原文、headers、失敗回應、取得時間、來源配置、新舊協定與舊checkpoint均先封存、Windows備份取回，SHA／manifest／CRC通過後才解析。最終包SHA `{r['sha256']}`。同電腦跨Windows／WSL檔案系統備份，非離機備份。大型原始資料不進Git。

固定24列中重播出 **{summary['numeric_rows']}列數值**，涵蓋2023Q1～2025Q4。主要目標為合併毛利率；EPS與新台幣十億元營收作數值及單位核對。台積電2023Q2管理報告明示合併，但未明示TIFRS，因此該欄位保留未知，不能宣稱24列全部會計準則驗證通過。計算明列哪些目標／基準涉及這一列；所有ready_for_historical_model=False。

## 簡單基準的回顧算術（不是歷史可交易預測驗證）

| 公司 | 基準 | 共同目標數 | MAE（百分點） | 中位絕對誤差（百分點） |
|---|---|---:|---:|---:|
{table}

目標固定2024Q1～2025Q4，兩基準使用相同列；不插補缺季、不依結果選公司／期間。這些數字只描述本次取得版本序列的變動尺度，可能受後來版本影響；不是獨立留出、PIT預測能力或股票獲利證據。未擬合模型。管理層區間／下界及條件另存原文或結構欄位，不自行取中點，不混進點預測MAE。

## 後續工作方式

此次自動來源試點不再依賴使用者補檔，舊的手動下載待辦已由本決定取代。保存的panel與來源索引可作可稽核公司研究工具，先評估自動擷取／資料覆蓋的實用性。若另做預測能力研究，必須新定義模型、資訊截點與獨立評估；本輪算術不支持直接升級成模型或投入一年每日人工驗證。七規則每日計畫保持停止，沒有新有效前瞻訊號、交易或績效宣稱。

見[來源盤點](source_inventory.json)、[逐列誤差](arithmetic_errors.csv)、[阻礙紀錄](blocker_diagnosis.json)、[下一步](next_tasks.json)、[測試](tests.json)與[pipeline hashes](pipeline_state.json)。
''')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage');a=parser.parse_args()
    if a.stage=='package_final':package_final()
    elif a.stage.startswith('package_'):package(a.stage.removeprefix('package_'))
    else:globals()[a.stage]()
