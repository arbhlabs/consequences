---
name: ship-gate
description: >-
  Use before handing ANY deliverable to the owner (build, installer, ISO, app,
  page, post, file, script, report): a cheap scripted release gate, the cost of
  a miss, and how to log it so the same mistake never ships twice. Mandatory for
  every AI agent doing work for the owner.
version: 1.5.0
---
# Ship gate: nothing broken reaches the owner

The owner is the customer, not the test lab. A deliverable that fails on their screen is a production defect. It wastes their time and money (usage), and in a real company whoever shipped it would answer for it. The owner decides the consequences. Treat every handoff as a release to production.

## The rule
Only hand something over when a script has proved that the exact thing the owner will use works. "Probably fine", "preflight passed" on a different artifact, and "it worked last time" are not proof.

## The gate (cheap, scripted, no AI review)
1. **Test the artifact, not the source.** Check the built output the owner will actually run (the installed app, the extracted ISO, the live page), never only the build folder.
2. **Every reference resolves.** Run a project-specific reference checker for every path, file, command, URL and required environment variable the deliverable uses. A missing reference fails the gate.
3. **Run the real entry point once.** Run a project-specific smoke script against the exact deliverable (container, staged copy, emulator or device), not a simulation of it. It must exit 0.
4. **Look at it.** For anything with a screen, capture a screenshot of the real thing, open it and inspect it. If it shows placeholders, `--`, errors, empty lists, overlap or clipping, the gate fails, whatever the logs say.
5. **Match the checklist.** Run the project's checklist for this kind of deliverable (`CHECKLIST.md` or your notes vault). Every checkbox must be completed; every lessons-learned line must be addressed.
6. **Report the proof.** Give the filename, hash or version, gate result (pass X/X), smoke-run exit code and screenshot path. Without proof, say "not ready" instead of "done".

## Deterministic gate runner
The installed skill includes `templates/gate.sh` and `templates/CHECKLIST.md`; the Windows and macOS/Linux installers place them alongside `SKILL.md`. Invoke the runner by its installed path (or copy it into the project), adjusted for the active agent's skill directory. It requires explicit project-specific helpers; it does not accept shell command strings:

```bash
bash "$HOME/.claude/skills/ship-gate/templates/gate.sh" ./dist/deliverable \
  --refs-check ./scripts/check-refs.sh \
  --smoke-script ./scripts/smoke-test.sh \
  --checklist ./CHECKLIST.md
```

For a screen-based deliverable, open and inspect the screenshot first, then add:

```bash
  --ui --screenshot ./artifacts/release.png --visual-reviewed
```

The reference-check and smoke-test files must be real Bash scripts. Each receives the artifact path as its first argument and must return a nonzero exit code on failure. They must inspect the exact artifact being handed over, not merely source files or an earlier build. Do not use `eval`, `sh -c` command strings, or hardcoded success output in helper scripts.

The runner checks artifact existence, obvious secret-assignment patterns, the reference helper, the smoke helper, and completion of the Markdown checklist. For UI deliverables it also checks that a screenshot file exists and that visual review was explicitly attested. **The runner cannot inspect image pixels or prove that a person opened the screenshot**; the agent must genuinely open and inspect it before passing `--visual-reviewed`. The secret scan is a heuristic, not a substitute for secret-management tooling, and does not scan Git history.

Run the regression suite after changing the runner:

```bash
bash tests/test-gate.sh
```

## Budget (don't waste the owner's money)
- The gate is scripts, not extra AI passes. No extra research, second reviewers or repeated dry runs unless a script flagged something.
- Build the gate once per deliverable type and rerun it forever.
- If the gate costs more than the deliverable, shrink the gate, but never skip steps 1 to 4.

## When a defect gets through anyway
1. **Own it in one line:** what broke and why the gate missed it. No excuses or padding.
2. **Fix the artifact and the gate in the same pass,** so the gate would now catch it.
3. **Add one line to the checklist / lessons file** for that deliverable type, so the mistake can't repeat.
4. **The owner decides any consequence.** Never argue with it or repeat the mistake.

## Consequences
The owner decides how to respond to a missed handoff. If the optional points add-on is configured, read its active rules at task start and follow its workflow when the owner gives feedback.

## Never
- Never say done, ready, fixed or passed without the proof from step 6.
- Never claim PASS for a screen you did not look at.
- Never hand the owner a fix that needs typing or extra clicks from them when a scripted path exists.
- Never ship the same class of mistake twice.

## Lessons from fixes that worked (keep doing these)
- **Root cause from the logs first.** Read the server, app or crash log before changing anything. One log line (for example a 401 from an auth parameter the server no longer accepts) beats three guesses.
- **Tap every new button on the real device** and check its crash log before the handoff.
- **Look before a visual change goes live.** For camera, picture or UI settings, save one test frame or screenshot with the new setting and check it first. A setting that "should" brighten can posterize the image.
- **Smoke-run any helper script once yourself** before handing it over. Its very first run must not be on the owner's screen.
- **One-shot commands for the owner:** one paste, absolute paths everywhere (.NET file calls in PowerShell ignore `cd`), back up what it changes, print a clear success line, and roll itself back automatically if the build or check fails.
- **Small in-place fixes:** one edit, one build or restart, then verify. Don't rewrite things that already work.
