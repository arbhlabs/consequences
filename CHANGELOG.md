# Changelog

## 1.5.0
- **Consequences Brain** (optional add-on, `addons/brain`): a live 3D desktop window for the points ledger.
  - It shows who leads, who is working right now (Claude Code sessions are detected from their transcripts, other agents push a beacon) and who is waiting for points.
  - One-click Accept writes the agent's own suggested amount.
  - Promotion ranks: a Lead may suggest points for other agents.
  - Claims from the UNATTRIBUTED pool with evidence.
  - Reads the add-on's `ledger.jsonl` or a `Scoreboard.md` table.
  - Push only: OS change notifications. It reflows at any window size.
- **One-click Windows installer** `ConsequencesSetup.exe` with checkboxes for the skill, the points add-on and the Brain window. No admin rights or Python needed, and it uninstalls from Settings → Apps.
- OpenCode bridge (`addons/brain/bridges`) to show agents on another machine through a synced folder.

## Unreleased
- Public README, diagrams, and a recorded real run of the gate on a sample deliverable.
- Points add-on genericized for public use, with a scoreboard template and a rule to record awards automatically.
- Clarified the Warning, Probation, Reassigned, and Fired ladder in the README and add-on docs. Fired is a last resort that has not been needed yet. The usual consequence is that the owner stops using that agent or model.

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