#!/usr/bin/env python3
"""Offline behavior tests for RewardSplit; no network or wallet access."""
import importlib.util
from contextlib import redirect_stdout
import io
import itertools
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("rewardsplit", Path(__file__).with_name("rewardsplit.py"))
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)


class RewardTests(unittest.TestCase):
    def setUp(self):
        self.metadata = json.loads(Path(__file__).with_name("zto-mainnet.json").read_text())

    def allocate(self, budget, weights, decimals=0):
        metadata = dict(self.metadata, decimals=decimals)
        return rs.allocate({"budget": budget, "contributors": [
            {"id": name, "weight": value} for name, value in weights
        ]}, metadata)

    def test_real_zto_one_token_three_ways(self):
        request = json.loads(Path(__file__).with_name("example.json").read_text())
        result = rs.allocate(request, self.metadata)
        self.assertEqual(self.metadata["decimals"], 18)
        self.assertEqual(self.metadata["symbol"], "ZTO")
        self.assertEqual([a["units"] for a in result["allocations"]],
                         ["333333333333333334", "333333333333333333", "333333333333333333"])
        self.assertFalse(result["all_recipients_supplied"])

    def test_order_independent_ties(self):
        rows = [("z", "1"), ("a", "1"), ("m", "1")]
        expected = self.allocate("2", rows)
        for permutation in itertools.permutations(rows):
            self.assertEqual(self.allocate("2", permutation), expected)
        self.assertEqual([a["units"] for a in expected["allocations"]], ["1", "1", "0"])

    def test_zero_weight_never_wins(self):
        result = self.allocate("1", [("a", "0"), ("b", "1"), ("c", "1")])
        self.assertEqual([a["units"] for a in result["allocations"]], ["0", "1", "0"])

    def test_decimal_weights_and_exact_rounding(self):
        result = self.allocate("0.000000000000000007", [("a", "0.1"), ("b", "0.2")], 18)
        self.assertEqual([a["units"] for a in result["allocations"]], ["2", "5"])

    def test_uint256_boundary(self):
        result = self.allocate(str(rs.UINT256_MAX), [("a", "1"), ("b", "2")])
        self.assertEqual(sum(int(a["units"]) for a in result["allocations"]), rs.UINT256_MAX)
        with self.assertRaises(rs.Invalid):
            self.allocate(str(rs.UINT256_MAX + 1), [("a", "1")])

    def test_budget_rejects_lossy_or_ambiguous_notation(self):
        for value in [0.1, True, 1, "1e3", "NaN", "-1", "+1", "01", " 1", "1.", ".1", "0", "0.001"]:
            with self.subTest(value=value), self.assertRaises(rs.Invalid):
                self.allocate(value, [("a", "1")], 2)

    def test_invalid_contributors(self):
        for rows in [[], [("a", "0")], [("a", "1"), ("a", "2")], [("bad id", "1")],
                     [("a", "-1")], [("a", "1e3")], [("a", 1)], [("a", "0.0000000000000000001")]]:
            with self.subTest(rows=rows), self.assertRaises(rs.Invalid):
                self.allocate("1", rows)

    def test_recipient_identity_is_optional_but_duplicates_fail(self):
        # The two real token contract addresses test parsing, never example payees.
        request = {"budget": "1", "contributors": [
            {"id": "a", "weight": "1", "address": rs.TOKENS["zto"]},
            {"id": "b", "weight": "1", "address": rs.TOKENS["imd"]},
        ]}
        self.assertTrue(rs.allocate(request, self.metadata)["all_recipients_supplied"])
        request["contributors"][1]["address"] = rs.TOKENS["zto"].upper().replace("0X", "0x")
        with self.assertRaises(rs.Invalid):
            rs.allocate(request, self.metadata)
        request["contributors"][1]["address"] = "0x" + "0" * 40
        with self.assertRaises(rs.Invalid):
            rs.allocate(request, self.metadata)

    def test_conservation_and_quota_for_300_seeded_cases(self):
        rng = random.Random(737)
        for _ in range(300):
            count = rng.randint(1, 70)
            weights = [rng.randint(0, 10**18) for _ in range(count)]
            budget = rng.randint(1, rs.UINT256_MAX)
            rows = [(f"worker-{i:03}", str(w)) for i, w in enumerate(weights)]
            result = self.allocate(str(budget), rows)
            self.assertEqual(sum(int(a["units"]) for a in result["allocations"]), budget)
            for allocation, w in zip(result["allocations"], weights):
                units = int(allocation["units"])
                numerator = budget * w
                denominator = sum(weights)
                floor, remainder = divmod(numerator, denominator)
                self.assertIn(units, {floor, floor + bool(remainder)})

    def test_maximum_row_count(self):
        rows = [(f"worker-{i:04}", "1") for i in range(1000)]
        self.assertEqual(len(self.allocate("999", rows)["allocations"]), 1000)
        with self.assertRaises(rs.Invalid):
            self.allocate("999", rows + [("extra", "1")])

    def test_reject_metadata_wrong_chain_or_precision(self):
        request = {"budget": "1", "contributors": [{"id": "a", "weight": "1"}]}
        for changes in [{"chain_id": 8453}, {"chain_id": True}, {"decimals": True}, {"decimals": 256}, {"block_hash": "bad"}]:
            with self.subTest(changes=changes), self.assertRaises(rs.Invalid):
                rs.allocate(request, dict(self.metadata, **changes))

    def test_json_duplicate_keys_and_nonfinite_numbers(self):
        for value in [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'not json']:
            with self.subTest(value=value), self.assertRaises(rs.Invalid):
                rs.parse_json(value)

    def test_abi_metadata_decoding_and_malformed_data(self):
        text = b"ZTO"
        encoded = (32).to_bytes(32, "big") + (3).to_bytes(32, "big") + text.ljust(32, b"\0")
        self.assertEqual(rs.abi_string("0x" + encoded.hex()), "ZTO")
        self.assertEqual(rs.abi_string("0x" + text.ljust(32, b"\0").hex()), "ZTO")
        self.assertEqual(rs.abi_uint("0x" + (18).to_bytes(32, "big").hex()), 18)
        for bad in ["0x", "0x00", "0x" + (encoded + b"\0" * 32).hex(), "0x" + (encoded[:-1] + b"\1").hex()]:
            with self.subTest(bad=bad), self.assertRaises(rs.Invalid):
                rs.abi_string(bad)

    def test_rpc_rejects_wrong_chain_and_reorg(self):
        with patch.object(rs.Rpc, "call", return_value="0x2105"), self.assertRaises(rs.Invalid):
            rs.inspect_token("https://example.com")
        metadata = self.metadata
        text = lambda value: "0x" + value.encode().ljust(32, b"\0").hex()
        responses = ["0x1", "0x10", {"number": "0x10", "hash": metadata["block_hash"]},
                     text("ZTO"), text("Zero To One"), "0x" + (18).to_bytes(32, "big").hex(),
                     "0x" + (100).to_bytes(32, "big").hex(), {"number": "0x10", "hash": "changed"}]
        with patch.object(rs.Rpc, "call", side_effect=responses), self.assertRaises(rs.Invalid):
            rs.inspect_token("https://example.com")

    def test_no_external_input_paths(self):
        with self.assertRaises(rs.Invalid):
            rs.workspace_path(Path.cwd().parent / "outside.json")

    def test_writer_preserves_pretty_output_at_exact_limit(self):
        value = {"message": "ordinary report", "units": "123"}
        expected = json.dumps(value, indent=2, ensure_ascii=True) + "\n"
        with patch.object(rs, "MAX_BYTES", len(expected.encode())), redirect_stdout(io.StringIO()) as output:
            rs.write_json(value)
        self.assertEqual(output.getvalue(), expected)

    def test_large_roster_compact_output_roundtrips_through_receipt(self):
        request = {"budget": "1", "contributors": [
            {"id": str(i).zfill(4) + "x" * 60,
             "weight": "999999999999999999.999999999999999999"}
            for i in range(1000)
        ]}
        report = rs.allocate(request, self.metadata)
        pretty = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
        self.assertGreater(len(pretty.encode()), rs.MAX_BYTES)
        scratch = Path.cwd() / "test" / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="rewardsplit-roundtrip-", dir=scratch) as directory:
            destination = Path(directory) / "report.json"
            rs.write_json(report, destination)
            self.assertLessEqual(destination.stat().st_size, rs.MAX_BYTES)
            saved = rs.read_json(destination)
            self.assertEqual(saved, report)
        receipt_path = Path(__file__).resolve().parents[1] / "rewardreceipt" / "rewardreceipt.py"
        receipt_spec = importlib.util.spec_from_file_location("rewardreceipt_roundtrip", receipt_path)
        receipt = importlib.util.module_from_spec(receipt_spec)
        receipt_spec.loader.exec_module(receipt)
        result = receipt.verify(request, saved, self.metadata)
        self.assertEqual(result["budget_units"], str(10 ** 18))
        self.assertEqual(result["contributors"], 1000)

    def test_writer_accepts_compact_output_at_exact_limit(self):
        # {"x":"..."} plus the terminating newline has nine overhead bytes.
        value = {"x": "x" * (rs.MAX_BYTES - 9)}
        with redirect_stdout(io.StringIO()) as output:
            rs.write_json(value)
        encoded = output.getvalue().encode()
        self.assertEqual(len(encoded), rs.MAX_BYTES)
        self.assertEqual(rs.parse_json(encoded), value)

    def test_writer_refuses_oversize_before_creating_file_or_stdout(self):
        value = {"x": "x" * (rs.MAX_BYTES - 8)}
        with redirect_stdout(io.StringIO()) as output, self.assertRaises(rs.Invalid):
            rs.write_json(value)
        self.assertEqual(output.getvalue(), "")
        scratch = Path.cwd() / "test" / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="rewardsplit-oversize-", dir=scratch) as directory:
            destination = Path(directory) / "report.json"
            with self.assertRaises(rs.Invalid):
                rs.write_json(value, destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
