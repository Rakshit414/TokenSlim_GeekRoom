# Security Policy

## Reporting Security Issues

We take the security and integrity of **TokenSlim** seriously. If you discover a security vulnerability or potential threat within this project, please report it responsibly.

### Responsible Disclosure Process
- **Do not** report security vulnerabilities via public GitHub issues, pull requests, or public discussions.
- Please email the project maintainer directly at: `rakshit.mj414@gmail.com`
- Include a detailed description of the vulnerability, steps to reproduce, and potential impact.
- We will acknowledge receipt within 48 hours and coordinate a fix prior to public disclosure.

---

## Defensive Architecture & Specifications

TokenSlim includes built-in safeguards to prevent unintended execution:
- **Workspace Sandboxing:** All task execution and patching occurs inside isolated `%TEMP%` directory clones (`agent/workspace.py`).
- **Subprocess Disarmament:** Test runners execute with `shell=False` and are restricted strictly to allowlisted binaries (`pytest`, `python`).
- **Process Tree Killing:** Recursive cleanup (`taskkill /F /T /PID` on Windows, `os.killpg` on POSIX) prevents orphan processes.
- **Secret Sanitization:** Automatic redaction of sensitive credentials (`sk-*`, `tvly-*`, `ghp_*`, `Bearer`) from logs, database records, and telemetry streams.
- **Path Traversal Protection:** Canonical path verification (`os.path.realpath`) prevents directory escapes (`../`) and symlink attacks.

For full architectural details, threat models, and command execution policies, refer to the complete specification:
👉 **[docs/security/SECURITY.md](docs/security/SECURITY.md)**
