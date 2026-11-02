# Public release gate — 2026-10-27 target

This is a **decision checklist**. The date is a target, not approval to
publish unverified code. The product prioritizes functional autonomy; the
owner accepts the risks of granting an agent extensive control over the Mac.
Do not add compulsory restrictive sandboxes or confirmation loops solely for
marketing claims. Protect external access and credentials from outsiders.

## Current evidence (verified 2026-10-26)

- DEV release source on branch feature/background-automation-parity-20261023,
  commit 6596ae2, clean when inspected.
- Separate release worktree release/public-beta-20261027.
- Existing regression suite: 78 tests, OK (one skipped).
- Native and browser background functionality implemented. Mac-specific
  fixture evidence covers covered/minimized-window screenshot, AX actions,
  capability isolation, and two independent Chrome sessions.
- Two 30-minute sustained runs are documented, but foreground preservation
  throughout is **inconclusive** because the frontmost PID changed during
  both runs. Spaces and lock/unlock are not yet verified.
- The existing public-facing DEV HTTP preview only exposes read-only tools
  on 127.0.0.1:3101. Full DEV operations are currently offered by local
  stdio through a configured Stable bridge. **No standalone external OAuth
  HTTP service with full feature parity has been verified.**
- A new versioned Mac Control MCP Server installer was installed into an isolated test
  root on the original Mac; local stdio MCP with 102 tools, repeated install,
  and historical independent Chromium (109 tools) passed actual client calls.
  **Browser architecture has since changed to ChatBridge HTTP** and
  requires a new live E2E. A second clean Mac has not been tested; native
  GUI TCC is not installed.
- Experimental standalone remote GitHub OAuth was introduced. Anonymous
  ASGI requests correctly return 401 with auth challenge, but no real GitHub
  sign-in, public HTTPS tunnel or authorized remote write has been verified.
- Current tracked-source secret scan: zero obvious critical signatures,
  with owner-specific paths/identifiers flagged. Local history audit scanned
  242 blobs with zero heuristic critical signature matches. Neither proves
  absence of private data or clears source provenance.
- Source includes hardcoded owner's macOS paths, launchd identifiers and
  legacy handler assumptions. These need portability refactoring.
- MIT LICENSE for Mac Control MCP Server is now included; public GitHub
  remote, independent code provenance audit and publication remain open.
- ChatBridge is prepared in its own repository with separate MIT LICENSE
  and EN/RU READMEs. Publish and validate ChatBridge first, then Mac Control.

## P0 gates — required BEFORE opening the repository as a usable release

- [x] Select product name Mac Control MCP Server and MIT license;
      source provenance/rights and public GitHub owner still require review.
- [ ] Replace hardcoded local paths/identifiers with reproducible
      per-user configuration, without breaking DEV GUI TCC identity.
- [ ] Audit all Git-tracked files and **all Git history** for credentials,
      tokens, private hostnames, personal data, source licensing and sensitive
      screenshots; remove affected material and revoke any exposed credential.
- [ ] Deliver an independently installable local MCP distribution; verify on
      a clean Mac. Installer must be idempotent, support uninstall/update and
      rollback and must never mutate an existing Stable instance silently.
- [x] Verify ChatBridge Browser API v1 locally through the Mac Control
      adapter with file, DOM, click, screenshot and session operations.
      [ ] Repeat on independent Mac and verify no focus stealing.
- [ ] Implement and verify remote HTTPS/OAuth (or choose explicitly a
      local-stdio-only first release, and accurately advertise that scope).
      A tunnel alone does not supply authentication or write-enabled tools.
- [ ] Reproduce at least one write-capable end-to-end MCP workflow **from
      a fresh installation**, not via an already configured Stable bridge.
- [ ] Verify all 78+ source tests, clean Git status and package checksums.
- [ ] Include truthful README, compatibility matrix, permissions guide,
      owner risk acceptance text, troubleshooting and LICENSE.
- [ ] Independent review of release file inventory and exposure surfaces.
- [ ] Create a GitHub release from the approved commit/tag only after the
      final gate review.

## P1 gates — strongly recommended for broader promotion

- [ ] Verified focus-preservation test with the owner actually using a
      different app while an agent operates in the background.
