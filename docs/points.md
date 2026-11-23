# Points bank

The optional CLI uses Node.js 22 or later and no packages. Run `node addons/points/points.mjs` or use the PowerShell or Bash wrapper in the same directory. Give the agent the [add-on skill](../addons/points/SKILL.md) to enable the conversation workflow.

| Platform | Default data folder |
| --- | --- |
| Windows | `%LOCALAPPDATA%\ship-gate` |
| macOS | `~/Library/Application Support/ship-gate` |
| Linux | `$XDG_DATA_HOME/ship-gate` or `~/.local/share/ship-gate` |

Override with `SHIP_GATE_DATA_DIR` or pass `--data-dir DIR` per command. The CLI creates the folder on the first award. Rules are optional. Put `rules.json` next to `ledger.jsonl` to enable tagging and ranking.

```bash
bash addons/points/points.sh award agent-a package -3 "Missed an entrypoint check" --tag smoke-test
bash addons/points/points.sh ledger
bash addons/points/points.sh board
bash addons/points/points.sh lessons --agent agent-a
bash addons/points/points.sh export --output export.json
```

The award example assumes a local `smoke-test` rule. Without rules, omit the tag. If keyword suggestions are available, the CLI prints a proposal and returns 2 before writing. Repeat the command with confirmed tags or `--no-tags`. Repeat `--tag` to link multiple rules. The source is `owner` by default and `auto` when the agent records an explicit award through the conversation hook.

Every event has a UTC timestamp, agent, task, signed integer points, reason, source and tags. Treat the ledger as append-only. Agent and task totals are all-time through the cutoff, trends sum the last 7 and 30 UTC calendar days, and streaks count the most recent consecutive awards of the same sign. Most-docked rules count tagged negative events.

Archive the data folder for backup. If an interrupted writer leaves `ledger.lock`, check that no writer is active before removing that file. Inspect the ledger before retrying an interrupted award. The CLI reports the line number for invalid ledger data.

## Generate the sample charts

```bash
node addons/points/points.mjs charts --data-dir templates/points --as-of 2026-11-23 --output docs/previews
```

[Dashboard](previews/dashboard.svg) · [Scoreboard](previews/scoreboard.svg) · [Daily points](previews/points-over-time.svg) · [Calendar](previews/heatmap.svg) · [Rule strength](previews/rule-strength.svg)

Charts are standalone SVGs with no external fonts or network dependencies. For real data, use a private output directory.
