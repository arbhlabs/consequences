# Strike log

Agents read this before every handoff and state their status. Rolling 30-day window. Same class of mistake = 2 strikes. 10 clean handoffs clear 1 strike.

| Date | Agent / model | What reached the owner broken | Gate line added | Strikes now | Status |
|---|---|---|---|---|---|
| 2026-01-01 | example-agent / model-x | Said "all tabs PASS"; app showed `--` and HTTP 401 | Step 4: open the real screenshot before PASS | 1 | Warning |
