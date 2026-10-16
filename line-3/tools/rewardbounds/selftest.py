#!/usr/bin/env python3
"""Offline bounded-reward tests, including exhaustive small allocation oracles."""

import copy
from contextlib import redirect_stdout
from fractions import Fraction
import io
import itertools
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

import rewardbounds as rb


def independent_oracle(rows, budget):
    """Enumerate every possible saturated set, then every possible award set."""
    reserved = sum(row[2] for row in rows)
    residual = budget - reserved
    eligible = [i for i, row in enumerate(rows) if row[1] > 0 and row[3] > row[2]]
    candidates = set()
    for mask in range(1 << len(eligible)):
        saturated = {eligible[j] for j in range(len(eligible)) if mask & (1 << j)}
        active = set(eligible) - saturated
        consumed = sum(rows[i][3] - rows[i][2] for i in saturated)
        if consumed > residual:
            continue
        if active:
            level = Fraction(residual - consumed, sum(rows[i][1] for i in active))
        elif consumed == residual:
            level = max((Fraction(rows[i][3] - rows[i][2], rows[i][1])
                         for i in saturated), default=Fraction(0))
        else:
            continue
        if any(rows[i][3] - rows[i][2] > level * rows[i][1] for i in saturated):
            continue
        if any(rows[i][3] - rows[i][2] < level * rows[i][1] for i in active):
            continue
        quotas = tuple(min(Fraction(row[3] - row[2]), level * row[1])
                       if row[1] > 0 else Fraction(0) for row in rows)
        if sum(quotas) == residual:
            candidates.add(quotas)
    if len(candidates) != 1:
        raise AssertionError("oracle did not identify one unique quota vector")
    quotas = candidates.pop()
    floors = [quota.numerator // quota.denominator for quota in quotas]
    remaining = residual - sum(floors)
    # Each candidate awards the right number of units. Maximize total fractional
    # remainder; ties prefer earlier ASCII IDs. This does not sort remainders.
    choices = list(itertools.combinations(range(len(rows)), remaining))
    best = max(choices, key=lambda chosen: (
        sum((quotas[i] - floors[i] for i in chosen), Fraction(0)),
        tuple(i in chosen for i in range(len(rows)))))
    return quotas, [row[2] + floors[i] + (i in best) for i, row in enumerate(rows)]


class BoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = rb.rs.read_json(rb.rr.ROOT / "zto-mainnet.json")

    def request(self, rows, budget):
        return {"budget": rb.rs.display_units(budget, self.metadata["decimals"]),
                "contributors": [{"id": name, "weight": str(weight),
                                  "minimum": rb.rs.display_units(minimum, self.metadata["decimals"]),
                                  "maximum": rb.rs.display_units(maximum, self.metadata["decimals"])}
                                 for name, weight, minimum, maximum in rows]}

    def test_demo_real_zto(self):
        result = rb.demo()
        report = result["allocation"]
        self.assertEqual(report["token"]["address"], rb.rs.TOKENS["zto"])
        self.assertEqual(report["budget_units"], str(10 ** 18))
        self.assertEqual([row["units"] for row in report["allocations"]],
                         [str(4 * 10 ** 17), str(25 * 10 ** 16), str(25 * 10 ** 16), str(10 ** 17)])
        self.assertFalse(report["all_recipients_supplied"])
        self.assertEqual(result["verification"]["report_sha256"], rb.rr.digest(report))

    def test_no_bounds_matches_original_allocator(self):
        rng = random.Random(28)
        for _ in range(100):
            count = rng.randrange(1, 12)
            request = {"budget": rb.rs.display_units(rng.randrange(1, 10 ** 21), 18),
                       "contributors": [{"id": "r%02d" % i,
                                         "weight": str(rng.randrange(1, 9999)) + ".123456789012345678"}
                                        for i in range(count)]}
            plain = rb.rs.allocate(request, self.metadata)
            bounded = rb.allocate(request, self.metadata)
            self.assertEqual([row["units"] for row in plain["allocations"]],
                             [row["units"] for row in bounded["allocations"]])

    def test_seeded_exhaustive_oracle(self):
        rng = random.Random(2828)
        checked = 0
        for _ in range(350):
            rows = []
            for i in range(rng.randrange(1, 7)):
                minimum = rng.randrange(4)
                rows.append(("r%02d" % i, rng.randrange(7), minimum, minimum + rng.randrange(9)))
            if not any(row[1] > 0 for row in rows):
                continue
            reserved = sum(row[2] for row in rows)
            capacity = sum(row[3] - row[2] for row in rows if row[1] > 0)
            if reserved + capacity == 0:
                continue
            budget = rng.randrange(max(1, reserved), reserved + capacity + 1)
            quotas, expected = independent_oracle(rows, budget)
            report = rb.allocate(self.request(rows, budget), self.metadata)
            actual = report["allocations"]
            self.assertEqual([int(row["units"]) for row in actual], expected, (rows, budget))
            self.assertEqual([Fraction(row["discretionary_quota_fraction"]) for row in actual], list(quotas))
            self.assertEqual(sum(int(row["units"]) for row in actual), budget)
            for row, result in zip(rows, actual):
                self.assertLessEqual(row[2], int(result["units"]))
                self.assertLessEqual(int(result["units"]), row[3])
                if row[1] == 0:
                    self.assertEqual(int(result["units"]), row[2])
            checked += 1
        self.assertGreater(checked, 300)

    def test_multiple_caps_and_rounding_tie(self):
        rows = [("a", 100, 0, 1), ("b", 10, 0, 2), ("c", 1, 0, 10), ("d", 1, 0, 10)]
        report = rb.allocate(self.request(rows, 10), self.metadata)
        self.assertEqual([int(row["units"]) for row in report["allocations"]], [1, 2, 4, 3])
        self.assertEqual(report["waterfill_level_fraction"], "7/2")
        self.assertEqual(report["rounding_units_distributed"], 1)
        self.assertTrue(report["allocations"][2]["rounding_unit_awarded"])

    def test_exact_minima_and_zero_capacity(self):
        rows = [("a", 2, 3, 3), ("b", 0, 4, 100)]
        report = rb.allocate(self.request(rows, 7), self.metadata)
        self.assertEqual([row["units"] for row in report["allocations"]], ["3", "4"])
        self.assertEqual(report["waterfill_level_fraction"], "0")
        self.assertEqual(report["rounding_units_distributed"], 0)
        self.assertTrue(all(row["at_minimum"] for row in report["allocations"]))

    def test_budget_equals_positive_capacity(self):
        rows = [("a", 1, 0, 3), ("b", 4, 1, 10), ("c", 0, 2, 20)]
        report = rb.allocate(self.request(rows, 15), self.metadata)
        self.assertEqual([row["units"] for row in report["allocations"]], ["3", "10", "2"])
        self.assertEqual(report["waterfill_level_fraction"], "3")

    def test_infeasible_minima_caps_and_zero_weight(self):
        cases = [([("a", 1, 6, 10), ("b", 1, 6, 10)], 10, "minimum amounts exceeds"),
                 ([("a", 1, 0, 3), ("b", 1, 0, 4)], 8, "capacity"),
                 ([("a", 1, 1, 1), ("b", 0, 0, 100)], 2, "capacity"),
                 ([("a", 0, 1, 2)], 1, "positive"),
                 ([("a", 1, 2, 1)], 2, "minimum exceeds")]
        for rows, budget, message in cases:
            with self.subTest(rows=rows, budget=budget), self.assertRaisesRegex(rb.rs.Invalid, message):
                rb.allocate(self.request(rows, budget), self.metadata)

    def test_uint256_and_fractional_weight_precision(self):
        maximum = rb.rs.UINT256_MAX
        request = self.request([("a", 1, maximum - 10, maximum), ("b", 1, 0, maximum)], maximum)
        request["contributors"][0]["weight"] = "0.000000000000000001"
        request["contributors"][1]["weight"] = "999999999999999999.999999999999999999"
        report = rb.allocate(request, self.metadata)
        self.assertEqual([row["units"] for row in report["allocations"]], [str(maximum - 10), "10"])
        self.assertEqual(sum(int(row["units"]) for row in report["allocations"]), maximum)
        request["contributors"][0]["maximum"] = rb.rs.display_units(maximum + 1, 18)
        with self.assertRaisesRegex(rb.rs.Invalid, "uint256"):
            rb.allocate(request, self.metadata)

    def test_permutation_is_byte_identical(self):
        request = self.request([("a", 100, 1, 3), ("b", 1, 2, 20), ("c", 1, 2, 20)], 14)
        expected = rb.rr.canonical_bytes(rb.allocate(request, self.metadata))
        for permutation in itertools.permutations(request["contributors"]):
            candidate = dict(request, contributors=list(permutation))
            self.assertEqual(rb.rr.canonical_bytes(rb.allocate(candidate, self.metadata)), expected)

    def test_tampering_types_and_request_disagreement(self):
        request = self.request([("a", 2, 0, 3), ("b", 1, 0, 20)], 10)
        report = rb.allocate(request, self.metadata)
        changes = [lambda value: value["allocations"][0].update(units="4"),
                   lambda value: value["allocations"].reverse(),
                   lambda value: value.update(extra=True),
                   lambda value: value.update(rounding_units_distributed=False),
                   lambda value: value["allocations"][0].update(discretionary_quota_fraction="0"),
                   lambda value: value["token"].update(block_number=0)]
        for change in changes:
            altered = copy.deepcopy(report)
            change(altered)
            with self.assertRaises(rb.rs.Invalid):
                rb.verify(request, altered, self.metadata)
        altered = copy.deepcopy(request)
        altered["contributors"][0]["maximum"] = rb.rs.display_units(4, 18)
        with self.assertRaises(rb.rs.Invalid):
            rb.verify(altered, report, self.metadata)

    def test_malformed_input_and_addresses(self):
        base = self.request([("a", 1, 0, 10)], 5)
        for key in ("minimum", "maximum"):
            for value in (None, True, 1, 1.0, "-1", "1e1", "01", "0.0000000000000000000", "9" * 341):
                request = copy.deepcopy(base)
                request["contributors"][0][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(rb.rs.Invalid):
                    rb.allocate(request, self.metadata)
        cases = [dict(base, extra=True), dict(base, contributors=[]), dict(base, budget="0"),
                 dict(base, contributors=[base["contributors"][0]] * 2)]
        for request in cases:
            with self.assertRaises(rb.rs.Invalid):
                rb.allocate(request, self.metadata)
        # Real public contracts are used solely to exercise syntax propagation;
        # they are not suggested recipients and are never in the example.
        request = self.request([("a", 1, 0, 10), ("b", 1, 0, 10)], 5)
        request["contributors"][0]["address"] = rb.rs.TOKENS["zto"].upper().replace("0X", "0x")
        request["contributors"][1]["address"] = rb.rs.TOKENS["imd"]
        report = rb.allocate(request, self.metadata)
        self.assertTrue(report["all_recipients_supplied"])
        self.assertEqual(report["allocations"][0]["address"], rb.rs.TOKENS["zto"])
        request["contributors"][1]["address"] = rb.rs.TOKENS["zto"]
        with self.assertRaisesRegex(rb.rs.Invalid, "duplicate recipient"):
            rb.allocate(request, self.metadata)

    def test_metadata_and_output_bounds(self):
        request = self.request([("a", 1, 0, 10)], 5)
        for key, value in (("chain_id", 2), ("decimals", True), ("address", rb.rs.TOKENS["imd"][:-1])):
            metadata = dict(self.metadata)
            metadata[key] = value
            with self.assertRaises(rb.rs.Invalid):
                rb.allocate(request, metadata)
        large = {"budget": "1", "contributors": [{"id": "r%04d" % i, "weight": "1"}
                                                   for i in range(1000)]}
        with self.assertRaisesRegex(rb.rs.Invalid, "output exceeds"):
            rb.allocate(large, self.metadata)
        large["contributors"].append({"id": "extra", "weight": "1"})
        with self.assertRaisesRegex(rb.rs.Invalid, "1000"):
            rb.allocate(large, self.metadata)

    def test_large_report_compacts_and_verifies(self):
        request = {"budget": "1", "contributors": [{"id": "r%04d" % i, "weight": "1"}
                                                     for i in range(750)]}
        report = rb.allocate(request, self.metadata)
        self.assertGreater(len((json.dumps(report, indent=2) + "\n").encode("ascii")), rb.rs.MAX_BYTES)
        output = io.StringIO()
        with redirect_stdout(output):
            rb.rs.write_json(report)
        encoded = output.getvalue().encode("ascii")
        self.assertLessEqual(len(encoded), rb.rs.MAX_BYTES)
        self.assertEqual(encoded.count(b"\n"), 1)
        parsed = rb.rs.parse_json(encoded)
        self.assertEqual(rb.verify(request, parsed, self.metadata)["report_sha256"], rb.rr.digest(report))

    def test_cli_roundtrip_duplicate_keys_and_overwrites(self):
        scratch = Path.cwd() / "test" / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp:
            root = Path(temp)
            request = self.request([("a", 8, 1, 4), ("b", 1, 1, 10), ("c", 1, 1, 10)], 10)
            source, report = root / "request.json", root / "report.json"
            source.write_text(json.dumps(request), encoding="utf-8")
            command = [sys.executable, "-B", str(Path(rb.__file__)), "allocate",
                       "--request", str(source), "--output", str(report)]
            run = lambda args: subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(run(command).returncode, 0)
            self.assertLessEqual(report.stat().st_size, rb.rs.MAX_BYTES)
            self.assertEqual(run(command).returncode, 2)
            check = [sys.executable, "-B", str(Path(rb.__file__)), "verify", "--request", str(source),
                     "--report", str(report)]
            self.assertEqual(run(check).returncode, 0)
            report.write_text('{"schema":"a","schema":"b"}', encoding="utf-8")
            self.assertEqual(run(check).returncode, 2)

    def test_outside_workspace_refused_before_read(self):
        with self.assertRaisesRegex(rb.rs.Invalid, "within the current workspace"):
            rb.rs.workspace_path(Path.cwd().parent / "not-read.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
