"""Fail closed on missing/mismatched frozen inputs for the v79–v81 diagnostics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "docs/DIAGNOSTIC_INPUTS.json"


def verify(root: Path = ROOT, manifest: Path = MANIFEST) -> list[str]:
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    issues = []
    for entry in entries:
        path = root / entry["path"]
        if not path.is_file():
            issues.append(f"MISSING {entry['path']}")
            continue
        if path.stat().st_size != entry["bytes"]:
            issues.append(f"SIZE MISMATCH {entry['path']}")
            continue
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != entry["sha256"]:
            issues.append(f"SHA256 MISMATCH {entry['path']}")
    return issues


def main() -> None:
    problems = verify()
    if problems:
        print("\n".join(problems))
        print("See docs/DATA_SETUP.md; do not silently substitute new snapshots.")
        raise SystemExit(1)
    print("Frozen diagnostic inputs: size and SHA-256 verified.")


if __name__ == "__main__":
    main()
