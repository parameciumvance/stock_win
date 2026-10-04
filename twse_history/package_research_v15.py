"""Package v15 cash dividend evidence and existing research."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="outputs/taiwan_stock_research_2025_v14.zip")
    p.add_argument("--spec", required=True)
    p.add_argument("--output", default="outputs/taiwan_stock_research_2025_v15.zip")
    args = p.parse_args()
    root = Path(__file__).parent
    out = root / "output_research_v15"
    result = json.loads((out / "test_results.json").read_text())
    if result["tests_run"] < 64 or result["failures"] or result["errors"]:
        raise ValueError("Tests missing or failing")
    new = {f"twse_history/{name}": root / name for name in (
        "raw_replay_v15.py", "test_raw_replay_v15.py", "paid_rights_evidence_v15.csv", "dividend_evidence_v15.csv", "dividend_revisions_v15.csv", "paid_subscription_scenario_v15.py", "test_paid_subscription_scenario_v15.py",
        "README_research_v15.md", "research_report_2025_v15.md", "package_research_v15.py")}
    for version in (15,):
        folder = root / f"output_research_v{version}"
        new.update({f"twse_history/output_research_v{version}/{path.name}": path
                    for path in folder.iterdir() if path.is_file()})
    new.update({"taiwan_stock_ml_v1_spec.md": Path(args.spec),
                "README.md": root / "README_research_v15.md"})
    for path in new.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with zipfile.ZipFile(args.base) as base, zipfile.ZipFile(target, "w",
                           compression=zipfile.ZIP_DEFLATED, compresslevel=6) as dst:
        if base.testzip() is not None:
            raise ValueError("Bad base archive")
        for info in base.infolist():
            if info.is_dir() or info.filename in new or info.filename == "archive_manifest.json":
                continue
            h = hashlib.sha256()
            with base.open(info) as incoming, dst.open(info.filename, "w") as outgoing:
                while chunk := incoming.read(1024 * 1024):
                    outgoing.write(chunk)
                    h.update(chunk)
            manifest.append(dict(path=info.filename, bytes=info.file_size,
                                 sha256=h.hexdigest()))
        for name, path in sorted(new.items()):
            dst.write(path, name)
            manifest.append(dict(path=name, bytes=path.stat().st_size,
                                 sha256=sha(path)))
        dst.writestr("archive_manifest.json", json.dumps(dict(
            base_archive_sha256=sha(args.base), files=sorted(manifest, key=lambda x: x["path"])),
            ensure_ascii=False, indent=2))
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None or len(z.namelist()) != len(set(z.namelist())):
            raise ValueError("Invalid archive")
    print(json.dumps(dict(path=str(target.resolve()), bytes=target.stat().st_size,
                          files=len(manifest) + 1, sha256=sha(target)), indent=2))


if __name__ == "__main__":
    main()
