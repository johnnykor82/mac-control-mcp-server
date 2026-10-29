# Security model and responsible disclosure

**This project is designed for powerful, autonomous access by AI agents.**

A user who enables its command, file, SSH, GUI or MCP bridging tools gives the
authorized agent capabilities comparable to interactive access to the owner's
Mac and connected services. This can cause irrecoverable data loss, credential
exposure, unintended deployments, expensive actions, or remote compromise.
An LLM can also be deceived by text it sees in files and web pages.

The goal is **not** to claim that Mac Control is a secure sandbox. Full
capabilities should remain available where the owner chooses to grant them.
Do not treat a project directory allowlist as a reliable OS security boundary
when unrestricted shell commands are also enabled.

## What still matters

- Authentication of clients connecting from outside the Mac.
- Encrypted transport and protection of credentials/tokens.
- Explicit owner choice to enable powerful operations.
- Clear indication which endpoint is local-only and which is externally
  accessible, plus revocation of external access.
- No secrets committed to Git or distributed in release archives.
- Diagnostic logs should not expose passwords, tokens or private input.
- Never silently change the active production installation.

## Reporting a vulnerability

Until a private security-reporting channel is configured on GitHub, do
**not** post credentials, exploit details or private user data in public
issues. Contact the maintainer privately through the repository's security
reporting mechanism once it is configured. We do not currently promise an
SLA or a formal security response program.

The full installation, OAuth, GUI and remote exposure claims remain subject
to docs/PUBLIC_RELEASE_GATES.md. This document is a description of intended
product risk posture, not an audit certificate.
