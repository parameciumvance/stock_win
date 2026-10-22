"""Page-bound PDF text extraction from pinned official attachment readbacks.

Text identity matches are candidates, not automatic document/legal conclusions.
Full extracted text is saved only beneath ignored inputs; Git outputs contain
source provenance, page counts/hashes and the locations of identity candidates.
"""
import argparse
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.parse import urljoin

from lxml import html
import pypdf
from pypdf import PdfReader

from cash_merger_census_independent import _readback, _transport
from cash_merger_current_index_independent import digest, require, strict_json


ROOT = Path("inputs/cash_merger_pdf_transfer_20261022")
OUT = Path("deliverables/cash_merger_pdf_transfer_20261022")
DOCUMENT_OUT = Path("deliverables/cash_merger_documents_20261022")
POLICY = Path("configs/cash_merger_pdf_transfer_protocol_20261022.json")
CATALOGUE_SHA256 = "2dc775a28540045d30bcf244209c0d07bb2ea8b8aac06bd2e7372f468816f406"
REDIRECT_ARCHIVE_SHA256 = "a21b4ec1547bb4cae44f69ef7d99b714d42240df655e38617c87698f7ae34f2e"
PDF_TRANSFER_SHA256 = "8dfc037a92837c34536f0b65bd488d47d47ceb92992939dfeb5cfa408b1f4dad"  # Parent supplies this only after actual PDF backup/readback.
FILENAMES = ("2026_6674_20261109F02.pdf", "2026_6674_20261109F13.pdf")
IDENTITY_TERMS = {
    "issuer_name": ["鋐寶科技股份有限公司", "鋐寶科技"],
    "meeting_type": ["股東臨時會"],
    "meeting_date": ["115年11月9日", "115年11月09日", "一一五年十一月九日", "115/11/09", "115/11/9", "2026年11月9日", "2026-11-09"],
}


def replay_pdf(body, expected_sha256, identity_terms, expected_pages=None):
    """Reject damaged/wrong binary input; retain blank-page and missing-ID facts."""
    require(isinstance(body, bytes) and digest(body) == expected_sha256, "PDF source SHA mismatch")
    require(body.startswith(b"%PDF-"), "Saved response lacks PDF magic; do not parse an HTML download page")
    try:
        reader = PdfReader(BytesIO(body), strict=True)
        require(not reader.is_encrypted, "Encrypted PDF requires a separately established source path")
        declared = reader.trailer["/Root"]["/Pages"]["/Count"]
        require(type(declared) is int or isinstance(declared, pypdf.generic.NumberObject), "Missing PDF page-tree count")
        count = len(reader.pages)
        require(int(declared) == count and count > 0, "PDF page tree has missing/zero pages")
        require(expected_pages is None or count == expected_pages, "PDF expected page count differs")
        texts, image_counts = [], []
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text(extraction_mode="plain")
            require(isinstance(text, str), f"PDF page{number} did not produce auditable text")
            texts.append(text)
            # Text extraction can coexist with seals, signatures or scanned
            # material. Counting image objects does not authenticate them.
            image_counts.append(len(page.images))
    except Exception as error:
        # Corrupt/encrypted/missing-page inputs fail visibly; they never become
        # a successful unknown legal classification or a substituted source.
        raise ValueError("PDF extraction rejected: " + str(error)) from error
    require(isinstance(identity_terms, dict) and identity_terms
            and all(isinstance(k, str) and isinstance(v, list) and v
                    and all(isinstance(s, str) and s.strip() for s in v) for k, v in identity_terms.items()),
            "Explicit text identity candidate terms required")
    candidates = {name: [] for name in identity_terms}
    pages = []
    for number, (text, image_count) in enumerate(zip(texts, image_counts, strict=True), 1):
        compact = re.sub(r"\s+", "", text)
        found = {}
        for name, alternatives in identity_terms.items():
            matches = [literal for literal in alternatives if re.sub(r"\s+", "", literal) in compact]
            if matches:
                found[name] = matches
                candidates[name].extend(dict(page_number=number, literal=literal) for literal in matches)
        encoded = text.encode("utf-8")
        pages.append(dict(page_number=number, text_sha256=digest(encoded), text_utf8_bytes=len(encoded),
                          character_count=len(text), empty_extracted_text=not text.strip(),
                          embedded_image_count=image_count,
                          visual_review_needed=image_count > 0 or not text.strip(),
                          identity_candidates=found))
    full_text = "\n\f\n".join(texts)
    missing = [name for name, matches in candidates.items() if not matches]
    full = dict(pages=[dict(page_number=n, text=t) for n, t in enumerate(texts, 1)],
                full_text=full_text, full_text_page_separator="LF FORM_FEED LF")
    summary = dict(body_sha256=expected_sha256, size_bytes=len(body), pdf_magic_verified=True,
                   encrypted=False, declared_page_count=int(declared), extracted_page_count=len(pages),
                   all_declared_pages_extracted=True, pypdf_version=pypdf.__version__,
                   extraction_mode="plain", full_text_sha256=digest(full_text.encode("utf-8")),
                   pages=pages, identity_candidate_matches=candidates, missing_identity_candidate_fields=missing,
                   text_identity_candidates_complete=not missing, text_identity_is_legal_or_issuer_verification=False,
                   embedded_image_count=sum(image_counts),
                   visual_review_needed=bool(missing) or any(p["visual_review_needed"] for p in pages),
                   visual_review_completed=False,
                   visual_review_scope="Image counts flag review needs; extraction performs no visual clearance or signature authentication.",
                   contract_terms_automatically_classified=False, contractual_cash_claim_verified=False,
                   historical_first_availability_verified=False, source_gate_passed=False)
    return full, summary


