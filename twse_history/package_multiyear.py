"""Package the audited two-year data, sources, code, and current project spec."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quotes-2025", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--output", default="outputs/taiwan_stock_history_2024_2025_v3.zip")
    args = p.parse_args()
    root = Path(__file__).parent
    out = root / "output_multiyear"
    summary = json.loads((out / "summary_2024_2025.json").read_text())
    tests = json.loads((out / "test_results.json").read_text())
    if not summary["calendar_exact_match"] or tests["failures"] or tests["errors"]:
        raise ValueError("Build/tests are not ready to package")
    report = root / "history_extension_report_2024_2025.md"
    if not report.exists():
        raise FileNotFoundError(report)
    files = {}

    def add(path, archive=None):
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        files[archive or f"twse_history/{path.relative_to(root).as_posix()}"] = path

    for path in root.iterdir():
        if path.is_file() and path.suffix in {".py", ".md", ".txt"}:
            add(path)
    for path in out.iterdir():
        if path.is_file():
            add(path)
    for folder in [root / "raw", Path("data/raw/twse_2024")]:
        for meta in sorted(folder.glob("*.meta.json")):
            record = json.loads(meta.read_text())
            stem = meta.name.removesuffix(".meta.json")
            candidates = [folder / f"{stem}.{ext}" for ext in ("json", "html", "pdf")]
            source = next((x for x in candidates if x.exists()), None)
            if source is None or hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256"]:
                raise ValueError(f"Invalid source checksum: {meta}")
            for path in [meta, source]:
                archive = f"twse_history/raw/{path.name}" if folder == root / "raw" else f"data/raw/twse_2024/{path.name}"
                add(path, archive)
    add(root / "raw/verified_share_ratios.json")
    add(root / "raw/verified_supplemental_actions.json")
    add(root / "README_multiyear.md", "README.md")
    add(args.spec, "taiwan_stock_ml_v1_spec.md")
    add("inputs/quotes_twse_2024.csv.gz", "inputs/quotes_twse_2024.csv.gz")
    add(args.quotes_2025, "inputs/quotes_twse_2025.csv.gz")
    for path in Path("inputs").glob("*2024.json"):
        add(path, f"inputs/{path.name}")
    manifest = [dict(path=name, bytes=path.stat().st_size,
                     sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                for name, path in sorted(files.items())]
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        archive.writestr("archive_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive integrity failure")
    print(json.dumps(dict(path=str(target.resolve()), bytes=target.stat().st_size,
                          entries=len(files) + 1, sha256=hashlib.sha256(target.read_bytes()).hexdigest()), indent=2))


if __name__ == "__main__":
    main()