- [ ] Owner-assisted off-Space, lock/unlock and wake test.
- [ ] Native helper signing/TCC upgrade strategy across updates.
- [ ] Automated macOS CI, including unit/integration and source hygiene.
- [ ] Demo video without personal data: concurrent Mac use + autonomous
      coding/deployment + a third-party MCP adapter (with demo fixtures).
- [ ] English documentation with a direct quick-start, screenshots and
      honest limitations; GitHub topics and descriptive repository About.

## Ready-for-release command checks

From the repository checkout:

    python3 scripts/release_preflight.py --json
    python3 scripts/release_audit.py --strict
    PYTHONPATH=src:. .venv/bin/python -P -B -m unittest discover -s tests -p 'test_*.py' -q

If no isolated Python environment exists yet, the installing agent must
provision one; never run unknown package installation commands without owner
review. The audit scanner is **not** a history/credential assurance.

## Channel sequence once P0 gates pass

1. Publish repository, tag, binary/source release, installer and quickstart.
2. Verify public unauthenticated README viewing and fresh-clone installation.
3. Telegram channel post (Russian), GitHub Discussions/Release notes (English).
4. Show HN only when strangers can actually try the project. Explain
   implementation, limitations and tradeoffs; do not request votes.
5. Product Hunt only with working software and launch visuals prepared;
   optimize for feedback, not upvote requests.
6. Developer audiences: an individual technical story on relevant forums
   or Reddit communities **only where their current self-promotion rules
   allow it**. Do not cross-post boilerplate.
7. Respond to user issues, prioritize installation defects, measure
   successful installs and engaged contributors rather than star count alone.

Do not invent a GitHub URL before origin exists. Do not run scheduled
publication or social posting unless the owner explicitly triggers it
through connected publishing tools.

## Status update — 2026-11-02 (E9 in progress)

The earlier October 26 snapshot remains historical evidence, not a current release approval.
- Owner-approved roadmap: E0–E8 COMPLETE, E9 ACTIVE, E10 PENDING; source branch feature/installer-full-capabilities at 8cdba98.
- Full local regression rerun: 547 tests, successful (one skipped). Python 3.13.12 on macOS arm64; installer preflight exit 0.
- Real GUI permission acceptance: Accessibility and Screen Recording both trusted, AX tree read successfully after owner re-added the GUI helper in macOS Settings.
- The supported installed `MacControlMCP/bin/maccontrol status` launcher succeeds. The active installed release does not yet expose the new `doctor` subcommand.
- Current private plan/progress in `AgentWorkspace/projects/mac-control-mcp-server-private/.planning/` are authoritative for stage status; the sibling legacy full-installer plan/spec headers are stale.
- The source audit attempt was blocked before execution by platform policy; it must not be marked passed. CI from GitHub Actions and a reproducible clean installation have not been verified here.
- Still required for E9: package equivalence, real authenticated ChatBridge, Watcher end-to-end, remote OAuth, upgrade/rollback, GUI TCC after upgrade, final source-history/secret audit.
- See `docs/E9_STATUS_AUDIT_2026-11-02.ru.md` for the detailed local verification and outstanding blockers.

**Release gate remains OPEN.** No public release, production cutover or external publication authorized by this update.

## E9 local GUI RC acceptance — 2026-11-02
- The installer source supports an explicit E9-only local GUI archive override via both `MACCONTROL_GUI_RC_ARCHIVE` (absolute file path) and `MACCONTROL_GUI_RC_SHA256` (64 lowercase hex digits). With no archive set, the existing HTTPS release pin remains unchanged.
- The local path is opened without symlink following; it must be a single-linked regular owner-owned file, not group/world writable, within the archive size limit, and must match the explicit SHA256 before the payload is written. The existing archive extraction and Mach-O/signature checks still apply.
- RED: 5 new regression tests initially failed. GREEN: all 5 now pass. Full source suite: 552 tests OK (1 skipped).
- This override exists only to verify a locally built RC without publishing it. It is not authorization to deploy production or to publish a release. E9 remains PARTIAL; E10 remains pending.