def catalogue_candidates(body):
    """Read the declared Big5 catalogue without selecting by an outcome."""
    tree = html.fromstring(body, parser=html.HTMLParser(encoding="big5"))
    matches = {}
    for tr in tree.xpath('//tr[td/a[contains(@href,"readfile2")]]'):
        cells = [c.text_content().strip() for c in tr.xpath('./td')]
        anchors = tr.xpath('./td/a[@href]')
        require(len(cells) == 11 and len(anchors) == 1, "Catalogue row schema differs")
        match = re.fullmatch(r'javascript:readfile2\("F","6674","([A-Za-z0-9_.-]+)"\);', anchors[0].get("href"))
        require(match and anchors[0].text_content().strip() == match[1] and cells[0] == "6674",
                "Catalogue issuer/declared filename pointer differs")
        filename = match[1]
        require(filename not in matches, "Duplicate catalogue filename")
        matches[filename] = dict(filename=filename, original_cells=cells,
                                  original_cells_sha256=digest(json.dumps(cells, ensure_ascii=False).encode("utf-8")),
                                  literal_pointer=anchors[0].get("href"),
                                  reported_upload_datetime=cells[9],
                                  reported_upload_is_first_public_availability_verified=False)
    require(len(matches) == 15, "Frozen catalogue no longer has all15 declared rows")
    return matches


