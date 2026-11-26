# Sample deliverable

A tiny artifact used to exercise `templates/gate.sh`. The committed tree is the passing state. The demo recording starts from a miss: no `dist/VERSION`, and `CHECKLIST.fail.md` still has an open checkbox.

From this directory:

```bash
bash ../../templates/gate.sh ./dist \
  --refs-check ./scripts/check-refs.sh \
  --smoke-script ./scripts/smoke-test.sh \
  --checklist ./CHECKLIST.md
```

To reproduce the failing run, temporarily move `dist/VERSION` aside and point `--checklist` at `CHECKLIST.fail.md`.
