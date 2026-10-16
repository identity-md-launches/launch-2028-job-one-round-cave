# SchemeCheck

Detect potential breaking changes to authentication request construction in two
saved OpenAPI 3.0/3.1 descriptions. Python 3.9+, standard library only. Keep the
seven earlier sibling tool folders alongside this folder; no install is needed.

From the repository root, run one offline demonstration:

```sh
python3 -B line-4/tools/schemecheck/schemecheck.py demo
```

The demo uses the bundled real public IMD description. It hypothetically changes
its shared HTTP Bearer definition to Basic in memory. The description has two
aliases for that definition and three authenticated operations. The result is
**six potential breaking findings and one retained review over five operations**.
Anonymous operations remain unaffected. The demo exits 0 after asserting that it
found its hypothetical break; it makes no request and uses no credential.

Compare your own saved descriptions:

```sh
python3 -B line-4/tools/schemecheck/schemecheck.py compare line-4/tools/apidelta/imd-openapi.json line-4/live-openapi-28.json
```

Replace those paths as needed. They must resolve within the current workspace.
Output is deterministic JSON with exact input-byte SHA-256 hashes and escaped
operation locations. Exit codes: **0** no detected breakage (or successful demo),
**1** potential breaking change, **2** invalid/unsupported input or resource
limit, **3** unresolved review without a detected break. Exit 0 does not prove
runtime compatibility.

## Supported checks

SchemeCheck preserves every AuthCheck and earlier schema finding. For common
operations it additionally compares each effective old authentication alternative
against new alternatives. A new alternative covers the old one only if its
scheme/scope/role obligations are a subset and every required same-named scheme
preserves these declared transport details:

- Scheme type (API key, HTTP, OAuth2, OpenID Connect or mutual TLS).
- API-key request location and name. Header names compare without ASCII case;
  query and cookie names compare exactly.
- HTTP authentication scheme, compared without ASCII case.

If the symbolic requirements still have a covering alternative but none retains
those transport details, `security_transport_incompatible` identifies the old
alternative that may stop working. A surviving OR alternative or anonymous
alternative prevents that transport finding. AND requirements must all match.
Already uncovered symbolic alternatives retain AuthCheck's finding without a
duplicate transport finding. Same-named local references resolve before checking,
including aliases and escaped names. Root defaults and operation overrides follow
AuthCheck. Effective API-key and HTTP required fields are validated even when the
descriptions are identical or an alternative is redundant. Invalid shapes fail
with exit 2. No remote reference or discovery URL is fetched.

The semantics are based on the official
[OpenAPI 3.1 Security Scheme Object](https://spec.openapis.org/oas/v3.1.0.html#security-scheme-object).
Only declarations are analyzed; no credential is accepted, read or evaluated.

## Limits

Same scheme names are compared; renames and differently named equivalent schemes
are not inferred. OAuth flow/endpoint/scope-definition changes, OpenID discovery,
TLS trust, extensions and bearerFormat remain unresolved inherited document
reviews. A change in scheme type is a potential break even if the actual service
continues accepting old requests. Unchanged declarations prove no runtime behavior.
The tool is not a full OpenAPI validator: unsupported scheme-specific fields,
unused schemes and policies on newly added/removed operations are not fully
validated. Earlier schema-analysis limitations remain.

Transport comparison adds a separate 100,000 alternative-pair budget. Effective
policies retain 64 alternatives, 32 schemes per alternative and 64 scope/role
entries per scheme. Earlier limits include 1 MiB per file, 50,000 nodes, depth 80,
20,000 schema visits and 2,000 findings. Limit failures refuse the comparison;
they never return a partial pass. Definitions are cached by side and scheme name.

## What happened when tried

- All 11 new regression tests passed, including 100 transport pairs checked
  against an independent wire-slot model, OR survivors, anonymous access, AND
  requirements, scheme-type changes, root inheritance, references, malformed
  effective definitions, review retention, determinism, immutability, resource
  refusal, demo assertions and all CLI exits/input hashes.
- The seven inherited suites passed unchanged: 116 tests. The AuthCheck suite
  includes 65,536 finite symbolic policy comparisons.
- The demo produced six potential breaks and one review across five operations.
- A read-only GET of `https://api.imd.fun/openapi.json` with User-Agent
  `Pepeolithic-SchemeCheck/28.0` returned HTTP 200 and 23,132 bytes. Its SHA-256
  matched the bundled capture. Comparing them found five operations and no
  findings. The exact observation timestamp and comparison are in
  [live-check-28.json](../../live-check-28.json), with bytes saved in
  [live-openapi-28.json](../../live-openapi-28.json).

Run the regressions:

```sh
python3 -B line-4/tools/schemecheck/selftest.py
```

Nothing signs, sends transactions, pays, posts, deploys, reads environment
variables, or accesses a wallet. No coin or price is needed for static comparison.
