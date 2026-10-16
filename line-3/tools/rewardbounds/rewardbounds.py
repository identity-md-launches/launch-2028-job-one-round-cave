#!/usr/bin/env python3
"""Allocate exact ZTO rewards with caller-supplied minimum and maximum amounts."""

import argparse
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import re
import sys


SPEC = importlib.util.spec_from_file_location(
    "rewardreceipt", Path(__file__).resolve().parents[1] / "rewardreceipt" / "rewardreceipt.py")
rr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rr)
rs = rr.rs


def bound_units(value, decimals):
    """Parse a nonnegative amount, including zero, without using floating point."""
    rs.require(isinstance(value, str) and len(value) <= 340,
               "minimum and maximum must be decimal strings")
    rs.require(re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value),
               "minimum and maximum must use unsigned ordinary decimal notation")
    whole, _, fraction = value.partition(".")
    rs.require(len(fraction) <= decimals, "bound has more fractional digits than the token")
    units = int(whole) * 10 ** decimals + int((fraction + "0" * decimals)[:decimals] or "0")
    rs.require(units <= rs.UINT256_MAX, "minimum and maximum must fit uint256")
    return units


def parse_request(request, metadata):
    decimals = rs.validate_metadata(metadata)
    rs.require(isinstance(request, dict) and set(request) == {"budget", "contributors"},
               "input must contain exactly budget and contributors")
    budget = rs.token_units(request["budget"], decimals)
    rows = request["contributors"]
    rs.require(isinstance(rows, list) and 1 <= len(rows) <= rs.MAX_CONTRIBUTORS,
               "contributors must contain between 1 and 1000 rows")
    parsed, ids, addresses = [], set(), set()
    for row in rows:
        rs.require(isinstance(row, dict) and {"id", "weight"} <= set(row)
                   <= {"id", "weight", "minimum", "maximum", "address"},
                   "each contributor needs id and weight, with optional minimum, maximum and address")
        identifier = row["id"]
        rs.require(isinstance(identifier, str)
                   and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", identifier),
                   "id must be 1-64 ASCII letters, digits, dots, underscores or hyphens")
        rs.require(identifier not in ids, "duplicate contributor id: " + identifier)
        ids.add(identifier)
        recipient = rs.address(row["address"]) if "address" in row else None
        rs.require(recipient is None or recipient not in addresses, "duplicate recipient address")
        if recipient is not None:
            addresses.add(recipient)
        proportion = rs.weight(row["weight"])
        minimum = bound_units(row.get("minimum", "0"), decimals)
        maximum = bound_units(row["maximum"], decimals) if "maximum" in row else budget
        rs.require(minimum <= maximum, "minimum exceeds maximum for " + identifier)
        parsed.append({"id": identifier, "weight": proportion, "minimum": minimum,
                       "maximum": maximum, "address": recipient})
    parsed.sort(key=lambda row: row["id"])
    rs.require(any(row["weight"] > 0 for row in parsed), "at least one weight must be positive")
    minimum_total = sum(row["minimum"] for row in parsed)
    rs.require(minimum_total <= budget, "sum of minimum amounts exceeds budget")
    capacity = sum(row["maximum"] - row["minimum"] for row in parsed if row["weight"] > 0)
    rs.require(budget - minimum_total <= capacity,
               "budget exceeds minimum amounts plus positive-weight discretionary capacity")
    return budget, decimals, minimum_total, parsed


def checked_size(value):
    # The shared writer uses compact JSON when indentation would exceed its
    # reader's byte cap. Refuse only when even that complete form cannot fit.
    encoded = (json.dumps(value, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False) + "\n").encode("ascii")
    rs.require(len(encoded) <= rs.MAX_BYTES,
               "output exceeds 256-KiB limit; reduce the number of contributors")
    return value


