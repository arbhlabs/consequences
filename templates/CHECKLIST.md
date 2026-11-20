# Release checklist: <deliverable type>

Run as a script where possible. Every miss that reaches the owner adds one line under "Lessons". The gate runner requires all checklist boxes to be checked before handoff.

## Gate
- [ ] Artifact tested is the exact file/page/app the owner gets (name + hash/version recorded)
- [ ] Every referenced path, file, URL and env var exists in the artifact
- [ ] Real entry point run once, exit code 0
- [ ] Screenshot of the real screen opened and checked: no placeholders, errors, empty lists, overlap
- [ ] No secrets, PINs or keys in the artifact; audit Git history separately when required

## Lessons (one line per past miss, newest last)
- YYYY-MM-DD: <what broke> -> <check that now catches it>