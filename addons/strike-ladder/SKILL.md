---
name: ship-gate-strike-ladder
description: >-
  Optional add-on to ship-gate for teams that want explicit, visible
  consequences: a strike log and a Warning, Probation, Reassigned, Fired ladder.
version: 1.2.0
---
# Ship-gate add-on: strike ladder

Use together with `ship-gate`. Most owners don't need this: ship-gate works best when consequences are real but unspecified. Add this only if you want them written out.

## Strike ladder
Every defect that reaches the owner is a **strike**, logged in `STRIKES.md` (date, agent/model, what broke, gate line added). Strikes decide what happens next. The owner can skip or override any step.

| Strikes (rolling 30 days) | Status | What happens |
|---|---|---|
| 0 | Trusted | Normal autonomy. |
| 1 | Warning | Owns it in one line, fixes artifact + gate, adds a checklist line. |
| 2 | Probation | Every handoff must attach full gate proof and a screenshot; no "done" without the owner seeing it. |
| 3 | Reassigned | Work moves to another agent or a stronger model; this agent only does reviewed, low-risk tasks. |
| 4+ | Fired | Agent or model is removed from the project. Its lessons stay in the checklist. |

A strike for the **same class** of mistake already in the checklist counts double. A clean streak of 10 gated handoffs clears one strike.

Before every handoff, read `STRIKES.md` and state your current status in the report (for example "Status: Probation, 2 strikes").

