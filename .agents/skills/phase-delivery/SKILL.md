---
name: phase-delivery
description: >-
  End-to-end workflow for implementing, reviewing, testing, and merging phases
  of the VibePlay Desktop Application Plan. Use when starting or completing a
  phase from src/Desktop App Plan.odt or delivering a feature branch via PR.
---

# VibePlay Phase Delivery Workflow

Follow these steps in order when implementing a phase of the VibePlay Desktop Application Plan:

## 1. Branch & Specification Alignment
1. Ensure `master` is clean and up to date (`git status`, `git pull --ff-only`).
2. Create a dedicated feature branch named `feat/phase-<N>-<short-slug>`.
3. Read the target phase requirements from `src/Desktop App Plan.odt` and `SPEC.md`.
4. If the phase touches UI/templates, inspect `DESIGN.md` and query Stitch MCP (`projectId: "4886383833648930957"`) using `list_screens` and `get_screen`.

## 2. Implementation & Automated Verification
1. Implement the phase modules and corresponding unit/integration tests in `tests/`.
2. Run the full test suite via `uv run pytest` and ensure 100% pass rate with zero regressions.

## 3. Independent Subagent Code Review Gate
1. Before pushing or opening a PR, invoke a `research` or `self` subagent with the role `Senior Code Reviewer`.
2. Prompt the subagent to independently audit all modified files for:
   - Security invariants (loopback binding, file permissions, XSS/input validation)
   - Conformance to `src/Desktop App Plan.odt` and Stitch MCP screens
   - Edge cases, concurrency, and test coverage
3. Address any blocking or non-blocking findings raised by the reviewer and re-run `uv run pytest`.

## 4. Pull Request & Merge
1. Stage and commit only the phase deliverables (never commit temporary screenshots or `.coverage` artifacts).
2. Push the feature branch to `origin` and open a Pull Request using `gh pr create`.
3. Check open pull requests (`gh pr list` / `gh pr view`) and, when instructed to merge if able, merge cleanly into `master` via `gh pr merge <PR> --merge --delete-branch`.
