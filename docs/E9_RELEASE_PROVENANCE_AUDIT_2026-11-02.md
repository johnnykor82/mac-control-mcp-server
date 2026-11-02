# E9 — Source, dependencies, licenses and CI evidence (2026-11-02)

Status: **LOCAL CHECKS PASSED, RELEASE GATE NOT CLEARED**. These checks do
not authorize a GitHub push, prerelease, new service installation or E10.

## Scope and evidence

- Source branch: `feature/installer-full-capabilities`. Locally modified
  source is **not** automatically tested by GitHub Actions; the upstream
  default branch is a different commit.
- Source MIT LICENSE was inspected in the working tree and through the owner's
  GitHub repository. The separately maintained ChatBridge source also declares
  MIT in its published repository LICENSE (GitHub
  `johnnykor82/chatbridge`). Both licenses require keeping their copyright
  and permission notices in substantial redistributions.
- `requirements/dev-frozen.txt` contains **66 exact version pins**. An
  installed Python 3.13 environment was inspected using
  `scripts/release_dependency_audit.py`, including correct PEP 503
  canonicalization of `jaraco.classes` / `jaraco-context` /
  `jaraco-functools`. Result: 66 installed distributions match the exact
  pins, and all 66 declare some license metadata.
  License declarations include MIT, BSD, Apache, ISC, MIT-0, Unlicense,
  PSF-2.0 and dual-license alternatives. **The machine-readable inventory,
  not an inferred license category count, is the source for exact declarations.**
- Repeatable local inventory output:
  `/Users/openclaw/AgentWorkspace/scratch/e9_dependency_licenses_20261102.json`.
  This is a metadata inventory: origin ownership, copyright notices,
  transitive native libraries, license compliance, and security advisories
  require independent verification. No legal clearance is claimed.
- Explicit installation source manifest: **110 files**. The deterministic
  release-source audit creates a byte-for-byte TAR/GZIP using sorted manifest
  entries and fixed metadata (mtime, mode, owner). Identical inputs produce
  identical archive SHA-256; changed inputs change digest. The audit rejects
  duplicates, paths outside the installer allowlist, symlinks and missing
  files. Private/untracked files outside the manifest are not included.
  Re-run `python -P -B scripts/release_payload_audit.py` after any tracked
  release-source modification; do not treat an earlier checksum as current.
- Existing signed universal GUI RC was tested locally with SHA-256
  `6f9f4924a8a6c784c1b4abf30bd0cff99da43307b484eba233ee558d2f8c079e`.
  **The default installer is still pinned to the older beta.11 GUI archive**,
  SHA-256 `7540329d030e5066d49ef9af4c8c2007edc245f8c17b7ef3c93c39114881cfaa`.
  The tested RC was installed using the explicit two-variable local archive
  override; do not imply a public install will obtain the same RC yet.
- Managed ChatBridge installer separately pins `johnnykor82/chatbridge`
  release `v0.2.0-beta.11` and SHA-256
  `bad1268ff113cbd2311eb1d82c113adb2cb5da0902433b1677d7443f516e6064`.
  GitHub tag `v0.2.0-beta.11` itself was inspected: its `LICENSE` file is
  MIT and `pyproject.toml` identifies `chatbridge-gateway 0.2.0b11` and
  `license = "MIT"`. The installed managed ChatBridge venv has 14
  distributions; all 14 provide license metadata, including
  `aiohttp 3.14.5` (Apache-2.0 AND MIT), `playwright 1.64.1`
  (Apache-2.0), and `greenlet 3.5.6` (MIT AND PSF-2.0).
  A final redistribution-notices and binary content review remains required;
  declaration metadata alone is not sufficient.
- A local source audit and locally reachable Git-history audit previously
  passed with no critical heuristic findings, but they cannot prove absence
  of secrets or verify copyright provenance.
- The macOS CI workflow includes Python 3.9 bootstrap planning, Python 3.13,
  compilation, source and Git-history audits, pinned dependency installation,
  deterministic payload and metadata audits, and full unit/integration tests.
  **No completed GitHub Actions run matching the current local working commit
  has been observed**. There has been no push.

## Acceptance and remaining P0/P1 items

1. Preserve exact third-party copyright/permission notices and verify rights
   for the pinned ChatBridge release, native GUI archive and any vendored code.
2. Check the current RC's default-download pin and released bytes against
   the locally signed, tested helper. This requires deliberate release and
   publication approval, not a silent change to running services.
3. Confirm the package manifest, checksum, test matrix and CI results against
   one exact future commit/tag, not a prior Beta CI run.
4. Complete an independent clean macOS installation and owner-driven GUI,
   OAuth, browser and Watcher acceptance. No extra macOS account is assumed
   or created on the owner's current Mac.
5. Finalize Source/README/ChatGPT setup/release notes and perform E9
   Analyze → Converge with a local Git commit. E10 must remain PENDING until
   E9 gates are met; public prerelease or installed-service changes require
   a separate owner decision.

## Reproduction (source tree only)

```sh
PYTHONPATH=src:. python -P -B scripts/release_dependency_audit.py
PYTHONPATH=src:. python -P -B scripts/release_payload_audit.py
PYTHONPATH=src:. python -P -B -m unittest tests.integration.test_release_provenance_audit -v
PYTHONPATH=src:. python -P -B -m unittest discover -s tests -p 'test_*.py' -q
```
