# Changelog

## 1.8.0

- **Referee (rules only, no AI).** Each points ask gets a verdict built from that session's own transcript: tests run and passed, commits, screen and device checks, steps handed back to the owner, and the owner's tone, compared with past awards. The card lists the evidence. It runs in its own idle process every two minutes and never blocks the window.
- The referee hears points typed in chat and logs them once if nobody did (`[heard]`). It may pay by itself only after its backtest clears a fixed bar; automatic rows are marked `[referee]`, capped (±5 a row, ±10 a day per runner) and undone in one click. A `never_auto` list and a seal over its code and caps; any change shows in the window until the owner accepts it.
- New `cb_chatpoints.py` Claude Code hook: "minus 20 points" or "+3" in the owner's prompt is logged the moment it is sent. Promised points and ranges are ignored. Regression test: `addons/brain/tests/test_chatpoints.py`.
- Parallel sessions of one model no longer close each other's asks: a ledger row tied to a session closes only that session's ask.
- A Claude Code API error reply no longer shows the session as working.
- Installer: optional Obsidian vault. Pick a vault and the ledger becomes `<vault>\Consequences\Scoreboard.md` (created from a template, never overwritten, append-only); default stays the local `ledger.jsonl`. Unattended: `-ObsidianVault <folder>`.
- The points skill (`addons/points/SKILL.md`) is now a generic, hand-maintained version: how to ask for points with a calibrated amount, the self-check before asking, promised points, the pool, promotion ranks, the gate and the referee.
- New README, screenshots and a 16 s demo clip, all rendered headless from the fictional sample team.

### Also in 1.8.0: gated point delegation (first published here)

- A score change now stays visible for 15 minutes: a "+10 now" / "-5 3m" chip next to the runner's score, read from the ledger's own timestamps, so it survives a restart and changes that cancel show as "±0". Before, it was a 1.4 s row flash that was easy to miss.
- Stale runners fold into one "N stale · names · Show" line at the bottom of the leaderboard and leave the 3D map. A runner is stale when the owner lists it in config `"stale"` (names, or `{"runners": [...], "why": "..."}`), or when it has had no points for `"stale_after_days"` (default 7). A runner that is working right now is never stale, and stale runners never take the top spot or the green tier.
- New `cb_gate.py`: agents ask the gate for points (`gate claim --job <type> --commit <sha>`), and the gate runs the owner's checks itself on a clean checkout of that commit. It stores the evidence (command, exit code, output hash, artifact hash, commit) and pays only when every required check passes.
- Score is quality first. Any failed check scores 0. Measured lower token use than the median of earlier passing runs adds at most 30% of base points. Unmeasured usage gets no bonus.
- Self-awards are capped and rate limited. Peer awards need rank from owner-given points only. Reciprocal and circular awards are blocked. Anything over a cap waits for the owner's click.
- Checks and policy are sealed by the owner's click. A commit that edits its pinned tests, or an edit to the checks outside the window, stops the gate (fail closed; tamper-evident, not tamper-proof on one account).
- A check that later fails on an awarded commit takes the points back. Every gate award can be reverted. Every write goes through one backup-first ledger path.
- Starts in dry-run: decisions are logged and shown, nothing is written until the owner clicks Go live (two clicks).
- Window: a "Gate" line in the feed with plain-words decisions, Approve checks, Go live / Back to dry-run, Approve / Decline for waiting awards, and Revert.
- Optional Claude Code Stop hook `gate hook`: a finished turn that committed in a gated repo is claimed automatically in the background (idle priority, 2 cores, one run at a time).
- Tests: `addons/brain/tests/test_gate_cheats.py` (38 tests that try to cheat the gate) and new gate checks in `ui_gate.py`. Design: `docs/gated-delegation.md`.

## 1.7.0

- Proven experience: the leaderboard shows jobs, share that went well and XP for each runner, and can be ordered by XP ("Proven").
- New XP tab: programs and models ranked by XP, with the most used program. Ledger data only; jobs that name no model or program are counted as such.

## 1.6.1

- Fixed: in narrow and half-screen layouts the Detail overview could show no timeline lines when the entries were long. The panel now scrolls instead.
- The UI gate fails if a visible timeline shows none of its lines.

## 1.6.0
- **Consequences Brain**: waiting-for-points list is capped. It shows the newest cards that fit (max 4), then one "+N older waiting · Show all" line.
- A finished-work card only becomes a gold card when the final message ends with `Points for this? Suggested: +N (why)`. Other finished work goes to a collapsed quiet group and expires after 12 hours (suggested asks: 3 days).
- Cards show the runner under the leaderboard name, the project folder and the agent's own reason. The owner's raw prompt is never a title; attachments, paths and tool markup are stripped.
- If the award was already given in chat and logged in the ledger during that turn, the card closes by itself.
- Four-step colour scale in the leaderboard and graph: green (top 3), yellow (+20 or more), orange (0 to +19), red (below 0, even in the top 3). The rule is printed under the leaderboard.
- Click a runner for a plain-language view: what it is doing now, rank and trend, latest points, lessons that name it in your skill file, and work waiting for points.
- Graph labels no longer overlap, and the status suffix is shorter ("· asks", "· working").
- First run: an empty scoreboard explains how points get in (three ways, copy buttons with this install's real commands) and offers "Show sample data" (fictional, this session only, writes nothing).
- Lower idle cost: the pulse dots were an infinite CSS animation that forced 60 fps compositing. They are now stepped from the 3D frame. Measured in a headless lab (Chromium, 1936x1048 at 1.5 scale, 25 s, two runs each, 16-thread PC): 1.5.0 used 48-59% of one CPU core, 1.6.0 used 34-35%; memory 979-1120 MB became about 904 MB for the lab browser tree. GPU use did not drop in the lab (17-23% before, about 25% after). These are lab figures, not the installed window.
- New commands: `award "My agent" +5 "what it did" [--why "reason"]`, and `working`, `done`, `idle`, `list`, `claim` pass through to `cb_activity`. The installed app runs them too, with no Python. `--version` prints 1.6.0. `--selftest` never opens a window.
- Default ledger for a fresh install is `%LOCALAPPDATA%\Consequences\ledger.jsonl`. An existing `%LOCALAPPDATA%\ship-gate\ledger.jsonl` is still used.
- New headless UI gate: `python addons/brain/tests/ui_gate.py`.
- Optional Claude Code hooks example: `addons/brain/hooks/claude-code-hooks.example.json`.
- Rewritten Brain README: install, first run, how points get in, hooking up agents, uninstall, third-party notices.

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