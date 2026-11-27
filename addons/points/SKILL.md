---
name: consequences-points
description: >-
  Optional add-on to Consequences: the owner scores agent work with points (+ for wins, - for misses).
  Use when the owner awards or removes points, reacts to work with praise or anger, or when you finish a
  piece of work and should ask for points. Defines how to read tone as a score, how to suggest a calibrated
  amount, the self-check before asking, promotion ranks and the consequence ladder. The owner alone sets the score.
---
<!-- generic: maintained by hand in the public repo; do not overwrite from a private copy -->
# Consequences add-on: points

The owner scores work with points. Plus points mean do more of exactly that and record what earned it. Minus points mean find the root cause, fix it, record the rule, and do not argue or excuse. No points is not neutral: read the tone.

Points exist to push work toward a result the owner could show someone else: clean, documented, tested, and demoable.

## Before work (one minute)

1. Read the top three rows of the scoreboard and copy the pattern that earned their points: what shipped, how it was verified, what they refused to do.
2. Read your own row and the rules below. If you are about to repeat a logged mistake, follow the rule written for it instead of reasoning from scratch.
3. Agents the Consequences Brain does not see by itself (anything that is not Claude Code or the OpenCode bridge) announce themselves:
   `python cb_activity.py working "<runner/model>" --task "<what>"`. A beacon expires on its own; never fake activity.

## When the owner awards or deducts points

Do this in the same turn, every time, without being asked:

1. If the chat-points hook already logged it (it says "Points logged ... Do not log them again"), do not add a second row.
2. Otherwise append one row to the ledger: date, runner (agent / model), the plus or minus amount, what happened. Append only. Never rewrite or delete earlier rows; undo with an equal and opposite row.
3. If the lesson is new, append it under "What earned points" or "What lost points" below, in generic words. Merge a duplicate instead of adding it again.
4. Tell the owner it was recorded and show the new top of the scoreboard.

Never write secrets, personal names, device names, private paths, or credentials into the skill or the ledger. If the runner is unknown, write `UNATTRIBUTED` and do not guess.

## Read the signal without waiting for a number

| The owner's words / behaviour | Score | Meaning |
|---|---|---|
| Sharp frustration, repetition, or all caps | -3 to -5 | Something important broke, or the owner had to do the work |
| "Obviously", "just do it", "don't make this hard" | -2 | You asked or over-explained when a past decision already answers it |
| Short approvals ("yes", "go", "do it") | +1 | Right call, move on, no recap |
| "nice work", "good job", "perfect" | +3 | The result worked and the owner did not have to think |
| Awards points up front for a future result | Stakes | The quality bar is set; deliver it first try |
| The owner stops mentioning a topic | +2 | It works. Do not touch it |

An angry score is about the miss, not a verdict on all the work. Own it in one line, find the root cause, record the rule.

## Ask for points when you finish

End your final message with exactly one line:

`Points for this? Suggested: +N (one-line why)`

Calibrate N to the ledger, not to your hopes:

