# Contributing to TokenSlim

Thank you for your interest in contributing to **TokenSlim**! We welcome bug reports, feature proposals, documentation improvements, and pull requests from the community.

TokenSlim is an autonomous, token-efficient software engineering agent with selective AST context extraction, Tavily stale-answer detection, and granular Bifrost gateway accounting.

---

## Code of Conduct

We are committed to providing a welcoming, inclusive, and harassment-free environment for all contributors. Please be respectful, constructive, and collaborative in all communications and code reviews.

---

## How to Contribute

### 1. Reporting Bugs & Issues
- Before opening a new issue, check existing GitHub Issues to see if the defect has already been reported.
- When filing a bug report, please provide:
  - Clear, reproducible steps.
  - Expected versus actual behavior.
  - Subprocess traceback, terminal logs, or relevant SSE event trace excerpt.
  - Environment details (OS, Python version, platform).

### 2. Suggesting Enhancements
- Open an issue outlining the motivation, proposed architecture, and expected impact.
- Keep in mind TokenSlim's core architectural tenets:
  - **Minimal Prompt Footprint:** All context extraction must be token-efficient (AST-sliced).
  - **Deterministic Verification:** Fixes must be validated inside ephemeral sandboxes.
  - **Defensive Containment:** Command execution must remain disarmed (`shell=False`, allowlists).

---

## Local Development Workflow

### Prerequisites
- Python 3.11, 3.12, or 3.13
- Git
- PowerShell (Windows) or Bash (Linux / macOS)

### 1. Clone & Set Up Environment
```bash
git clone https://github.com/Rakshit414/TokenSlim_GeekRoom.git
cd TokenSlim_GeekRoom

# Create virtual environment
python -m venv .venv

# Activate:
# On Windows:
.\.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Test Suite
All automated tests must pass before opening a pull request:
```bash
pytest -v
```

### 3. Run Benchmark Suite
Verify that token reduction metrics and task pass rates remain consistent:
```bash
python -m benchmark.runner
```

---

## Development Standards & Guidelines

1. **Security & Sandboxing:**
   - Never introduce `shell=True` in subprocess invocations.
   - Keep binaries restricted to the allowlist in `agent/verification.py`.
   - Ensure path traversal protections (`os.path.realpath`) are maintained across workspace utilities.
   - Do not log or leak sensitive credentials; use `agent.security.scrub_secrets`.

2. **Token Accounting Integrity:**
   - Clearly categorize token metrics: provider-reported (`response.usage`), locally estimated (`tiktoken`), or simulated (`is_simulated = True`).
   - Do not synthesize mock values as provider-reported usage.

3. **Code Style & Formatting:**
   - Follow standard Python PEP 8 conventions.
   - Maintain descriptive function and class docstrings.
   - Keep dependencies lean and standard-library-focused wherever practical (e.g. `ast`, `difflib`, `pathlib`).

---

## Pull Request Process

1. Create a descriptive feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Write unit tests for new functionality under `tests/`.
3. Verify the full test suite passes (`pytest -v`).
4. Ensure no unwanted temporary files, databases (`*.db`), or caches are tracked.
5. Submit a pull request with a clear description of changes, motivation, and test verification output.

Thank you for helping make TokenSlim faster, more token-efficient, and more dependable!
