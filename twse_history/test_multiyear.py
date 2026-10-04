import json
import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from .build_history import adjust_prices, build_labels, compare_listing_dates, load_actions
from .build_multiyear import assign_temporal_roles, boundary_audit, validate_calendar
from .fetch_quotes import normalize_quotes
from .test_history import events, quotes


class CrossYearTests(unittest.TestCase):
    def data(self):
        q = quotes([100, 95, 95, 104.5])
        q["date"] = pd.to_datetime(["2024-12-30", "2024-12-31", "2025-01-02", "2025-01-03"])
        e = events(["2024-12-31"], [0.95])
        return q, e

    def test_no_factor_reset_at_year_boundary(self):
        q, e = self.data()
        full = adjust_prices(q, e, q.date.max())
        np.testing.assert_allclose(full.adj_close, [100, 100, 100, 110])
        # A real event in December must remain in the scale of January prices.
        independently_built_next = adjust_prices(q.iloc[2:], events([], []), q.date.max())
        naive_return = independently_built_next.adj_close.iloc[0] / full.adj_close.iloc[1] - 1
        self.assertAlmostEqual(naive_return, -0.05)
        boundary = boundary_audit(full, pd.DatetimeIndex(q.date))
        self.assertAlmostEqual(boundary.adjusted_close_return.item(), 0)

    def test_year_end_window_uses_following_year_market_dates(self):
        q, e = self.data()
        p = adjust_prices(q, e, q.date.max())
        labels = build_labels(p, q[["date", "symbol"]], pd.DatetimeIndex(q.date), horizon=2, threshold=0.10)
        row = labels[labels.date.eq(pd.Timestamp("2024-12-31"))].iloc[0]
        self.assertEqual(row.label_window_end, pd.Timestamp("2025-01-03"))
        self.assertEqual(row.entry_market_date, pd.Timestamp("2025-01-02"))
        self.assertTrue(row.label_available)
        self.assertTrue(row.surge_adjusted)

    def test_cross_year_label_is_purged_from_prior_year_training(self):
        labels = pd.DataFrame(dict(
            date=pd.to_datetime(["2024-12-02", "2024-12-30", "2024-12-31", "2025-01-02", "2025-12-31"]),
            symbol="2330", label_available=[True, True, True, True, False],
            label_window_end=pd.to_datetime(["2024-12-31", "2025-01-02", "2025-01-03", "2025-02-03", None])))
        roles = assign_temporal_roles(labels, pd.Timestamp("2025-01-02"))
        self.assertEqual(roles.role.tolist(), ["train_eligible", "purged_overlap", "purged_overlap", "test_eligible", "unlabeled"])
        train = roles[roles.role.eq("train_eligible")]
        self.assertTrue(train.label_window_end.lt(pd.Timestamp("2025-01-02")).all())

    def test_missing_market_day_is_not_treated_as_holiday(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            dates = []
            for m in range(1, 13):
                date = pd.Timestamp(2024, m, 2)
                dates.append(date)
                (raw / f"calendar_2024{m:02d}.json").write_text(json.dumps(dict(
                    stat="OK", fields=["日期"], data=[[f"113/{m:02d}/02"]])))
            q = pd.DataFrame({"date": dates})
            self.assertEqual(len(validate_calendar(q, raw, [2024], pd.Timestamp("2024-12-31"))), 12)
            with self.assertRaises(ValueError):
                validate_calendar(q.iloc[1:], raw, [2024], pd.Timestamp("2024-12-31"))

    def test_no_data_response_on_expected_market_day_is_error(self):
        with self.assertRaises(ValueError):
            normalize_quotes({"stat": "沒有資料"}, pd.Timestamp("2024-01-02"))

    def test_listing_on_closed_day_aligns_without_hiding_missing_quotes(self):
        calendar = pd.to_datetime(["2024-10-01", "2024-10-04", "2024-10-07"])
        new = pd.DataFrame(dict(symbol=["6919", "1111"],
                                official_listed_date=pd.to_datetime(["2024-10-02", "2024-10-04"])))
        q = pd.DataFrame(dict(symbol=["6919", "1111"],
                              date=pd.to_datetime(["2024-10-04", "2024-10-07"])))
        result = compare_listing_dates(new, q, calendar)
        self.assertEqual(result.matches.tolist(), [False, False])
        self.assertEqual(result.matches_market_calendar.tolist(), [True, False])
        self.assertEqual(result.scheduled_on_non_market_day.tolist(), [True, False])

    def test_supplemental_reduction_keeps_evidence_and_adjusts_by_share_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            for kind in ("exrights", "reduction", "par_change", "split"):
                source = raw / f"{kind}_2024.json"
                source.write_text(json.dumps({"stat": "OK", "fields": [], "data": []}))
                (raw / f"{kind}_2024.meta.json").write_text(json.dumps({"url": "https://twse.example/", "fetched_at": "2024-01-01", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}))
            item = dict(event_id="reduction:8101:20241119", symbol="8101", name="華冠",
                effective_date="2024-11-19", announcement_published_at="2024-11-18",
                previous_quote_close=1.9, new_shares_per_old_share=0.2,
                source_file="terms.pdf", source_page_1based=1,
                source_url="https://twse.example/terms.pdf",
                relisting_source_file="resume.pdf", relisting_source_url="https://twse.example/resume.pdf")
            for name, url in [(item["source_file"], item["source_url"]),
                              (item["relisting_source_file"], item["relisting_source_url"])]:
                content = name.encode()
                (raw / name).write_bytes(content)
                (raw / name.replace(".pdf", ".meta.json")).write_text(json.dumps(dict(
                    sha256=hashlib.sha256(content).hexdigest(), url=url, fetched_at="2024-11-18")))
            (raw / "verified_supplemental_actions.json").write_text(json.dumps([item]))
            event = load_actions(raw, 2024, pd.Timestamp("2024-12-31"))
            self.assertEqual(len(event), 1)
            self.assertAlmostEqual(event.adjustment_factor.iloc[0], 5)
            self.assertAlmostEqual(event.official_reference.iloc[0], 9.5)
            (raw / "terms.pdf").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                load_actions(raw, 2024, pd.Timestamp("2024-12-31"))

    def test_response_for_wrong_day_is_error(self):
        with self.assertRaises(ValueError):
            normalize_quotes({"stat": "OK", "date": "20240103", "tables": []}, pd.Timestamp("2024-01-02"))


if __name__ == "__main__":
    unittest.main()