## E9 Watcher protected runtime installer fix — 2026-11-02
- Assess: a default `uv venv --python 3.13` resolved the user's Miniforge Python with group-writable executable (mode 775). The Watcher correctly refused to load its LaunchAgent; do not weaken its file-ownership or permission validation.
- Fix: new versioned releases invoke `uv venv --managed-python --python 3.13` to provision an isolated, protected Python independent of host Conda configuration. Existing installs are not implicitly rewritten.
- Test: one RED->GREEN installer contract test, 35 focused tests and the full 553-test source suite pass (1 skipped). Real uv-managed Python 3.13.12 on this Mac has executable mode 755 and owner UID 501.
- Deployment remains E9 PARTIAL until managed ChatBridge, Watcher, GUI/TCC and OAuth are accepted.

## E9 owner GitHub OAuth consent timeout — 2026-11-02
- Assess: public metadata and anonymous challenge passed, but the interactive OAuth verification failed with `Client failed to connect: Failed to initialize server session`. Its FastMCP client initialization timeout was only 35 seconds while browser-based GitHub consent callback allowed 180 seconds.
- Fix: the owner-invoked smoke test now allows `init_timeout=210` seconds, exceeding its 180-second callback window. The actual MCP tool call still has a bounded 30-second timeout. This does not change server OAuth, issuer validation, credentials or runtime authorization.
- RED/GREEN regression `test_oauth_interactive_timeout` tests the relative timeout invariant, and full suite passes: 554 tests OK, 1 skipped.
- Test harness isolation: remote-release fixture now explicitly mocks absence of an unrelated real host Watcher LaunchAgent. Without this, host-side E9 installation made the fixture query a synthetic root with no ownership marker.
- Owner-authenticated GitHub OAuth E2E remains pending; preflight alone is insufficient.

## E9 live OAuth, GUI and rollback verification — 2026-11-02
- Owner completed the real GitHub OAuth browser consent. An authenticated **public** MCP client successfully called `system_info`, and the installed release wrote an acceptance marker with `authenticated_mcp_success=true` for release `b141d60`. This is stronger evidence than metadata/anonymous-401 preflight.
- A source update to `6f087c9` was performed with the existing owner-managed ChatBridge preserved and the same SHA256-pinned local GUI RC explicitly replaced. The updated native GUI retained both macOS TCC permissions (Accessibility and Screen Recording) and strict code-signature verification.
- The updated remote and Watcher remained running, the independent legacy Mac Control was unaffected, and the complete 13-route Funnel JSON matched the baseline exactly. The prior installed release was retained as `previous`.
- The source installer `--rollback` returned successfully to `b141d60`; remote/Watcher/ChatBridge and legacy service were running, data preserved, GUI TCC still true/true, and owner OAuth acceptance marker once again matched the active release. `6f087c9` remains available as the previous release. No release publication or origin push was performed.
- The source tree includes an MIT LICENSE and a macOS GitHub Actions workflow. The local bounded Git-history scanner examined 277 reachable blobs with zero detected critical findings or skipped large blobs. This is **not** equivalent to a human provenance/third-party licensing audit or a successful remote Actions run for the latest commit.
- The only incomplete installed component reported by `doctor` after explicitly waking an otherwise-idle authenticated ChatBridge is the `mclog` command: the user's pre-existing `~/.local/bin/mclog` symlink points to the independent legacy installation. The new versioned `~/MacControlMCP/current/bin/mclog` remains usable; the old symlink is not overwritten without explicit owner approval.
- E9 is PARTIAL pending owner decision on `mclog`, provenance/licensing, successful relevant remote CI and remaining independent fresh-install/release gates. E10 is PENDING.

## E9 approved legacy CLI migration — 2026-11-02
- The owner explicitly authorized migrating the existing user-global `mclog` command to the newly installed Mac Control MCP Server while preserving the old utility.
- The versioned `scripts.setup_cli_commands.resolve_mclog_conflict(root, approved=True)` accepted the exact preflight: old `~/.local/bin/mclog` was a user-owned symlink to `~/chatgpt-mcp/workspace/mclog.py`, and `mclog-legacy` did not already exist.
- Migration completed successfully: `~/.local/bin/mclog-legacy` retains the original symlink; `~/.local/bin/mclog` is a private mode-0700 managed wrapper to `~/MacControlMCP/current/bin/mclog`. Both commands executed their `--help` operation successfully. The old `net.johnnykor.chatgpt-mcp` LaunchAgent remained running.
- After explicitly waking the existing owned ChatBridge (browser idle is not a login loss), the installed doctor reported **READY for all 11 components** including the CLI and owner-authenticated OAuth marker. No other Mac services or Funnel routes were reconfigured.
- Focused CLI migration regression: 2 tests passed. Full source suite after actual migration: 554 tests OK (one skipped). This closes the E9 CLI ownership decision only; independent clean-host installation, remote CI and third-party source/license provenance remain open release gates. E9 is still PARTIAL, E10 remains PENDING.

