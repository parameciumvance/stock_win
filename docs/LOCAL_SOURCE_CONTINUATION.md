# 本機 WSL 接續免費來源採集

Work Mode 的執行環境目前發生 transport 斷線，原來源程序是否仍活躍未知。先確認原任務已停止或完成，再啟動第二套採集。以下只下載與驗收既定2018來源，不交易、不調模型。下一年度依序2017、2016、2015。

## 選擇執行位置

- Work Mode 恢復：先查活躍程序與既有鎖、runner state，避免重複啟動。如果行情未完成，沿用 `configs/tpex_2018_source_pipeline.json` 與 `deliverables/tpex_2018_source_run`。行情全年度封存完成並保存取回後，才用 `configs/tpex_2018_resume_from_saved_quotes.json`。
- WSL：使用已登入GitHub的全新 `parameciumvance/stock_win` checkout。以下指令在repo根目錄執行，資料留在自己的本機磁碟；不需要先通過ChatGPT Library封存gate。

現有採集、逐筆重播與打包程式已在Work Mode驗收；下面這條WSL接續路徑尚未在使用者本機執行驗收。網路失敗不是休市，任一校驗失敗就停止。

## 1. 準備 Python

建議Ubuntu 24.04的Python 3.12虛擬環境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements_tpex.txt
```

## 2. 下載並核對已保存快取

[下載2018上半年快取](https://chatgpt.com/api/library/files/libfile_7f3c28b725c88191b79bfa65ee64f0b0/download)

把 `tpex_quotes_2018_partial_01_06_checkpoint.zip` 放到repo根目錄。它含118個日期、90,490筆行情及266個校驗成員；只有月級驗收，尚未完成全年獨立日曆、法人或公司行動。

在全新checkout根目錄執行以下復原步驟；先校驗完整封存與所有成員，再寫入，已存在而不同的檔案會拒絕覆蓋：

```bash
python - <<'PY'
from pathlib import Path, PurePosixPath
import hashlib, json, os, zipfile

archive = Path("tpex_quotes_2018_partial_01_06_checkpoint.zip")
expected = "8ccab520888d3f6d1a506a83a3df72c35391178aab94d73f7d161924060bf5ac"
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise ValueError("Archive SHA-256 mismatch")
manifest_name = "deliverables/tpex_2018/partial_manifest_01_06.json"
pending = []
with zipfile.ZipFile(archive) as z:
    if z.testzip() is not None:
        raise ValueError("ZIP CRC mismatch")
    names = z.namelist()
    manifest = json.loads(z.read(manifest_name))
    if len(manifest) != 266 or len(names) != len(set(names)) or set(names) != set(manifest) | {manifest_name}:
        raise ValueError("Unexpected archive members")
    for name, sha in manifest.items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or path.parts[:2] != ("deliverables", "tpex_2018"):
            raise ValueError("Unexpected destination")
        data = z.read(name)
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError("Member mismatch: " + name)
        dst = Path(name)
        if dst.exists() and dst.read_bytes() != data:
            raise ValueError("Existing data differs: " + name)
        pending.append((dst, data))
for dst, data in pending:
    if dst.exists():
        continue
    dst.parent.mkdir(parents=True, exist_ok=True)
    temporary = dst.with_name(dst.name + ".restoring")
    temporary.write_bytes(data)
    os.replace(temporary, dst)

# Restore the same frozen classification sources; never replace them with today's list.
for name in ("isin.raw", "isin_listed.raw", "unknown_single_query.html"):
    src = Path("deliverables/tpex_2018/classification") / name
    dst = Path("deliverables/tpex_pilot/classification") / name
    data = src.read_bytes()
    if dst.exists():
        if dst.read_bytes() != data:
            raise ValueError("Existing classification differs: " + name)
        continue
    dst.parent.mkdir(parents=True, exist_ok=True)
    temporary = dst.with_name(dst.name + ".restoring")
    temporary.write_bytes(data)
    os.replace(temporary, dst)
print("118 cached dates / 266 members verified and restored")
PY
```

## 3. 依序採集、重播與驗收

下面是本機採集入口，使用本機永久檔案及程式內部完整重播，不填造Library收據。原始快取逐日續抓；任一步失敗就停止。

```bash
set -e
python -u acquire_tpex_year.py --year 2018
python -u acquire_tpex_flow_year.py --year 2018
python -u package_tpex_flow_source.py --year 2018
python -u audit_tpex_event_coverage.py --year 2018
python -u audit_tpex_year_readiness.py --year 2018
```

不要在未完成年度行情時使用「跳過行情」恢復設定。已保存的年度檔不要重製；如果只需要補法人，從第二條採集指令開始。

## 4. 回傳給分析端

完成後回傳這兩份來源包：

- `deliverables/tpex_2018/tpex_raw_type_2018_checkpoint.zip`
- `deliverables/tpex_flow_2018/tpex_institutional_source_2018_checkpoint.zip`

同時提供年度摘要及checkpoints：

- `deliverables/tpex_2018/checkpoint.json`、`annual_verification.json`、`readiness.json`
- `deliverables/tpex_flow_2018/source_checkpoint.json`、`acquisition.json`、`source_replay.json`

分析端會再保存取回、核對SHA／CRC／全部成員，才宣布永久來源驗收完成。完整停牌主檔、原始公告時點PIT、精確現金帳仍待處理；法人缺列與未核實事件保持未知。
