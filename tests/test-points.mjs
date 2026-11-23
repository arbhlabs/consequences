import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { DAY, propose, readLedger, record, suggest, weigh } from '../addons/points/points.mjs';

const now = Date.parse('2026-11-20T00:00:00.000Z');
const timestamp = new Date(now).toISOString();
const rule = { id: 'smoke-test', text: 'Run the executable smoke test.', keywords: ['entrypoint'], created: timestamp, weight: 2 };
const other = { ...rule, id: 'refs', text: 'Check references.', keywords: [] };
const event = { timestamp, agent: 'agent-a', task: 'package', points: -4, reason: 'Missed entrypoint', source: 'owner', tags: [rule.id] };

function directory(context) {
  const path = mkdtempSync(join(tmpdir(), 'ship-gate-test-'));
  context.after(() => rmSync(path, { recursive: true }));
  return path;
}

test('weights reinforce on gains and docks, decay and keep historical counters', () => {
  const weights = weigh([rule, other], [event, { ...event, points: 4 }], now + 7 * DAY);
  assert.deepEqual(weights.map(item => item.id), [rule.id, other.id]);
  assert.equal(weights[0].weight, 8 * 0.95);
  assert.equal(weights[0].counter, 2);
  assert.equal(weights[0].docks, 1);
  assert.equal(weights[1].weight, 2 * 0.95);
  assert.equal(weigh([rule], [event], now + 365 * DAY)[0].counter, 1);
  assert.equal(weigh([rule], [], now - DAY).length, 0);
});

test('suggestions and tone never write or infer an award', () => {
  assert.deepEqual(suggest([other, rule], event.reason).map(item => item.id), [rule.id]);
  assert.deepEqual(propose('-4 points: missed entrypoint'), {
    status: 'review-award', points: -4, reason: 'missed entrypoint',
  });
  assert.deepEqual(propose('Nice work'), { status: 'praise' });
  assert.deepEqual(propose('Good job, +5 points for checking the package.'), {
    status: 'confirm-mention', candidates: [5],
  });
  assert.deepEqual(propose('+5 points if it works'), { status: 'no-award' });
});

test('ledger round trip, lock contention and malformed tail', context => {
  const dir = directory(context);
  const path = join(dir, 'ledger.jsonl');
  record(dir, event);
  record(dir, { ...event, points: 2 });
  assert.deepEqual(readLedger(path), [event, { ...event, points: 2 }]);
  writeFileSync(join(dir, 'ledger.lock'), '');
  assert.throws(() => record(dir, event), { code: 'EEXIST' });
  assert.equal(readLedger(path).length, 2);
  writeFileSync(path, '{broken');
  assert.throws(() => readLedger(path), /line 1/);
});

test('CLI proposes tags, records once, exports, caps rules and renders SVG', context => {
  const dir = directory(context);
  const run = (...args) => spawnSync(process.execPath, [
    'addons/points/points.mjs', ...args, '--data-dir', dir,
  ], { encoding: 'utf8' });
  writeFileSync(join(dir, 'rules.json'), JSON.stringify([rule, other]));
  const proposal = run('propose', '-4 points: missed entrypoint');
  assert.equal(proposal.status, 0, proposal.stderr);
  assert.equal(JSON.parse(proposal.stdout).points, -4);
  const suggestion = run('award', 'agent-a', 'package', '-4', 'Missed entrypoint');
  assert.equal(suggestion.status, 2, suggestion.stderr);
  assert.match(suggestion.stdout, /Confirm rule tags: smoke-test/);
  assert.equal(run('ledger').stdout, '');
  const award = run('award', 'agent-a', 'package', '-4', 'Missed entrypoint', '--tag', rule.id);
  assert.equal(award.status, 0, award.stderr);
  const exported = JSON.parse(run('export').stdout);
  assert.equal(exported.events.length, 1);
  assert.equal(exported.agents[0].total, -4);
  assert.equal(exported.tasks[0].total, -4);
  assert.equal(exported.weights[0].counter, 1);
  const digest = run('lessons', '--active-only', '--top', '1', '--agent', 'agent-a');
  assert.equal(digest.status, 0, digest.stderr);
  assert.match(digest.stdout, /Watch out for\n- smoke-test/);
  assert.doesNotMatch(digest.stdout, /- refs/);
  assert.equal(run('charts', '--output', dir).status, 0);
  const svgs = readdirSync(dir).filter(file => file.endsWith('.svg'));
  assert.equal(svgs.length, 5);
  for (const file of svgs) assert.match(readFileSync(join(dir, file), 'utf8'), /<svg .*<title/);
});