def audit(root):
    # This check precedes all real PDF archive reads.
    require(isinstance(PDF_TRANSFER_SHA256, str) and re.fullmatch(r"[0-9a-f]{64}", PDF_TRANSFER_SHA256),
            "Awaiting parent-confirmed actual PDF transfer backup/readback")
    root = Path(root)
    policy_body = (root / POLICY).read_bytes()
    policy = strict_json(policy_body)
    require(digest(policy_body) == strict_json((root / OUT / "protocol_freeze.json").read_bytes())["protocol_sha256"],
            "Frozen document protocol drift")
    for filename, expected in policy["prior_checkpoints"].items():
        body = (root / filename).read_bytes()
        require(digest(body) == expected, "Prior checkpoint drift")
        for name, wanted in strict_json(body)["files"].items():
            require(digest((root / name).read_bytes()) == wanted, "Prior frozen member drift")
    require(policy["max_saved_requests"] == 2 and policy["max_source_batches"] == 1
            and policy["source_ledger"] == dict(completed_prior_network_requests=12,
                new_artifact_transfer_max=2, explicit_cumulative_network_ceiling=14,
                old_document_phase_cap_remains4=True), "Explicit two-transfer request allocation differs")
    saved, archive = _readback(root, OUT, "files", PDF_TRANSFER_SHA256)
    require(saved["protocol.json"] == policy_body, "Archived attachment policy differs")
    request_ref = policy["batches"]["files"]
    request_body = (root / request_ref["path"]).read_bytes()
    require(saved["requests.json"] == request_body and digest(request_body) == request_ref["sha256"]
            and request_ref["requests"] == 2,
            "Frozen attachment requests differ")
    requests = strict_json(request_body)["requests"]
    require(len(requests) == 2 and [r["filename"] for r in requests] == list(FILENAMES), "Attachment population differs")
    _transport(saved, set(FILENAMES))
    catalogue, catalogue_archive = _readback(root, DOCUMENT_OUT, "catalogue", CATALOGUE_SHA256)
    catalogue_body = catalogue["raw/company6674_year115_catalogue.html"]
    candidates = catalogue_candidates(catalogue_body)
    redirects, redirect_archive = _readback(root, DOCUMENT_OUT, "attachments", REDIRECT_ARCHIVE_SHA256)
    _transport(redirects, set(FILENAMES))
    evidence = {item["filename"]: item for item in policy["source_evidence"]}
    require(len(evidence) == len(policy["source_evidence"]) == 2 and set(evidence) == set(FILENAMES),
            "Actual PDF source-link population differs")
    docs, full_docs = [], []
    for request in requests:
        filename = request["filename"]
        require(filename in candidates and candidates[filename]["original_cells"][4] == "第一次臨時會",
                "Selected attachment is not in the saved extraordinary-meeting catalogue")
        ref = evidence[filename]
        require(ref["archive_sha256"] == REDIRECT_ARCHIVE_SHA256 and ref["member"] == "raw/" + filename,
                "PDF parent download-page binding differs")
        parent_body = redirects[ref["member"]]
        require(digest(parent_body) == ref["body_sha256"] and not parent_body.startswith(b"%PDF-"),
                "PDF parent response was not the preserved HTML page")
        parent_tree = html.fromstring(parent_body, parser=html.HTMLParser(encoding="big5"))
        hrefs = parent_tree.xpath('//a/@href')
        require(ref["literal_href"] in hrefs and ref["literal_href"].startswith("/pdf/")
                and urljoin("https://doc.twse.com.tw/server-java/t57sb01", ref["literal_href"])
                    == ref["exact_resolved_url"]
                and request == dict(filename=filename, url=ref["exact_resolved_url"]),
                "Actual PDF GET differs from the saved server-generated link")
        body = saved["raw/" + filename]
        record = strict_json(saved["raw/" + filename + ".meta.json"])
        full, summary = replay_pdf(body, record["sha256"], IDENTITY_TERMS)
        require(len(body) == int(candidates[filename]["original_cells"][8].replace(",", "")),
                "Attachment bytes differ from catalogue declared size")
        docs.append(dict(filename=filename, source_archive_sha256=PDF_TRANSFER_SHA256,
                         source_member="raw/" + filename, catalogue=candidates[filename],
                         download_page_archive_sha256=REDIRECT_ARCHIVE_SHA256,
                         download_page_body_sha256=ref["body_sha256"], literal_pdf_href=ref["literal_href"],
                         actual_request_started_at=record["request_started_at"], actual_observed_at=record["observed_at"], **summary))
        full_docs.append(dict(filename=filename, body_sha256=summary["body_sha256"], **full))
    local = dict(documents=full_docs, text_extraction_version=pypdf.__version__)
    small = dict(status="archived_pdf_pages_extracted_identity_candidates_only", auditor_script_sha256=digest(Path(__file__).read_bytes()),
                 archive=archive, catalogue_archive=catalogue_archive, download_page_archive=redirect_archive,
                 catalogue_encoding="big5", catalogue_rows_preserved=15,
                 protocol_sha256=digest(policy_body), attachment_request_sha256=digest(request_body), documents=docs,
                 full_text_saved_only_in_ignored_inputs=True, source_reported_upload_is_historical_first_availability=False,
                 completed_prior_network_requests=12, actual_pdf_transfer_requests=2,
                 explicit_cumulative_network_requests=14, old_document_phase_cap_remains4=True,
                 source_gate_passed=False, cash_claim_source_gate_passed=False, historical_pit_verified=False,
                 profit_edge_proven=False, valid_prospective_signal_date=None, market_prices_or_returns_read=False, orders_authorized=False)
    return local, small


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    full, small = audit(args.root)
    local_path = args.root / ROOT / "pdf_text_full.json"
    local_path.write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n")
    small["local_full_text_sha256"] = digest(local_path.read_bytes())
    path = args.root / OUT / "pdf_replay.json"
    body = (json.dumps(small, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(body)
    print(json.dumps(dict(output=str(path), sha256=digest(body), source_gate_passed=False)))


if __name__ == "__main__":
    main()
