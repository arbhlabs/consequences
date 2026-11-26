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
| 0 | Trusted | The agent works as usual. |
| 1 | Warning | The agent says what went wrong, in one line. It fixes the work and the gate, and adds a checklist line so that mistake is harder to repeat. |
| 2 | Probation | The agent cannot call the work "done" until the owner has seen the proof. Every handoff must include the full gate result and a screenshot. |
| 3 | Reassigned | This work goes to another agent or a stronger model. The original agent only does small, reviewed, low-risk tasks. |
| 4+ | Fired | Last resort. The owner stops using that agent or model. |

Fired is a last resort, and it has not been needed yet. If an agent or model keeps missing what was asked, or keeps frustrating the owner, the owner stops using it. In an extreme case, the owner could uninstall the program. Lessons already written in the checklist stay there.

A strike for the **same class** of mistake already in the checklist counts double. A clean streak of 10 gated handoffs clears one strike.

Before every handoff, read `STRIKES.md` and state your current status in the report (for example "Status: Probation, 2 strikes").

