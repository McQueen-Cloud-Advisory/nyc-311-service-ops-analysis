"""Meaningful offline metric contracts; these are not BigQuery or DAX results."""
from copy import deepcopy
from unittest import TestCase

from nyc311.contracts import ContractError, content_hash, parse_utc
from nyc311.reference import BOROUGHS, build_marts, case_metrics, percentile_inc, summarize
from nyc311.targets import validate_targets
from nyc311.temporal import local_timestamp, normalize_temporal


def manifest(snapshot_id="fixture_b", observed_at="2026-11-18T12:00:00Z"):
    return {
        "snapshot_id": snapshot_id, "observed_at": observed_at,
        "extraction_started_at": observed_at, "extraction_ended_at": observed_at,
        "source_kind": "synthetic", "target_version": "fixture_targets",
        "expected_count": 0, "source_count": 0,
        "scope": {"dataset_id": "erm2-nwe9", "agency": "TEST", "problems": ["Demo Service"],
                  "cohort_start": "2026-09-07", "cohort_end": "2026-11-16", "source_timezone": "America/New_York"},
    }


def targets(hours=72):
    return [{"agency": "TEST", "problem": "Demo Service", "effective_start": "2026-09-01",
             "effective_end": None, "target_hours": hours}]


def request(request_id, created="2026-11-10T07:00:00", closed=None, status="Open", *, capture=None,
            agency="TEST", problem="Demo Service", borough="BROOKLYN"):
    capture = capture or manifest()
    row = dict(request_id=request_id, snapshot_id=capture["snapshot_id"], created_date=created, closed_date=closed,
               agency=agency, problem=problem, borough=borough, channel="ONLINE", status=status)
    row["payload_hash"] = content_hash(row)
    row.update(normalize_temporal(created, closed, capture["observed_at"]))
    return row


