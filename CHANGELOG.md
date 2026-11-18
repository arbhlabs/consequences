# Changelog

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
