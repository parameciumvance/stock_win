"""Finite synthetic controls for the independent current-index replay."""
import copy
import json
import unittest

from cash_merger_current_index_independent import parse_saved_index, reconcile_q3


def row(category="M11", clock="20:25:55", subject="現金股份轉換\r\n完整主旨"):
    return dict(CDATE="115/09/18", COMPANY_NAME="甲公司", AN_NAME="來源原分類",
                CODE_NAME="來源產業", AN_CODE=category, CTIME=clock, TYPEK="上市",
                SUBJECT=subject, COMPANY_ID="6674",
                HYPERLINK="https://mopsov.twse.com.tw/mops/web/ajax_t05sr01_1?firstin=true&stp=1&step=1"
                          "&SEQ_NO=5&SPOKE_TIME=" + clock.replace(":", "")
                          + "&SPOKE_DATE=20260918&COMPANY_ID=6674")


def payload(rows, **extra):
    return json.dumps(dict(data=rows, message=["回傳成功"], status="success", **extra),
                      ensure_ascii=False).encode()


class IndependentCurrentIndexTests(unittest.TestCase):
    def test_all_categories_and_exact_source_fields_preserved_without_declared_total(self):
        originals = [row("M08"), row("M17", "20:24:00"), row("M99", "20:23:00")]
        result = parse_saved_index(payload(originals), "6674")
        self.assertEqual([r["original_fields"] for r in result["rows"]], originals)
        self.assertEqual([r["reported_category"] for r in result["rows"]], ["M08", "M17", "M99"])
        self.assertIsNone(result["declared_total"])
        self.assertFalse(result["count_reconciliation_passed"])
        self.assertFalse(result["complete_population_verified"])
        self.assertFalse(result["current_transaction_status_verified"])

    def test_empty_index_cannot_establish_no_later_change_or_cash_eligibility(self):
        result = parse_saved_index(payload([]), "6674")
        self.assertEqual(result["rows"], [])
        self.assertFalse(result["complete_population_verified"])
        self.assertFalse(result["current_transaction_status_verified"])
        self.assertFalse(result["contractual_cash_claim_verified"])

    def test_declared_total_must_be_exact_integer_count(self):
        self.assertTrue(parse_saved_index(payload([row()], total=1), "6674")["count_reconciliation_passed"])
        for value in (0, 2, True, "1", 1.0, None):
            with self.subTest(total=value), self.assertRaises(ValueError):
                parse_saved_index(payload([row()], total=value), "6674")

    def test_duplicate_pointer_rejected_even_when_category_changes(self):
        for duplicate in (row(), row("M99")):
            with self.subTest(category=duplicate["AN_CODE"]), self.assertRaises(ValueError):
                parse_saved_index(payload([row(), duplicate]), "6674")
        result = parse_saved_index(payload([row(), row(clock="20:24:55")]), "6674")
        self.assertNotEqual(result["rows"][0]["pointer_identity"], result["rows"][1]["pointer_identity"])

    def test_wrong_issuer_date_or_url_clock_fails_without_normalizing_identity(self):
        mutations = [dict(COMPANY_ID="2324"), dict(CDATE="115/09/17"), dict(CDATE="115/10/22"),
                     dict(CTIME="25:25:55"),
                     dict(HYPERLINK=row()["HYPERLINK"].replace("202555", "202556")),
                     dict(HYPERLINK=row()["HYPERLINK"] + "&SEQ_NO=5"),
                     dict(HYPERLINK=row()["HYPERLINK"].replace("mopsov.twse.com.tw", "other.example"))]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_saved_index(payload([row() | change]), "6674")

    def test_duplicate_json_keys_nonfinite_numbers_and_capped_rows_fail(self):
        bad = [b'{"data":[],"data":[],"message":["ok"],"status":"success"}',
               payload([]).replace(b'"data": []', b'"data": NaN'),
               payload([], total=float("inf")), payload([row()] * 1000)]
        for body in bad:
            with self.subTest(prefix=body[:45]), self.assertRaises(ValueError):
                parse_saved_index(body, "6674")

    def test_q3_match_requires_every_original_field_including_crlf(self):
        current = parse_saved_index(payload([row(), row("M17", "20:24:00")]), "6674")["rows"]
        self.assertEqual(reconcile_q3(current, payload([row()])), current[:1])
        for field, value in (("SUBJECT", row()["SUBJECT"].replace("\r\n", "\n")),
                             ("CODE_NAME", "後來不同產業"), ("COMPANY_NAME", "後來不同名稱")):
            prior = row() | {field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                reconcile_q3(current, payload([prior]))

    def test_q3_absent_category_is_not_silently_dropped_or_deemed_no_change(self):
        originals = [row(), row("M99", "19:39:09", "股東會公告尚未讀原文")]
        current = parse_saved_index(payload(originals), "6674")
        matches = reconcile_q3(current["rows"], payload([row()]))
        self.assertEqual(len(current["rows"]), 2)
        self.assertEqual(len(matches), 1)
        self.assertEqual(current["rows"][1]["original_fields"], originals[1])
        self.assertFalse(current["current_transaction_status_verified"])


if __name__ == "__main__":
    unittest.main()
