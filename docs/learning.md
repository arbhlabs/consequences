# Weighted rule memory

Ship-gate uses transparent weighted rule memory with reinforcement. A fixed formula replays explicit awards from the local ledger. There is no trained neural network, model training, or network call.

## Rule file

Edit the local `rules.json` in a text editor. See the [sample rules](../templates/points/rules.json) for the schema. Each rule has a stable hyphenated lowercase `id`, short `text`, a list of `keywords`, a UTC ISO `created` timestamp, and a nonnegative numeric starting `weight`. Keep IDs stable so historical links still resolve. Change the starting weight to tune priority. The CLI recalculates derived weights and counters on every read.

- Between events, multiply by `0.95^(elapsed days / 7)`.
- For a dock, add the absolute award value capped at 10. For a gain, add half that amount.
- Apply the increment to each confirmed rule tag and increment that rule's event counter once. Each linked dock also increments the dock counter.
- Sort by weight descending, then ID. Inactive rules remain in the file.

For example, a rule at weight 2 that gets a dock of 4 rises to 6. With no new events for seven days it falls to 5.70. An award of +4 at that point raises it to 7.70.

The default active list is five rules. Set `--top K` to select 1–50. Run `lessons --active-only --agent <agent>` before a task for the active list and up to three rules most often docked for that agent. A plain `lessons` regenerates the weekly Markdown digest at read time, comparing the current weights with those seven days ago and listing new rules and changes of at least 0.01. Redirect it to a file for a snapshot.

An untagged reason can suggest up to three rules by shared case-insensitive words of at least three ASCII letters or digits. Confirm the match before recording. If a defect has no matching rule, turn the confirmed lesson into a short rule and a check in the actual gate.
