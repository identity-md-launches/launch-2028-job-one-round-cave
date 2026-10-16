# ZipSelect

Extract only explicitly named files from an approved ZIP, with separate output
byte and node budgets. Every archive member is checked, including files you
leave out. This helps a worker retrieve particular documents without unpacking
unrelated files or empty directories. Python 3.9+ standard library only; the
shipped sibling ZipGate and SafeZip modules are required. No installation,
network, environment variables, keys, wallet, payment or coin is needed.

Run this one command from the repository root to see it work offline:

```sh
python3 -B line-2/tools/zipselect/demo.py
```

Tried here: selected the bundled real public IMD OpenAPI capture (23,132 bytes)
from a three-entry demonstration ZIP. A two-node output budget refused it; three
nodes extracted exactly `docs/imd/openapi.json` and its two parents, matching the
capture byte for byte. The unrelated note and empty directory stayed absent.
All archive payloads passed inspection. The source and provenance are shipped
in `../safezip/imd-openapi.json` and `../safezip/sample-source.json`. This is an
offline replay of historical public data, not a fresh observation. The note and
archive packaging are illustrative. The demo approves only the ZIP it creates,
uses disposable `test/scratch/` paths, and removes them afterwards.

## Review, plan, extract

First inspect your own archive and review its inventory:

```sh
python3 -B line-2/tools/zipgate/zipgate.py inspect incoming.zip
```

Retain the returned `archive_sha256`. In the following commands,
`APPROVED_DIGEST` means that actual reviewed 64-hex SHA-256, and the paths are
examples to replace with exact file names from your inventory:

```sh
python3 -B line-2/tools/zipselect/zipselect.py plan incoming.zip --sha256 APPROVED_DIGEST --file docs/readme.txt --file data/input.csv --output-nodes 5 --output-bytes 1048576 --seconds 10
python3 -B line-2/tools/zipselect/zipselect.py extract incoming.zip selected --sha256 APPROVED_DIGEST --file docs/readme.txt --file data/input.csv --output-nodes 5 --output-bytes 1048576 --seconds 10
```

`plan` checks the complete ZIP and reports the selected paths, hashes, bytes and
node count without writing an output. `extract` repeats validation and publishes
the selected tree only after every selected payload matches its reviewed size
and hash. `selected` must be absent and its parent must exist. Paths must be
inside the current workspace without symlink components. Existing destinations
are refused. No archive content is executed, sent or recursively opened.

Each repeatable `--file` names one exact case-sensitive file, with its original
path preserved in the output. No globs, normalization, directory expansion,
renaming or flattening. Directory selections, unknown names, duplicate names,
empty selections and non-string API selections are refused. Implicit parent
directories are included and count once. Unselected empty directories are not
created. Empty selected files count as one node and zero bytes. Reports sort
files by path. The destination root is excluded from `output_nodes`.

Python callers use:

```python
report = process(archive_path, ["docs/readme.txt"], output,
                 expected_sha256=approved_digest,
                 output_nodes=2, output_bytes=1048576, seconds=10)
```

Import `process` from `zipselect.py`; omit `output` for a plan. `selected` must
be a nonempty list or tuple, bounded by `entries`. Approval is mandatory for
both modes; neither CLI mode silently approves an incoming archive. An upper-case
digest is accepted; reports use lower case. A digest identifies bytes, not their
publisher or whether they are safe to use.

Exit 0 emits a successful JSON report; exit 2 emits `ok: false` and a reason on
policy, corruption, resource or I/O failure. Argument syntax errors use argparse
stderr and exit 2. Python policy failures raise `Rejected`; underlying I/O/ZIP
exceptions may propagate. Ordinary failure removes the private staging directory
and leaves no published output. Forced termination may leave `.zipselect-*` for
manual cleanup. Extraction never merges with an existing tree.

## Limits and checks

The entire ZIP must fit all inherited ZipGate limits, even if only one file is
selected. `--entries` (1000), `--directory-bytes` (2 MiB), `--archive-bytes`
(32 MiB), `--nodes` (32000), `--file-bytes` (16 MiB), `--total-bytes` (64 MiB)
and `--ratio` (200) retain their meanings. Additional `--output-nodes` (32000)
and `--output-bytes` (64 MiB) cap the selected tree. All count/byte/ratio budgets
must be positive integers. `--seconds` is one optional cooperative deadline
across validation, planning, selected snapshot capture and extraction. The API
also accepts a fast side-effect-free `cancelled` callback.

ZipGate bounds the central directory before parsing; SafeZip validates all
paths, collisions, compression, sizes, CRCs and content hashes. A further
bounded in-memory snapshot must match the same approved archive digest before
the selected extractor parses it. Replacing the source cannot substitute
different output bytes. Selected streams are size-bounded and hashed again.
These extra passes cost I/O and CPU; selecting less reduces filesystem output,
not the obligation to validate the whole archive.

```sh
python3 -B line-2/tools/zipselect/selftest.py
```

Observed: **30 tests passed**, including selected and omitted malicious paths,
omitted corruption and symlinks, full-archive and selected-tree limits,
mandatory approval, exact selections, shared parents, zero-byte files, parser
sentinels, source growth/replacement, snapshot stability, selected-stream size
and hash checks, staged cleanup after interruption/partial failure, deterministic
deadlines without sleeps, no-overwrite behavior, workspace confinement and CLI
success/refusal. All **104 inherited tests** also passed unchanged.

Use a cooperative workspace with no concurrent filesystem mutations. This is
not a defense against hostile local symlink/rename races. Classic single-disk
stored/deflated ZIPs only; ZipGate conservatively refuses ZIP64, prefixes,
noncontiguous directories and trailing data. Parser and snapshot overhead remain:
limits are not hard RAM/CPU ceilings. One blocking read, decompression, parser,
sort, cleanup or publication can overrun the cooperative deadline. Reports are
serialized outside that deadline. Archive permissions, executability, ownership
and timestamps are not restored. Hashes do not certify content safety.