## E9 reproducible source and declared-license inventory — 2026-11-02
- Added read-only E9 audits `scripts/release_dependency_audit.py` and
  `scripts/release_payload_audit.py`, plus seven new regression checks and
  two corresponding local steps in the macOS source CI workflow.
- On the current installed Python 3.13 environment, 66/66 pinned
  distributions match version and have declared license metadata (normalized
  names), but self-reported metadata are not a license/rights clearance.
- A 110-file deterministic source archive matches exactly the allowlisted
  installer manifest; two independent builds from identical sources produce
  the same SHA256. The archive omits unlisted/untracked files and refuses
  symlink or duplicate entries. Hash must be regenerated after source edits.
- Source README RU/EN, ChatGPT setup, installation contents and release notes
  now distinguish confirmed owner-host E9 E2E (ChatBridge, Watcher, public
  GitHub OAuth, GUI/TCC, update/rollback) from independent fresh-host and
  remote CI checks that remain pending.
- **Critical RC parity issue:** the default native GUI download still pins
  older beta.11, while E9 signed GUI RC was installed via an explicitly
  SHA256-pinned local archive. Do not claim equivalent public install yet.
- Detailed evidence and open provenance gates:
  `docs/E9_RELEASE_PROVENANCE_AUDIT_2026-11-02.md`.
- Local changes are not pushed and do not prove GitHub Actions passed for
  this exact commit. E9 remains PARTIAL; E10 remains PENDING.

## E9 branch CI and isolated source smoke — 2026-11-02
- The owner approved a push of only `feature/installer-full-capabilities`.
  GitHub Actions run
  [41463010615](https://github.com/johnnykor82/mac-control-mcp-server/actions/runs/41463010615)
  **passed** for SHA `068855aeee5a2b1ee7edda0dba983f665a3b2b1f`:
  macOS-15 / Python 3.9 bootstrap / Python 3.13 validation, source and Git
  history audits, pinned dependencies and licenses, deterministic payload and
  561 integration/unit tests (2 skipped). `main` was not changed.
- An isolated read-only source-copy acceptance (110 identical files, 106 MCP
  compatibility handlers, isolated server initialization and separate
  `--plan` for temporary directories) also passed without creating a
  second user, installing global components or changing LaunchAgents or Funnel.
  Evidence is stored in
  `~/AgentWorkspace/scratch/e9_isolated_source_smoke_20261102.json`.
- This is **not** a real fresh-host GUI/OAuth onboarding. That release gate
  remains open, along with native GUI public-download pin parity and final
  binary redistribution/provenance. E9 remains PARTIAL and E10 PENDING.

## E9 FR-020: native background GUI consolidation (candidate; not released)
- Historical Dev Swift AX implementation (8f9edaa) ported to a Swift fragment
  compiled inside the **existing** MacControlMCPServer.app. Python session
  capability binding, direct owner-only GUI IPC, PID/window/launch-date checks,
  safe AX role/action restrictions and capture using GUI ScreenCaptureKit remain.
- The separate dev_native_background CLI and standalone TCC identity are **not**
  packaged. Staged ad-hoc signed GUI build and security/unit regression pass
  locally; GitHub macOS CI now compiles and verifies the staged app without
  installing or starting it.
- **Blocked release gate:** test the actual signed GUI app under the owner's
  Accessibility+Screen Recording permissions, then live E2E, 30-minute native
  soak, pinned public GUI artifact parity and rollback. The existing production
  app, OAuth, ChatBridge/Watcher, Funnel and legacy Mac Control were untouched.
- Do not enable background_native in production nor advertise seven extra
  background_app_* tools until all gates are accepted.
