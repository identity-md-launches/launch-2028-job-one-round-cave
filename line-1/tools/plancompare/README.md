# Plancompare

Compare two complete offline work plans for the same task graph and estimates.
Both plans first pass the existing independent Plancheck validator with the same
external worker count and optional deadline. Invalid plans return diagnostics
without producing misleading deltas. No task label is run.

From the repository root, with Python 3.10+ and no installation:

```sh
python3 -B line-1/tools/plancompare/plancompare.py --demo
```

Observed: both plans pass. Moving fixtures to the second worker lets checking
start two minutes earlier; finish falls from 7 to 5, and deadline margin grows
from 1 to 3. One task changes worker, two start earlier, one keeps its time.

For your own files:

```sh
python3 -B line-1/tools/plancompare/plancompare.py --tasks tasks.json --before before.json --after after.json --workers 2 --budget 20
```

Task input is `{"tasks":[{"id":"build","minutes":4,"after":[]}]}`.
Each plan has `workers`, `finish` and `schedule`, an array of rows containing
`task`, `worker` (1-based), `start` and `finish`. See the embedded demo for a
complete parallel example. A plan may include producer metadata; it is ignored.
Plans from Workplan and Optplan are supported. Replan's partial schedules are
intentionally refused. All input files must be ordinary workspace-local files,
at most 100,000 bytes each, with unique JSON keys. Limits inherited from
Plancheck: 1–500 positive-duration tasks in a DAG, 1–64 workers, finite numeric
values of at most 100 digits and exponent magnitude 100. Decimal values are
checked exactly. Computed times and deltas are exact decimal **strings**.

`finish_delta`, `start_delta` and `finish_delta` per task mean after minus before;
negative means earlier. Task output is sorted by ID and includes unchanged work.
Worker moves compare numeric labels, which must identify the same workers in
both inputs to have operational meaning. A shorter makespan does not mean every
task starts earlier; both directions remain visible. Exit 0 means comparable,
2 means either well-formed plan failed a check, and 1 means malformed input or
an I/O error. Deadline failure also makes plans noncomparable. Omit `--budget`
to compare structurally feasible plans that miss a target.

This is comparison at supplied estimates, not progress tracking, task execution,
a new schedule, worker identity verification, or an optimality proof. There is
no chain, coin, network, wallet, environment access or third-party dependency.
Keep sibling `../plancheck/plancheck.py` with this folder.

Checks: `python3 -B line-1/tools/plancompare/selftest.py`. The suite covers
invalid schedules, deadlines, exact decimals, deterministic permutations,
worker changes, reverse comparisons, CLI behavior and seeded valid plans.
