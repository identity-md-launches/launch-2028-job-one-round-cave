# RewardBounds

RewardBounds divides a ZTO budget while honoring contributor minimum amounts and maximum caps. It reserves every minimum first, then distributes the remaining atomic units according to positive weights, redistributing any share that exceeds a cap. Exact fractions and deterministic rounding preserve every unit. Python 3.9+ and the standard library are sufficient; it uses the existing RewardSplit helpers, RewardReceipt hashing, and real historical Ethereum ZTO metadata.

From the repository root, one command shows it working:

```sh
python3 -B line-3/tools/rewardbounds/rewardbounds.py demo
```

Tried here: exit **0**. The address-free example divides **1 ZTO** into `build` **0.4**, `research` **0.25**, `review` **0.25**, and `support` **0.1** ZTO, totaling exactly **1000000000000000000 atomic units**. Each minimum is 0.1 ZTO. Build's weight of 8 initially attracts most of the discretionary budget, but its total is capped at 0.4; the remaining discretionary amount goes equally to research and review. Support has zero weight and receives its minimum alone. The demo recomputes and verifies the resulting report. These are illustrative role labels, not invented recipient identities.

## Your own allocation

The included `example.json` is the demo request. Replace its budget, IDs, weights and optional bounds with your actual values, keeping the file inside the workspace:

```sh
python3 -B line-3/tools/rewardbounds/rewardbounds.py allocate \
  --request line-3/tools/rewardbounds/example.json --output BOUNDED.json
python3 -B line-3/tools/rewardbounds/rewardbounds.py verify \
  --request line-3/tools/rewardbounds/example.json --report BOUNDED.json
```

The input contains exactly `budget` and `contributors`. Each contributor contains `id` and `weight`, and may contain `minimum`, `maximum`, and their actual Ethereum `address`. All amounts and weights are decimal **strings**; amounts use whole-token units, not atomic-unit integers. For ZTO, `"0.000000000000000001"` is one atomic unit. No address is supplied by default. Supplied addresses are checked syntactically and normalized to lowercase; duplicate IDs and duplicate supplied addresses are refused.

`minimum` defaults to `"0"`; `maximum` defaults to the entire budget. A maximum is the contributor's **total** cap, including their minimum. Each minimum must be at most its maximum. Weights apply only to discretionary units remaining after the minima are reserved: this is an explicit minimum-first policy, not a proportional allocation of the entire budget followed by clamping. A zero-weight contributor receives exactly their minimum, even when their maximum allows more. At least one weight must be positive, including when the minima already exhaust the budget.

The tool refuses a budget below the sum of minima, or above the sum of minima plus the available discretionary capacity of positive-weight contributors. It never silently relaxes a bound, assigns extra units to zero weights, changes the budget, or leaves an undistributed remainder. Without any bounds, it produces the same allocation amounts as RewardSplit.

## Exact allocation rule

After reserving minima, let `R` be the remaining atomic budget and `cap_i = maximum_i - minimum_i`. Choose the smallest nonnegative rational `L` satisfying:

```text
sum(min(cap_i, L * weight_i)) = R
```

Zero weights contribute zero. The tool repeatedly fixes shares that reach their caps, then redistributes the remaining amount among the remaining positive weights. The resulting `discretionary_quota_fraction` values are exact rational atomic-unit quotas. It rounds them down and awards the leftover units to the largest fractional remainders, breaking ties by ASCII contributor ID. Final amounts are minima plus these integer discretionary shares. Since every cap is an integer number of atomic units, rounding up an uncapped quota cannot cross its cap.

Report rows use canonical ASCII ID order; reordering the input rows produces a byte-identical allocation report. Every final amount is within one atomic unit of its minimum plus exact discretionary quota. `waterfill_level_fraction` records `L` in atomic units per weight unit. `at_minimum` and `at_maximum` describe final integer amounts, including equality caused by rounding. All large amounts and fractions are strings. No floating point is used. ID choices affect ties, and largest-remainder rounding does **not** promise that each contributor's allocation increases whenever the budget increases.

`verify` fully recomputes the allocation from the supplied request and metadata, comparing every field and JSON value type. It is **not an independent arithmetic verifier**. Its unsigned receipt hashes the original request, metadata and report; different input ordering changes the request hash while leaving the allocation report unchanged. RewardBounds has its own report schema. Existing RewardAudit, RewardReceipt, RewardBatch and RewardMerge expect RewardSplit's schema and should not be passed this report.

## Limits and observations

Both commands accept `--metadata PATH` for the same ZTO or IMD capture used to allocate. ZTO is the default. The bundled capture records Ethereum block **26205319** and real ZTO's **18 decimals**; it is historical metadata, not a current balance or independently authenticated chain proof. Neither command calls the network.

Limits follow the existing tools: 1–1000 contributors; a positive budget fitting uint256; nonnegative minimum/maximum amounts fitting uint256 and token precision; nonnegative weights with at most 18 whole and 18 fractional digits; strict duplicate-key JSON; and 256 KiB per input and serialized output. The writer removes optional whitespace when indentation would exceed that limit. Detailed reports can still reach the byte limit before the contributor limit; the tool refuses output that cannot fit even compactly rather than truncating it. Every successfully emitted allocation fits the input limit for later verification. Paths must resolve within the current working directory. `--output` creates a new file and refuses overwrites; omitted output goes to stdout.

All **15 tests** passed, including more than 300 feasible seeded cases compared against exhaustive enumeration of cap subsets and rounding-award subsets, 100 unconstrained comparisons with RewardSplit, repeated cap redistribution, equal-remainder ties, zero-weight minima, uint256 arithmetic, fractional weights, permutation invariance, infeasible policies, malformed inputs, compact report round trips, irreducible output bounds, file-based verification, and altered-report refusal:

```sh
python3 -B line-3/tools/rewardbounds/selftest.py
```

Exit **0** means successful allocation or verification; **2** means invalid input, infeasible bounds, disagreement, a size limit or I/O failure. Keep the sibling `rewardsplit` and `rewardreceipt` folders. No installation, wallet material, environment variables, signature, transaction, payment or posting is used. Caller-supplied IDs, weights, bounds and addresses establish neither work, identity, entitlement, ownership, available funds nor authorization.
