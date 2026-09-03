# Contributing to Velqron

> **Important:** Velqron is an actively maintained industrial intelligence platform. We prioritize stability, determinism, and explainability over bleeding-edge complexity.

Thank you for your interest in contributing! This document outlines the process, style guides, and architectural rules for the repository.

---

## 1. Development Environment Setup

1. **Fork & Clone** the repository.
2. **Setup Python Environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Configure Environment:** Copy `.env.example` to `.env` and fill in necessary keys.

---

## 2. Code Style & Linting

We enforce strict formatting and linting using `ruff` to ensure a consistent codebase.

* **Line Length:** 100 characters
* **Target Python Version:** 3.10+
* **Quotes:** Double quotes (`"`)
* **Indentation:** 4 spaces

Before submitting a Pull Request, run:
```bash
ruff check .
ruff format .
```
> The CI pipeline will automatically reject any PR that fails `ruff check .`

---

## 3. Branching & Commit Conventions

* **Main Branch:** `main` is always production-ready (stable).
* **Branch Naming:**
    * `feature/your-feature-name`
    * `fix/bug-description`
    * `docs/documentation-update`
* **Commit Messages:** Use imperative mood, e.g., "Add thermal agent", "Fix baseline calculation".

---

## 4. Testing Requirements

All core logic must be thoroughly tested before submitting PRs.

1. **Unit Tests:** Any new engine or agent must have a corresponding test file in `tests/`.
2. **Integration Tests:** Ensure `pytest` passes cleanly across the entire suite.
3. **Accuracy Tests:** If modifying core engine logic, run `python scripts/accuracy_test.py` and ensure the F1 score has not regressed.

---

## 5. Architectural Rules & Anti-Scope

Velqron follows strict architectural boundaries. Please review [System Architecture](VELQRON_SYSTEM_ARCHITECTURE.md) before proposing major changes.

**Do NOT submit PRs that:**
* Deploy unexplainable, black-box deep learning models as the primary/sole trigger for safety contactor trips or final diagnostic verdicts. Auxiliary, lightweight TinyML models (such as 1D CNNs or quantized decision trees) are permitted only as secondary anomaly flags, pattern classifiers, or MCSA helpers.
* Introduce cloud-dependencies for core functionality (the system must work offline).
* Add real-time streaming charts that bypass the cycle-based logic (we aggregate by cycle, not by millisecond).

**DO submit PRs that:**
* Improve the deterministic physics controllers (`signal_controller`, `logic_controller`).
* Add new specialized Expert Agents (`src/agents/`).
* Improve edge performance or stability.
* Enhance hardware support.

---

## 6. Pull Request Checklist

When submitting a PR, please ensure:
- [ ] You have run `ruff check .` and `ruff format .`
- [ ] You have run `pytest` and all tests pass.
- [ ] You have added tests for any new logic.
- [ ] You have updated relevant documentation (including `docs/INDEX.md` if adding a new doc).
- [ ] Your code follows the deterministic, edge-first philosophy of Velqron.
