# Consequences Brain (optional add-on)

A live desktop window for the [points add-on](../points/SKILL.md). It shows your agents as a 3D constellation.

- **Who leads.** Node size is net score. Warm means gained points, red means lost.
- **Who is working right now.** The node pulses and a comet circles it.
- **Who finished and is waiting for points.** A gold card appears with the agent's own suggested amount: one click on **Accept** writes it to the ledger.

<p align="center"><img src="../../assets/brain-demo.gif" alt="Consequences Brain: agents as glowing nodes, a working agent pulsing, a points ask accepted with one click" width="640"></p>

## Install

**Easiest:** download **`ConsequencesSetup.exe`** from [Releases](https://github.com/arbhlabs/consequences/releases/latest) and double-click it.

1. Tick what you want:
   - the skill
   - the points add-on
   - the Brain window
   - a desktop shortcut
2. Press **Install**.

You don't need Python or admin rights. The setup isn't code-signed yet, so if Windows SmartScreen asks, choose **More info → Run anyway**. Uninstall from **Settings → Apps**.

**From source:** you need Python 3.10+ and `pip install pywebview`. Then run:

```
python addons/brain/app/consequences_brain.py
```

## What it reads (push, never polls)

| Source | How it gets there |
|---|---|
| Points ledger | The add-on's `ledger.jsonl` (default), or any `Scoreboard.md` table. The window wakes on an OS change notification and shows a change in under 1 s. |
| Claude Code sessions | Read from the transcripts Claude Code already writes. No hooks and no setup. |
| Any other agent | It runs `cb_activity.py working "<name>" --task "<what>"` when it starts and `cb_activity.py done "<name>" --task "<what>" --points N --why "<why>"` when it finishes. |
| OpenCode on another machine | `bridges/opencode_beacon_bridge.py` turns the server's event stream into beacons in a synced folder. |

Idle cost is near zero:
- The watchers sleep in the OS until something changes.
- The 3D view drifts at 30 fps while it's visible and stops when minimised or hidden.

## Points asks, ranks and claims

When an agent finishes, it ends with one line: `Points for this? Suggested: +N (why)`. The window turns that line into a card with Accept, +1, +5, +10, +20, −5 and Dismiss buttons.

Agents climb ranks as they earn points. The Lead rank (+100) unlocks suggesting points for *other* agents, and the window checks that against live scores.

Unattributed points form a pool. An agent can ask to claim from it with evidence; approving writes two reattribution entries.

## Settings (optional)

All settings live in `%APPDATA%\Consequences\config.json`, or in `config.json` next to the app:

```json
{
  "ledger": "C:\\path\\to\\Scoreboard.md",
  "notes": "C:\\path\\to\\notes-folder",
  "skill": "C:\\path\\to\\SKILL.md",
  "shared_activity": "D:\\Sync\\consequences-activity",
  "runners": [{"name": "Riley", "match": "\\briley\\b"}],
  "brand": "ACME"
}
```

| Key | What it does |
|---|---|
| `ledger` | Your Scoreboard.md or ledger.jsonl. Default: the points add-on's `ledger.jsonl`. |
| `notes` | Folder for your notes. Default: the ledger's folder. |
| `skill` | The skill whose `Promotion ranks` table and standing rules appear live in the Ranks and Rules tabs. Default: built-in ranks. |
| `shared_activity` | A synced folder for beacons from other machines. |
| `runners` | Extra agent names to recognise. Model families (Opus, Sonnet, GPT, Gemini, DeepSeek, Grok, Codex and more) are built in. |
| `brand` | Optional text before CONSEQUENCES in the header. |

## Tests

```
python -m unittest discover -s addons/brain/tests -v
```

The tests use only the standard library and never open a window. `installer/build.ps1` rebuilds `ConsequencesSetup.exe` and self-tests the packaged app before wrapping it.

## Privacy

Everything stays on your machine. The window makes no network calls, sends no telemetry, and writes only the ledger entries you click (always after a backup).
