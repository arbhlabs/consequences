# Gate concepts

A deliverable is the exact file, directory, or packaged entry point the owner will use. Choose tests that match where and how the owner will run it.

```bash
bash templates/gate.sh ./dist/deliverable \
  --refs-check ./scripts/check-refs.sh \
  --smoke-script ./scripts/smoke-test.sh \
  --checklist ./CHECKLIST.md
```

Both helpers receive the deliverable path as their first argument and must return nonzero on failure. The reference helper checks files and dependencies. The smoke helper runs the packaged entry point and checks its actual behavior. The gate also checks basic secret patterns and requires completed checklist items. See the [runner](../templates/gate.sh) for its supported options.

For UI work, open a real screenshot of the artifact, then pass `--ui --screenshot ./review.png --visual-reviewed`. Review legibility, clipping, placeholders and errors before attesting.

The [package demo](../examples/package-demo.sh) contains a launcher that expects config in the current directory. Both files are present, but launching from a fresh directory fails. The fix resolves config relative to the launcher. The regression check runs the same packaged entry point from outside the package on future releases.

A failed gate blocks the handoff. A successful handoff includes the artifact name, hash, gate result, smoke exit code and screenshot path when applicable. If a defect reaches the owner, fix the artifact and add the check that would have caught it.
