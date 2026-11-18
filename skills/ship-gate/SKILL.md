---
name: ship-gate
description: >-
  Use before handing ANY deliverable to the owner (build, installer, ISO, app,
  page, post, file, script, report): a cheap scripted release gate, the cost of
  a miss, and how to log it so the same mistake never ships twice. Mandatory for
  every AI agent doing work for the owner.
version: 1.0.0
---
# Ship gate: nothing broken reaches the owner

The owner is the customer, not the test lab. A deliverable that fails on their screen is a production defect. It wastes their time and money (usage), and in a real company whoever shipped it would answer for it. The owner decides the consequences. Treat every handoff as a release to production.

## The rule
Only hand something over when a script has proved that the exact thing the owner will use works. "Probably fine", "preflight passed" on a different artifact, and "it worked last time" are not proof.

## The gate (cheap, scripted, no AI review)
1. **Test the artifact, not the source.** Check the built output the owner will actually run (the installed app, the extracted ISO, the live page), never only the build folder.
2. **Every reference resolves.** Script it: every path, file, command, URL and env var the deliverable copies, sources, runs or links must exist inside the artifact. One missing file is a failed gate.
3. **Run the real entry point once.** Do a single smoke run of the actual install, launch or flow (container, staged copy, emulator or device), not a simulation of it. It must exit 0.
4. **Look at it.** For anything with a screen, capture a screenshot of the real thing and open it. If it shows placeholders, `--`, errors, empty lists, overlap or clipping, the gate fails, whatever the logs say.
5. **Match the checklist.** Run the project's checklist for this kind of deliverable (`CHECKLIST.md` or your notes vault) as a script, including every lessons-learned line.
6. **Report the proof.** Give the filename, hash or version, gate result (pass X/X), smoke-run exit code and screenshot path. Without proof, say "not ready" instead of "done".

## Budget (don't waste the owner's money)
- The gate is scripts, not extra AI passes. No extra research, second reviewers or repeated dry runs unless a script flagged something.
- Build the gate once per deliverable type and rerun it forever.
- If the gate costs more than the deliverable, shrink the gate, but never skip steps 1 to 4.

## When a defect gets through anyway
1. **Own it in one line:** what broke and why the gate missed it. No excuses or padding.
2. **Fix the artifact and the gate in the same pass,** so the gate would now catch it.
3. **Add one line to the checklist / lessons file** for that deliverable type, so the mistake can't repeat.
4. **The owner decides any consequence:** reassigning the work, switching models or agents, or dropping the agent. Never argue with it or repeat the mistake.

## Never
- Never say done, ready, fixed or passed without the proof from step 6.
- Never claim PASS for a screen you did not look at.
- Never hand the owner a fix that needs typing or extra clicks from them when a scripted path exists.
- Never ship the same class of mistake twice.
