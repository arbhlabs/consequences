# Changelog

## 1.5.0

- Added an optional local points ledger with agent and task balances, trends, streaks, and JSON export.
- Added weighted rule memory, per-agent watch lists, tag suggestions, and a generated weekly lesson digest.
- Added five offline SVG charts, runnable examples, and documentation for setup, privacy, and contributing.

## 1.4.0
- Removed `eval` from the gate runner; project helper scripts are invoked as quoted paths with the artifact passed as a single argument.
- Made reference checks, real smoke tests and completed checklists explicit required gate inputs; UI gates require a screenshot and a visual-review attestation.
- Added artifact SHA-256 evidence, regression tests for paths containing shell metacharacters and failing checks, installer coverage for both platforms, checklist completion enforcement, version consistency validation, and GitHub Actions CI.
- Updated both installers to deploy the gate runner and checklist alongside the skill.

## 1.3.0
- Added 'Lessons from fixes that worked': logs first, test on the real device, look before visual changes, smoke-run helpers, safe one-shot commands with auto-rollback, small in-place fixes.

## 1.2.0 (2026-11-18)
- Core skill goes back to real but unspecified consequences, decided by the owner. This is what made it work.
- The strike ladder and `STRIKES.md` move to an optional add-on: `addons/strike-ladder/`.

## 1.1.0 (2026-11-18)
- Consequences ladder: Trusted, Warning, Probation, Reassigned, Fired, driven by a strike log.
- Same-class repeat counts double; 10 clean handoffs clear a strike; agents state their status in every report.
- New template `STRIKES.md`, plus a "How it keeps agents in line" flowchart in the README.

## 1.0.0 (2026-11-18)
- First public release: the 6-step scripted gate, budget rules, defect handling and "never" list.
- Adds step 4 "Look at it": a screen is only PASS after its real screenshot has been opened and checked.
- Templates: `CHECKLIST.md` and `gate.sh`.
