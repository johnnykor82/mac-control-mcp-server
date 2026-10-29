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