class MetricContracts(TestCase):
    def test_mature_exact_target_closed_late_and_overdue_open(self):
        rows = [
            request("exact", closed="2026-11-13T07:00:00", status="Closed"),
            request("late", closed="2026-11-13T07:00:01", status="Closed"),
            request("overdue"),
        ]
        cases = case_metrics(rows, manifest(), targets(), "test_release")
        by_id = {row["request_id"]: row for row in cases}
        self.assertEqual(by_id["exact"]["elapsed_hours"], 72)
        self.assertEqual(by_id["exact"]["target_numerator"], 1)
        self.assertEqual(by_id["late"]["target_numerator"], 0)
        self.assertEqual(by_id["overdue"]["target_numerator"], 0)
        self.assertTrue(by_id["overdue"]["is_backlog"])
        result = summarize(cases)
        self.assertEqual((result["target_numerator"], result["target_denominator"]), (1, 3))
        self.assertAlmostEqual(result["within_demo_target"], 1 / 3)
        self.assertEqual(result["recorded_closures"], 2)

    def test_maturity_boundary_and_early_closed_immature_case(self):
        rows = [
            request("exactly_mature", created="2026-11-15T07:00:00"),
            request("immature_open", created="2026-11-15T07:00:01"),
            request("immature_closed", created="2026-11-15T07:00:01", closed="2026-11-15T08:00:01", status="Closed"),
        ]
        cases = {row["request_id"]: row for row in case_metrics(rows, manifest(), targets(), "test_release")}
        self.assertEqual(cases["exactly_mature"]["target_denominator"], 1)
        for request_id in ("immature_open", "immature_closed"):
            self.assertTrue(cases[request_id]["is_immature"])
            self.assertEqual(cases[request_id]["target_denominator"], 0)
            self.assertEqual(cases[request_id]["target_numerator"], 0)
        self.assertTrue(cases["immature_closed"]["is_recorded_closure"])
        self.assertTrue(cases["immature_closed"]["is_p90_eligible"])

    def test_exclusions_partition_population_and_have_defined_precedence(self):
        rows = [
            request("invalid", created=None, status="Unspecified", problem="No target"),
            request("unknown", status="Unspecified", problem="No target"),
            request("missing_target", problem="No target"),
            request("immature", created="2026-11-15T08:00:00"),
            request("mature"),
        ]
        cases = case_metrics(rows, manifest(), targets(), "test_release")
        result = summarize(cases)
        self.assertEqual(result["eligibility_counts"], {
            "eligible_mature": 1, "immature": 1, "invalid_outcome": 1,
            "missing_target": 1, "unknown_outcome": 1,
        })
        for row in cases:
            self.assertEqual(sum([row["target_denominator"], row["is_invalid_outcome"], row["is_unknown_outcome"],
                                  row["is_missing_target"], row["is_immature"]]), 1)
        self.assertEqual((result["case_count"], result["intake"]), (5, 4))

    def test_conflicting_status_dates_are_excluded_from_recorded_closures(self):
        cases = case_metrics([
            request("closed_no_date", status="Closed"),
            request("open_with_date", closed="2026-11-11T07:00:00", status="Open"),
            request("negative", closed="2026-11-09T07:00:00", status="Closed"),
        ], manifest(), targets(), "test_release")
        self.assertTrue(all(row["is_invalid_outcome"] for row in cases))
        self.assertFalse(any(row["is_recorded_closure"] or row["is_p90_eligible"] or row["is_backlog"] for row in cases))
        self.assertTrue(all(row["closed_date"] is None for row in cases))
        self.assertTrue(all(row["elapsed_hours"] is None or row["elapsed_hours"] >= 0 for row in cases))

    def test_continuous_p90_uses_case_rows(self):
        self.assertAlmostEqual(percentile_inc([1, 4, 2, 3]), 3.7)
        self.assertEqual(percentile_inc([11]), 11)
        self.assertIsNone(percentile_inc([]))
        self.assertEqual(percentile_inc([3, 1], 0), 1)
        self.assertEqual(percentile_inc([3, 1], 1), 3)
        with self.assertRaises(ValueError):
            percentile_inc([1], 1.1)

    def test_weighted_target_rollup_and_p90_do_not_average_segments(self):
        cases = case_metrics([
            request("a", closed="2026-11-11T07:00:00", status="Closed", borough="BRONX"),
            request("b", closed="2026-11-14T07:00:00", status="Closed"),
            request("c"), request("d"),
        ], manifest(), targets(), "test_release")
        overall = summarize(cases)
        borough_rates = [summarize([row for row in cases if row["borough_key"] == borough])["within_demo_target"]
                         for borough in ("BRONX", "BROOKLYN")]
        self.assertEqual(overall["within_demo_target"], 0.25)
        self.assertNotEqual(overall["within_demo_target"], sum(borough_rates) / 2)
        self.assertAlmostEqual(overall["p90_elapsed_hours"], 88.8)
        self.assertEqual(overall["p90_eligible_count"], 2)

    def test_empty_slice_has_zero_counts_and_undefined_rate_and_p90(self):
        result = summarize([])
        for name in ("case_count", "intake", "recorded_closures", "observed_backlog", "target_numerator",
                     "target_denominator", "p90_eligible_count"):
            self.assertEqual(result[name], 0)
        self.assertIsNone(result["within_demo_target"])
        self.assertIsNone(result["p90_elapsed_hours"])

    def test_target_effective_intervals_are_half_open_and_matching_is_unique(self):
        register, _ = validate_targets([
            {"agency": "test", "problem": "Demo Service", "effective_start": "2026-09-01", "effective_end": "2026-11-10", "target_hours": "24"},
            {"agency": "TEST", "problem": "Demo Service", "effective_start": "2026-11-10", "effective_end": "", "target_hours": "72"},
        ])
        cases = case_metrics([request("before", created="2026-11-09T07:00:00"), request("boundary")],
                             manifest(), register, "test_release")
        by_id = {row["request_id"]: row for row in cases}
        self.assertEqual(by_id["before"]["target_hours"], 24)
        self.assertEqual(by_id["boundary"]["target_hours"], 72)
        with self.assertRaises(ContractError):
            case_metrics([request("fanout")], manifest(), targets() + targets(24), "test_release")

    def test_unknown_boroughs_preserve_population_and_all_dimension_members(self):
        marts = build_marts([request("known"), request("missing", borough=None), request("unrecognized", borough="MARS")],
                            manifest(), targets(), "test_release")
        self.assertEqual({row["borough_key"] for row in marts["dim_borough"]}, BOROUGHS | {"UNKNOWN"})
        self.assertEqual(sum(row["borough_key"] == "UNKNOWN" for row in marts["fct_cases"]), 2)
        self.assertEqual(sum(row["open_count"] for row in marts["fct_backlog"]), 3)
        for dimension in ("agency", "problem", "borough"):
            unknown = next(row for row in marts["dim_" + dimension] if row[dimension + "_key"] == "UNKNOWN")
            self.assertEqual(unknown[dimension], "UNKNOWN")

    def test_projected_dates_keep_invalid_outcomes_out_of_date_relationships(self):
        rows = [
            request("future_closed", closed="9999-01-01T07:00:00", status="Closed"),
            request("outside_cohort", created="2026-09-06T07:00:00"),
            request("ambiguous", created="2026-11-01T01:30:00"),
        ]
        marts = build_marts(rows, manifest(), targets(), "test_release")
        cases = {row["request_id"]: row for row in marts["fct_cases"]}
        self.assertIsNone(cases["future_closed"]["closed_date"])
        self.assertIsNone(cases["outside_cohort"]["created_date"])
        self.assertEqual(cases["ambiguous"]["created_date"], "2026-11-01")
        self.assertTrue(cases["ambiguous"]["is_invalid_outcome"])
        self.assertEqual(cases["ambiguous"]["age_bucket"], "Unknown age")
        self.assertEqual(marts["dim_date"][0]["date_key"], "2026-09-07")
        self.assertEqual(marts["dim_date"][-1]["date_key"], "2026-11-18")
        dates = {row["date_key"] for row in marts["dim_date"]}
        for row in marts["fct_cases"]:
            for field in ("created_date", "closed_date"):
                self.assertTrue(row[field] is None or row[field] in dates)

    def test_calendar_includes_cohort_end_when_observation_precedes_it(self):
        capture = manifest(observed_at="2026-11-12T12:00:00Z")
        marts = build_marts([request("a", capture=capture)], capture, targets(), "test_release")
        self.assertEqual(marts["dim_date"][-1]["date_key"], "2026-11-15")

    def test_creation_and_closure_date_roles_select_different_cases(self):
        cases = case_metrics([
            request("created_then_closed_later", closed="2026-11-16T07:00:00", status="Closed"),
            request("created_earlier_closed_in_slice", created="2026-11-01T07:00:00", closed="2026-11-10T07:00:00", status="Closed"),
        ], manifest(), targets(), "test_release")
        start, end = "2026-11-09", "2026-11-16"
        creation = [row for row in cases if row["created_date"] and start <= row["created_date"] < end]
        closure = [row for row in cases if row["closed_date"] and start <= row["closed_date"] < end]
        self.assertEqual([row["request_id"] for row in creation], ["created_then_closed_later"])
        self.assertEqual([row["request_id"] for row in closure], ["created_earlier_closed_in_slice"])
        self.assertEqual(summarize(closure)["p90_elapsed_hours"], 216)

    def test_history_retains_original_capture_ages_and_filters_other_scopes(self):
        older = manifest("fixture_a", "2026-11-12T12:00:00Z")
        old_rows = [request("same_key", capture=older)]
        current_rows = [request("same_key", closed="2026-11-13T07:00:00", status="Closed")]
        other_scope = deepcopy(older)
        other_scope["snapshot_id"] = "unrelated"
        other_scope["scope"]["agency"] = "OTHER"
        other_kind = deepcopy(older)
        other_kind["snapshot_id"] = "real_capture"
        other_kind["source_kind"] = "real"
        future = manifest("future", "2026-11-20T12:00:00Z")
        marts = build_marts(current_rows, manifest(), targets(), "test_release", [
            (old_rows, older, targets()),
            ([request("other", capture=other_scope)], other_scope, targets()),
            ([request("real", capture=other_kind)], other_kind, targets()),
            ([request("future", capture=future)], future, targets()),
        ])
        self.assertEqual(len(marts["fct_cases"]), 1)
        by_snapshot = {row["snapshot_id"]: row for row in marts["fct_backlog"]}
        self.assertEqual(set(by_snapshot), {"fixture_a", "fixture_b"})
        self.assertEqual(by_snapshot["fixture_a"]["open_count"], 1)
        self.assertEqual(by_snapshot["fixture_a"]["age_24_to_72h_count"], 1)
        self.assertEqual(by_snapshot["fixture_b"]["open_count"], 0)
        self.assertTrue(by_snapshot["fixture_b"]["is_release_snapshot"])
        self.assertFalse(by_snapshot["fixture_a"]["is_release_snapshot"])

    def test_duplicates_and_wrong_snapshot_do_not_create_facts(self):
        row = request("a")
        with self.assertRaises(ContractError):
            case_metrics([row, row], manifest(), targets(), "test_release")
        row["snapshot_id"] = "wrong"
        with self.assertRaises(ContractError):
            case_metrics([row], manifest(), targets(), "test_release")
        with self.assertRaises(ContractError):
            build_marts([], manifest(), targets(), "test_release", [([], manifest(), targets())])

    def test_unreviewed_source_status_requires_mapping_review(self):
        with self.assertRaises(ContractError):
            case_metrics([request("new_status", status="Brand New Status")], manifest(), targets(), "test_release")
        known_unknown = case_metrics([request("unknown", status="Unspecified")], manifest(), targets(), "test_release")
        self.assertTrue(known_unknown[0]["is_unknown_outcome"])

    def test_reported_schema_and_dimension_relationships_are_complete(self):
        from nyc311.contracts import REPO_ROOT, read_json
        marts = build_marts([request("a")], manifest(), targets(), "test_release")
        schema = read_json(REPO_ROOT / "dbt/reporting_schema.json")
        for table, contract in schema["tables"].items():
            expected = {column["name"] for column in contract["columns"]}
            for row in marts[table]:
                self.assertEqual(set(row), expected, table)
                self.assertEqual(row["release_id"], "test_release")
        for dimension in ("agency", "problem", "borough"):
            column = dimension + "_key"
            keys = {row[column] for row in marts["dim_" + dimension]}
            for table in ("fct_cases", "fct_backlog"):
                self.assertTrue(all(row[column] in keys for row in marts[table]))


