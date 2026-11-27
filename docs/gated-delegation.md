# Gated point delegation (design, v1, for owner OK)

**One line:** an agent may *ask the gate* for points; the gate runs the owner's checks itself, scores the evidence, and writes points only when every required check passes, within caps, and only after the owner switches dry-run off.

## Roles and files
All under `%LOCALAPPDATA%\Consequences\gate\` (outside every repo an agent works in):

| File | Who writes it | What it holds |
|---|---|---|
| `checks.json` | owner only (edit, then **Approve** in the window) | job types: repo, check commands, pinned paths, base points |
| `policy.json` | owner only (same Approve) | caps, rate limits, peer rank, windows, bonus ceiling, `dry_run` |
| `seal.json` | the window, on the owner's click | SHA-256 of `checks.json` + `policy.json` |
| `evidence/<id>.json` | gate engine | per check: command, exit code, duration, output tail hash, artifact hash, commit |
| `gate.jsonl` | gate engine | every decision: would-award / awarded / blocked / pending / clawed back, with plain-words reason |

**Fail closed:** if the files don't match the seal, the gate stops awarding and the window shows "Checks changed outside the window". Honest limit: on one Windows account this is **tamper-evident, not tamper-proof**. A same-user process can still edit files. If that is ever needed, the engine moves to a separate local account or the mini PC (not built in v1). Any agent on the account can also import the owner functions. The window therefore lists every owner action (approve, mode, approve/decline, revert) with its time, so an action Aaron did not take is visible.

## Flow
1. The agent finishes and runs `cb_gate.py claim --job <type> --commit <sha> [--for <peer>]`. It can't pass checks, exit codes, scores or usage. Only the job type and the commit.
2. The engine checks the seal, then makes a **clean checkout of that exact commit** in a temp folder (no working-tree files, no untracked files).
3. **Pinned paths:** the tests and scripts named by the job type must hash-match what the owner approved. If a commit edits its own tests, that check fails with "test files changed, needs owner re-approval".
4. The engine runs each check at idle priority, on 2 cores max, with a timeout, one at a time. It stores the evidence, removes the temp checkout and leaves nothing running.
5. It scores, applies caps and rules, and logs one decision line. Dry-run stops here.
6. When live: the result is under the cap, so one ledger entry is written (backup first, `source=gate`, `award=<id>`), or it is over the cap and becomes a gold "waiting for your click" card in the existing waiting list.

## Score (quality first, then usage)
- Any **required** check fails or times out: **0 points**, logged as "blocked: <check> exit 1". Usage never offsets a failure, so cheaper-but-worse is always 0.
- All pass: `base` (the owner's number per job type), plus a usage bonus of up to `bonus_ceiling` (default 30% of base).
- **Usage bonus** = how far under the median of earlier all-pass runs of that job type, scaled from 0 to the ceiling. Usage is **measured** from the Claude Code transcript's token counts over that turn only (start to done). There is no bonus when there is no transcript (Codex, Cursor and others for now), no baseline yet (fewer than 3 prior passes) or no data. It is never estimated.
- The window explains every award in one line, for example: *"+6 to Sonnet 5.5: 4/4 checks passed (unit tests, cheat tests, ui_gate, refs) at a1b2c3d; base 5 + 1 for 38% fewer tokens than the median of 6 passing runs."*

## Self and peer rules
- **Identity is measured, not typed.** The runner comes from the transcript model id, the session id and the commit author, normalised by `canon_agent`. Any `--for` that resolves to the same model or program counts as a self-award. Honest limit: on one account, a peer award can't be *proven* to come from a different agent. That is why peer awards share the same caps.
- **Self-award:** max +10 per award, 3 per 24 h, +20 per day per runner. Over the cap goes to the owner's click.
- **Peer award:** the awarder must hold rank **Lead** (configurable) computed from **owner-sourced rows only**. Gate points never count toward the rank that unlocks peer awards, so nobody can self-award their way up. The beneficiary's commit still has to pass the gate.
- **No reciprocal or circular awards:** an award is blocked if it would close a cycle (A→B→A, A→B→C→A, …) in the gate's award graph over the last 30 days.
- **Idempotent:** one award per (job, commit). Replaying the same evidence does nothing.

## Taking points back
- **Regression:** a later gate run on the same job type and repo fails a check that passed before. Every gate award since the last green run is clawed back as a counter-entry that names the award id.
- **Revert button** on every gate award in the window: one click writes the counter-entry (backup first). The ledger stays append-only, so every change is visible and undoable.
- A gate award never silently closes the owner's open ask for the same turn (`settle_asks` ignores gate rows). If the owner also clicks Accept on that turn's ask, both entries count, and the gate card shows what the gate already paid.
- All ledger writes, including the window's own award path, go through one `append_ledger` with a backup first, for both ledger formats.

## Dry-run (the start state)
`policy.json` ships with `dry_run: true`. The gate runs checks and logs "would award +N" to `gate.jsonl` only. The ledger, the asks folder and the skill stay byte-identical, and a cheat test hashes them before and after. Only the owner's switch in the window turns awarding on.

## Cheat tests (`addons/brain/tests/test_gate_cheats.py`, fixture repos in temp)
These tests try to: edit `checks.json` or `policy.json` without the seal; pass their own exit code or score; claim a dirty tree or uncommitted change; claim a commit that weakens its own tests; claim an unknown commit; replay the same evidence; self-award through an alias; award a peer without rank; reach rank through gate points; trade reciprocal and A→B→C→A awards; exceed the rate limit or daily cap; get a bonus from a forged or missing usage record; win with cheaper but failing work; slip past a check timeout; write anything during dry-run; and keep an award after a regression. All of these must fail, and the honest path must pass. Then `tests/ui_gate.py` runs in headless Chromium, so no window opens on screen.

## Automatic scoring
An optional Claude Code Stop hook (`cb_gate.py hook`) checks whether the finished turn left a fresh, unscored commit (committed in the last 30 minutes) in a gated repo. If it did, the hook starts the claim in the background with that session's transcript, so the session never waits. The checks still run at idle priority, one run at a time.

## Window (no new panel)
Gate decisions show as cards in the existing waiting list, marked "gate". Each card has its plain-words line, an evidence link (commands, exit codes, hashes) and **Revert**, plus **Approve** when the award is over the cap. A small line in the framework tab shows *Gate: dry-run / live*, the seal state and **Approve checks**. The live window runs from its own folder, so building here never touches it. The swap happens only after the gate passes and you say go.

## Knobs (defaults, one approval)
| Knob | Default |
|---|---|
| Self cap per award / per day / awards per 24 h | +10 / +20 / 3 |
| Peer awards need rank | Lead (owner-sourced score ≥ +100) |
| Reciprocal / cycle window | 30 days |
| Usage bonus ceiling | 30% of base; needs ≥3 prior passes |
| Regression look-back | since last green run of that job type |
| Check limits | idle priority, 2 cores, 10 min per check |
| Start mode | dry-run |
| First job type | `consequences-brain`: unit tests + cheat tests + `ui_gate.py`, base +5 |