def allocate(request, metadata):
    """Reserve minima, water-fill positive weights up to caps, then apportion units."""
    budget, decimals, reserved, rows = parse_request(request, metadata)
    residual = budget - reserved
    remaining = residual
    capacities = [row["maximum"] - row["minimum"] for row in rows]
    quotas = [Fraction(0) for _ in rows]
    active = {i for i, row in enumerate(rows) if row["weight"] > 0 and capacities[i] > 0}
    level = Fraction(0)
    while remaining:
        # Feasibility was checked before allocation. Each pass either finishes or
        # removes at least one capped row; at most 1000 passes are possible.
        total_weight = sum((rows[i]["weight"] for i in active), Fraction(0))
        level = Fraction(remaining) / total_weight
        saturated = {i for i in active if capacities[i] <= level * rows[i]["weight"]}
        if not saturated:
            for i in active:
                quotas[i] = level * rows[i]["weight"]
            remaining = 0
        else:
            for i in saturated:
                quotas[i] = Fraction(capacities[i])
                remaining -= capacities[i]
            active.difference_update(saturated)

    floors = [quota.numerator // quota.denominator for quota in quotas]
    remainders = [quota - floor for quota, floor in zip(quotas, floors)]
    leftover = residual - sum(floors)
    ranked = sorted(range(len(rows)), key=lambda i: (-remainders[i], rows[i]["id"]))
    winners = set(ranked[:leftover])
    allocations = []
    for i, row in enumerate(rows):
        units = row["minimum"] + floors[i] + (i in winners)
        allocation = {
            "id": row["id"],
            "weight_fraction": str(row["weight"]),
            "minimum_units": str(row["minimum"]),
            "maximum_units": str(row["maximum"]),
            "discretionary_quota_fraction": str(quotas[i]),
            "rounding_unit_awarded": i in winners,
            "units": str(units),
            "amount": rs.display_units(units, decimals),
            "at_minimum": units == row["minimum"],
            "at_maximum": units == row["maximum"],
        }
        if row["address"] is not None:
            allocation["address"] = row["address"]
        allocations.append(allocation)
    assert sum(int(row["units"]) for row in allocations) == budget
    assert all(row["minimum"] <= int(result["units"]) <= row["maximum"]
               for row, result in zip(rows, allocations))
    return checked_size({
        "schema": "rewardbounds-allocation-v1",
        "purpose": "bounded allocation only; no transaction, balance check, or promise of payment",
        "token": {key: metadata[key] for key in
                  ("chain_id", "address", "symbol", "decimals", "block_number", "block_hash")},
        "budget_units": str(budget),
        "budget_amount": rs.display_units(budget, decimals),
        "minimum_units_reserved": str(reserved),
        "discretionary_units": str(residual),
        "method": "reserve minima; cap-weighted discretionary water filling; largest remainder; ASCII id ties",
        "waterfill_level_fraction": str(level),
        "rounding_units_distributed": leftover,
        "unallocated_units": "0",
        "all_recipients_supplied": all(row["address"] is not None for row in rows),
        "allocations": allocations,
    })


def verify(request, report, metadata):
    """Verify by complete recomputation, not by an independent arithmetic method."""
    expected = allocate(request, metadata)
    rs.require(rr.canonical_bytes(report) == rr.canonical_bytes(expected),
               "report differs from exact bounded allocation recomputed from request and metadata")
    return checked_size({
        "schema": "rewardbounds-verification-v1",
        "result": "verified bounded allocation by complete recomputation",
        "budget_units": expected["budget_units"],
        "contributors": len(expected["allocations"]),
        "request_sha256": rr.digest(request),
        "metadata_sha256": rr.digest(metadata),
        "report_sha256": rr.digest(report),
        "scope": "offline arithmetic and input agreement only; no entitlement, identity, balance or payment verified",
    })


def demo():
    metadata = rs.read_json(rr.ROOT / "zto-mainnet.json")
    request = {
        "budget": "1",
        "contributors": [
            {"id": "build", "weight": "8", "minimum": "0.1", "maximum": "0.4"},
            {"id": "research", "weight": "1", "minimum": "0.1"},
            {"id": "review", "weight": "1", "minimum": "0.1"},
            {"id": "support", "weight": "0", "minimum": "0.1", "maximum": "0.5"},
        ],
    }
    report = allocate(request, metadata)
    assert [row["amount"] for row in report["allocations"]] == [
        "0.400000000000000000", "0.250000000000000000",
        "0.250000000000000000", "0.100000000000000000"]
    return checked_size({
        "demo": "Illustrative address-free roles; real historical Ethereum ZTO metadata; no payment.",
        "request": request,
        "allocation": report,
        "verification": verify(request, report, metadata),
    })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="offline 1-ZTO allocation with a floor, a cap and redistribution")
    for command in ("allocate", "verify"):
        check = sub.add_parser(command)
        check.add_argument("--request", required=True, help="bounded allocation request JSON")
        check.add_argument("--metadata", default=str(rr.ROOT / "zto-mainnet.json"))
        check.add_argument("--output", help="new workspace JSON file; never overwrite")
        if command == "verify":
            check.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            result = demo()
        else:
            request = rs.read_json(args.request)
            metadata = rs.read_json(args.metadata)
            result = (allocate(request, metadata) if args.command == "allocate" else
                      verify(request, rs.read_json(args.report), metadata))
        rs.write_json(result, getattr(args, "output", None))
    except (rs.Invalid, OSError, ValueError, OverflowError, RecursionError) as exc:
        message = str(exc) if isinstance(exc, rs.Invalid) else type(exc).__name__
        print("rewardbounds: " + message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
