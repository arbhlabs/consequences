# Release checklist: sample report

## Gate
- [x] Artifact tested is the exact file the owner gets
- [x] Every referenced path exists in the artifact
- [x] Real entry point run once, exit code 0
- [x] No secrets in the artifact

## Lessons (one line per past miss, newest last)
- 2026-11-26: shipped a report without VERSION -> smoke test requires VERSION