class SourceTimeContracts(TestCase):
    def test_spring_and_fall_elapsed_time_use_utc_instants(self):
        spring = normalize_temporal("2026-03-08T01:30:00", "2026-03-08T03:30:00", "2026-03-09T12:00:00Z")
        fall = normalize_temporal("2026-11-01T00:30:00", "2026-11-01T02:30:00", "2026-11-02T12:00:00Z")
        for result, hours in ((spring, 1), (fall, 3)):
            self.assertEqual(result["temporal_quality"], "valid")
            self.assertEqual((parse_utc(result["closed_at"]) - parse_utc(result["created_at"])).total_seconds() / 3600, hours)

    def test_ambiguous_and_nonexistent_wall_times_have_no_invented_offset(self):
        for wall_time, quality in (("2026-11-01T01:30:00", "ambiguous_created"),
                                   ("2026-03-08T02:30:00", "nonexistent_created")):
            instant, local_date, actual_quality = local_timestamp(wall_time, "created")
            self.assertIsNone(instant)
            self.assertEqual(local_date, wall_time[:10])
            self.assertEqual(actual_quality, quality)

    def test_missing_invalid_negative_and_future_times_are_explicit(self):
        self.assertEqual(local_timestamp(None, "created")[2], "missing_created")
        self.assertEqual(local_timestamp(None, "closed")[2], "valid")
        self.assertEqual(local_timestamp("2026-02-30T10:00:00", "created")[2], "invalid_created")
        self.assertEqual(local_timestamp("2026-11-10T10:00:00Z", "created")[2], "invalid_created")
        negative = normalize_temporal("2026-11-10T10:00:00", "2026-11-09T10:00:00", "2026-11-18T12:00:00Z")
        future = normalize_temporal("2026-11-10T10:00:00", "2026-11-19T10:00:00", "2026-11-18T12:00:00Z")
        self.assertEqual(negative["temporal_quality"], "negative_elapsed")
        self.assertEqual(future["temporal_quality"], "future_closed")