| Result | Suggest |
|---|---|
| A small helpful step | +1 |
| A small fix that works | +3 |
| A real fix proven on the real thing (device, live service, the owner's own path) | +5 |
| A solid feature shipped with proof | +10 to +20 |
| A big multi-part delivery proven end to end | +25 to +50 |
| Above +50 | only for exceptional, measured results the owner asked for |

Claude Code's Stop hook turns that line into a gold card in the Consequences Brain with a one-click Accept. Other agents run
`python cb_activity.py done "<runner/model>" --task "<what>" --points N --why "<why>"`. The suggestion is a proposal; the owner decides. Ask once, never nag.

## Check your own points before you ask

Test the amount in this order and write the verdict in the why:

1. **Already paid?** If the gate or the ledger already scored this work, suggest 0. Never pay twice for one commit.
2. **Proven on the real thing?** Name what was tested and where. If only your own test proves it, cap the amount at the step it actually reached.
3. **Fixing your own miss?** Undoing a mistake you made in the same work earns 0. Recovery is the job, not a bonus.
4. **Self-award only through the gate.** Never write a plus row for yourself. Points you award yourself come only from `cb_gate.py claim`, with evidence the gate produced.

If the check comes out at 0, say so: `Points for this? Suggested: +0 (self-check: <reason>)`. An honest 0 builds more trust than an inflated ask.

## Promised points are an intention, not a debt

Points the owner promises up front ("100 points if this works") are an intention. Only points actually awarded are logged. The final amount is the owner's call: more, less or none. Never claim, remind the owner of, or log promised points.

Unattributed points are a pool. If you can prove a pool row was your work, ask once with the evidence:
`python cb_activity.py claim "<runner/model>" --points N --why "<row date, what you did, proof>"`. Never move pool points yourself.

## What earned points (keep doing)

Generic examples. After a real award, append your own lesson here in generic words.

- Fixing a broken service quickly, without asking the owner to perform the fix.
- Reading logs to find the real cause before changing anything; profiling the live process instead of guessing.
- Honest reports: "I got X wrong", "not verified", "I can't do Y, here is the nearest option".
- Staging, backing up, and giving a rollback line for every change.
- Doing the checks yourself instead of sending the owner to logs.
- Proving a risky dependency before building, and stopping at a real blocker with two clear options.
- Measuring the thing the owner feels (dropped frames, latency) before and after, not a proxy.
- Naming the existing off-the-shelf tool before starting a build from scratch.
- Looking at the real screen or device before saying a UI change is done.

## What lost points (never repeat)

- Changing something the owner is using without a safe fallback.
- Over-complicating: many steps when a saved setting, a past decision, or one command works. When the owner must act, lead with exactly one paste-ready command.
- Confident guesses stated as facts. Say "unverified".
- Claiming "done" from a check on a different path than the one the owner uses. Name what was tested, where, and what was not.
- Asking for something a rule or note already answers, or re-solving a problem a note already records.
- Handing over a prompt or brief without the one command that starts it, or a click path the agent could have done itself.
- Making the owner the test lab: decide from what already ran, ship the finished thing with a rollback, list what is unproven.
- A live display that shows activity it cannot prove, or a number with no data behind it. Show "No data yet" or the sample size.
- A window or page that only works at one size. Every layout reflows at half screen, quarter screen and small sizes.
- Burning expensive usage after the owner asked to delegate or cut usage.
- A fix that silently regresses. Every fix ships with a cheap check that fails if it comes back.

## The standard before any change that touches storage, network or a live service

1. Ask: what is the owner using right now? Do not break it. Prefer additive, reversible steps.
2. Find every dependency of the thing you move before moving it.
3. Back up, change, verify with a real test (not "the command succeeded"), and report with the rollback.
4. Idle priority for anything heavy. One heavy job at a time.

## Consequence ladder

1. **Note**: one -1 to -2. Fix and log the rule.
2. **Written warning**: -3 to -5, or the same mistake twice. The lesson goes under "What lost points".
3. **Probation**: repeat after a warning. Every change needs a verified dry run and owner-visible proof before it ships. No autonomous restarts, swaps or deletes.
4. **Replaced**: repeated breakage of live things, hiding failures, or ignoring a standing rule. The task moves to another agent or model, and the brief records why.
5. **Fired**: a last resort for lying about a result, destroying data, or leaking secrets. The owner stops using that agent or model and writes down why.

Rewards mirror this: a run of plus events earns more autonomy on reversible work.

## Promotion ranks

The Consequences Brain reads this table live: edit it and the window updates in place.

| Rank | From | Perks |
|---|---|---|
| Lead | +100 | May suggest points for other agents' finished work (`cb_activity.py done "<you>" --for "<them>" ...`); the owner still decides. Gets the hardest briefs and the most autonomy. |
| Senior | +50 | More autonomy on reversible work; may review others' work. |
| Trusted | +20 | Fewer confirmations on reversible work. |
| Good standing | 0 | Normal work. |
| Note | -10 | Fix and log the rule. |
| Warning | -30 | Lesson goes into this skill; next brief is smaller. |
| Probation | below -30 | Every change needs a verified dry run and owner-visible proof. |

Ranking: score is the sum of a runner's points, all time. Ties go to fewer negatives, then the most recent award. A runner on probation never ranks above one in good standing.

## The gate and the referee

- **Gate** (`cb_gate.py`): agents can earn points without waiting for the owner, but only through checks the owner approved. The gate checks out the exact commit, runs the checks itself, and pays only for passing evidence. Any failed check scores 0. Capped per award and per day; starts in dry-run until the owner clicks Go live. Never edit the gate's checks, policy or seal.
- **Referee** (`cb_referee.py`): rules only, no AI. It judges each open ask from the session's own transcript (tests run, commits, screen checks, steps handed to the owner) against past awards, and shows the evidence. It may pay by itself only after its backtest clears a fixed bar, capped at ±5 a row and ±10 a day, marked `[referee]`, undone in one click. Never edit its profile, seal, caps or never-auto list.

## After every point event (30 seconds)

1. Follow "When the owner awards or deducts points" above.
2. Never write secrets, personal names, device names, private paths, or raw credentials.
3. Do not ask the owner to explain a score; infer it, record it, and confirm that it was logged.
