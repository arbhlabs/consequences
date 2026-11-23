import { appendFileSync, closeSync, existsSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { pathToFileURL } from 'node:url';
import { charts } from './visuals.mjs';

export const DAY = 86400000;
const utcDay = time => Math.floor(time / DAY);
const sum = events => events.reduce((total, event) => total + event.points, 0);
const json = value => JSON.stringify(value, null, 2);
const textField = value => typeof value === 'string' && value.trim() && !/[\x00-\x1f\x7f-\x9f]/u.test(value);
const tagField = value => typeof value === 'string' && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value);
const dayLabel = day => new Date(day * DAY).toISOString().slice(0, 10);

const defaults = {
  win32: process.env.LOCALAPPDATA || join(homedir(), 'AppData', 'Local'),
  darwin: join(homedir(), 'Library', 'Application Support'),
};
const defaultDir = process.env.SHIP_GATE_DATA_DIR || join(
  defaults[process.platform] || process.env.XDG_DATA_HOME || join(homedir(), '.local', 'share'), 'ship-gate',
);

export function readLedger(path) {
  if (!existsSync(path)) return [];
  return readFileSync(path, 'utf8').split('\n').flatMap((line, index) => {
    if (!line.trim()) return [];
    try {
      const event = JSON.parse(line);
      validateEvent(event);
      return [event];
    } catch {
      throw new Error('Invalid ledger event on line ' + (index + 1));
    }
  });
}

function validateEvent({ timestamp, agent, task, points, reason, source, tags }) {
  if (![agent, task, reason].every(textField) || !Number.isSafeInteger(points) ||
      !points || Math.abs(points) > 1000000 || !['owner', 'auto'].includes(source) ||
      !Array.isArray(tags) || !tags.every(tagField) || new Set(tags).size !== tags.length ||
      !Number.isFinite(Date.parse(timestamp)) || new Date(timestamp).toISOString() !== timestamp) {
    throw new Error('Use nonempty plain text, signed whole points up to 1000000, and unique lowercase rule IDs.');
  }
}

export function record(directory, event) {
  validateEvent(event);
  mkdirSync(directory, { recursive: true });
  const path = join(directory, 'ledger.jsonl');
  // A lock excludes concurrent writers, including while checking the final line.
  const lockPath = join(directory, 'ledger.lock');
  const lock = openSync(lockPath, 'wx', 0o600);
  try {
    readLedger(path);
    const needsNewline = existsSync(path) && /[^\n]$/.test(readFileSync(path, 'utf8'));
    appendFileSync(path, (needsNewline ? '\n' : '') + JSON.stringify(event) + '\n', { mode: 0o600 });
  } finally {
    closeSync(lock);
    unlinkSync(lockPath);
  }
}

export function weigh(rules, events, now) {
  return rules.filter(rule => Date.parse(rule.created) <= now).map(rule => {
    const created = Date.parse(rule.created);
    let last = created;
    let weight = rule.weight;
    let counter = 0;
    let docks = 0;
    const decay = time => { weight *= 0.95 ** ((time - last) / (7 * DAY)); last = time; };
    const linked = events.filter(event => event.tags.includes(rule.id))
      .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp));
    for (const event of linked) {
      const time = Date.parse(event.timestamp);
      if (time > now) break;
      decay(Math.max(time, created));
      weight += Math.min(10, Math.abs(event.points)) * (event.points < 0 ? 1 : 0.5);
      counter++;
      if (event.points < 0) docks++;
    }
    decay(now);
    return { id: rule.id, text: rule.text, weight, counter, docks };
  }).sort((left, right) => right.weight - left.weight || left.id.localeCompare(right.id));
}

const words = value => new Set(value.toLowerCase().match(/[a-z0-9]{3,}/g) || []);
export function suggest(rules, reason) {
  const query = words(reason);
  return rules.map(rule => ({
    id: rule.id, text: rule.text,
    overlap: [...words([rule.id, rule.text, ...rule.keywords].join(' '))]
      .filter(word => query.has(word)).length,
  })).filter(rule => rule.overlap).sort((left, right) =>
    right.overlap - left.overlap || left.id.localeCompare(right.id)).slice(0, 3);
}

export function propose(message) {
  const match = /^([+-]\d+)\s+points?\b(?:\s*[:–—-]\s*(.+))?\s*$/iu.exec(message.trim());
  if (match && Number(match[1]) && Math.abs(Number(match[1])) <= 1000000) {
    return { status: 'review-award', points: Number(match[1]), reason: match[2] || null };
  }
  const mentions = [...message.matchAll(/(?<![\w+-])([+-]\d+)\s+points?\b/giu)]
    .map(mention => Number(mention[1])).filter(points => points && Math.abs(points) <= 1000000);
  if (mentions.length && !/^\s*[+-]\d+\s+points?\b/iu.test(message)) {
    return { status: 'confirm-mention', candidates: mentions };
  }
  if (/\b(?:nice work|good job|well done|perfect)\b/i.test(message)) return { status: 'praise' };
  if (/\b(?:unacceptable|ridiculous|come on|fix this)\b/i.test(message)) return { status: 'frustration' };
  return { status: 'no-award' };
}

function loadRules(path) {
  if (!existsSync(path)) return [];
  const rules = JSON.parse(readFileSync(path, 'utf8'));
  if (!Array.isArray(rules) || !rules.every(rule =>
    tagField(rule.id) && textField(rule.text) && Number.isFinite(rule.weight) &&
    rule.weight >= 0 && rule.weight <= 1000000 && Number.isFinite(Date.parse(rule.created)) &&
    Array.isArray(rule.keywords) && rule.keywords.every(textField)) ||
    new Set(rules.map(rule => rule.id)).size !== rules.length) {
    throw new Error('Invalid rules JSON. See docs/learning.md for the rule schema.');
  }
  return rules;
}

function summarize(events, now) {
  const groups = field => Map.groupBy(events, event => event[field]);
  const rank = (left, right) => right.total - left.total || left.label.localeCompare(right.label);
  const today = utcDay(now);
  const series = (entries, size) => {
    const totals = new Map();
    for (const event of entries) {
      const day = utcDay(Date.parse(event.timestamp));
      totals.set(day, (totals.get(day) || 0) + event.points);
    }
    return Array.from({ length: size }, (_, index) => {
      const day = today - size + 1 + index;
      return { date: dayLabel(day), total: totals.get(day) || 0 };
    });
  };
  const agents = [...groups('agent')].map(([label, entries]) => {
    const ordered = [...entries].sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp));
    const sign = Math.sign(ordered.at(-1).points);
    let streak = 0;
    for (const event of ordered.reverse()) {
      if (Math.sign(event.points) !== sign) break;
      streak += sign;
    }
    const days = series(entries, 30);
    return { label, total: sum(entries), week: sumDays(days.slice(-7)), month: sumDays(days), days, streak };
  }).sort(rank);
  const tasks = [...groups('task')].map(([label, entries]) => ({ label, total: sum(entries) })).sort(rank);
  const extremes = [...events].sort((left, right) => right.points - left.points);
  const docks = new Map();
  for (const event of events.filter(event => event.points < 0)) {
    for (const tag of event.tags) docks.set(tag, (docks.get(tag) || 0) + 1);
  }
  return { agents, tasks, days: series(events, 30), gains: extremes.filter(event => event.points > 0).slice(0, 3),
    losses: extremes.reverse().filter(event => event.points < 0).slice(0, 3),
    docks: [...docks].sort(([a, countA], [b, countB]) => countB - countA || a.localeCompare(b)) };
}

const sumDays = days => days.reduce((total, day) => total + day.total, 0);
export const signed = value => value > 0 ? '+' + value : String(value);

function board(summary, color) {
  if (!summary.agents.length) return 'No point events yet.';
  const maximum = Math.max(1, ...summary.agents.map(agent => Math.abs(agent.total)));
  const lines = ['Agent balances | last 7 / 30 UTC days | consecutive awards'];
  for (const agent of summary.agents) {
    const blocks = '#'.repeat(Math.ceil(16 * Math.abs(agent.total) / maximum));
    const bar = color && blocks ? '\x1b[' + (agent.total < 0 ? 31 : 32) + 'm' + blocks + '\x1b[0m' : blocks;
    lines.push(agent.label + '  ' + signed(agent.total) + ' ' + bar + '  |  ' +
      signed(agent.week) + ' / ' + signed(agent.month) + '  |  ' + signed(agent.streak));
  }
  lines.push('Task balances', ...summary.tasks.map(task => task.label + '  ' + signed(task.total)));
  for (const [label, entries] of [['Top gains', summary.gains], ['Top losses', summary.losses]]) {
    lines.push(label, ...entries.map(event => signed(event.points) + ' ' + event.agent + ' / ' + event.task + ' | ' + event.reason));
  }
  lines.push('Most-docked rules', ...summary.docks.map(([id, count]) => id + '  ' + count));
  return lines.join('\n');
}

function lessons(rules, events, now, top, agent) {
  const current = weigh(rules, events, now);
  const previous = new Map(weigh(rules, events, now - 7 * DAY).map(rule => [rule.id, rule.weight]));
  const lines = ['# Weekly lessons through ' + dayLabel(utcDay(now))];
  for (const [heading, predicate] of [
    ['New rules', rule => !previous.has(rule.id)],
    ['Stronger rules', rule => rule.weight - previous.get(rule.id) >= 0.01],
    ['Faded rules', rule => previous.get(rule.id) - rule.weight >= 0.01],
  ]) {
    const matching = current.filter(predicate);
    lines.push('', '## ' + heading, ...(matching.length ? matching.map(rule =>
      '- ' + rule.id + ' | ' + (previous.has(rule.id) ? previous.get(rule.id).toFixed(2) + ' → ' : '') +
      rule.weight.toFixed(2)) : ['None']));
  }
  lines.push('', '## Active rules', ...current.slice(0, top).map(rule =>
    '- ' + rule.id + ' | weight ' + rule.weight.toFixed(2) + ' | ' + rule.counter + ' events | ' + rule.text));
  if (agent) {
    const profile = weigh(rules, events.filter(event => event.agent === agent), now)
      .filter(rule => rule.docks).sort((left, right) => right.docks - left.docks);
    lines.push('', '## Watch out for', ...profile.slice(0, Math.min(3, top)).map(rule =>
      '- ' + rule.id + ' | ' + rule.docks + ' docks | ' + rule.text));
  }
  return lines.join('\n');
}

function main() {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      'data-dir': { type: 'string' }, source: { type: 'string', default: 'owner' },
      tag: { type: 'string', multiple: true, default: [] }, 'no-tags': { type: 'boolean' },
      'as-of': { type: 'string' }, top: { type: 'string', default: '5' },
      agent: { type: 'string' }, output: { type: 'string' },
      'active-only': { type: 'boolean' }, help: { type: 'boolean', short: 'h' },
    },
    args: process.argv.slice(2).map((arg, index, args) => {
      const signedAward = args[0] === 'award' && index === 3 && /^-\d+$/.test(arg);
      const signedMessage = args[0] === 'propose' && index === 1 && /^-\d+\s/.test(arg);
      return signedAward || signedMessage ? '\u0000' + arg : arg;
    }),
  });
  const [command, ...args] = positionals.map(arg => arg.replace(/^\u0000/, ''));
  if (!command || values.help) {
    console.log('points award <agent> <task> <+/-n> "<reason>" [--tag RULE ... | --no-tags]\n' +
      'points ledger | board | lessons [--agent AGENT] [--top K] [--active-only] | export | charts --output DIR\n' +
      'points propose "<owner message>" | suggest "<reason>"\nUse --data-dir DIR to select an isolated data folder.');
    return;
  }
  const directory = values['data-dir'] || defaultDir;
  const path = join(directory, 'ledger.jsonl');
  const rules = loadRules(join(directory, 'rules.json'));
  if (command === 'award') {
    const [agent, task, score, reason] = args;
    if (args.length !== 4 || !/^[+-]\d+$/.test(score)) throw new Error('Expected agent, task, signed points and reason.');
    const tags = values.tag;
    if (tags.some(tag => !rules.some(rule => rule.id === tag)) || (tags.length && values['no-tags'])) {
      throw new Error('Use existing rule IDs or --no-tags.');
    }
    const event = { timestamp: new Date().toISOString(), agent, task, points: Number(score), reason, source: values.source, tags };
    validateEvent(event);
    const matches = suggest(rules, reason);
    if (!tags.length && !values['no-tags'] && matches.length) {
      console.log('Confirm rule tags: ' + matches.map(rule => rule.id).join(', ') +
        '. Re-run with --tag RULE (repeatable) or --no-tags.');
      process.exitCode = 2;
      return;
    }
    record(directory, event);
    console.log('Recorded ' + signed(event.points) + ' for ' + agent + ' / ' + task + ' | ' + reason);
    return;
  }
  if (command === 'propose' && args.length === 1) {
    console.log(json(propose(args[0])));
    return;
  }
  if (command === 'suggest' && args.length === 1 && textField(args[0])) {
    console.log(json(suggest(rules, args[0])));
    return;
  }
  if (args.length) throw new Error('Unexpected positional arguments. See --help.');
  const now = values['as-of'] ? Date.parse(values['as-of']) : Date.now();
  const top = Number(values.top);
  if (!Number.isFinite(now) || !Number.isInteger(top) || top < 1 || top > 50) {
    throw new Error('Use a valid --as-of timestamp and --top between 1 and 50.');
  }
  const all = readLedger(path);
  const events = all.filter(event => Date.parse(event.timestamp) <= now);
  if (command === 'ledger') {
    for (const event of all) console.log(JSON.stringify(event));
  } else if (command === 'export') {
    const output = json({ events, rules, weights: weigh(rules, events, now), ...summarize(events, now) }) + '\n';
    if (values.output) writeFileSync(values.output, output, { flag: 'wx', mode: 0o600 });
    else process.stdout.write(output);
  } else if (command === 'board') {
    console.log(board(summarize(events, now), process.stdout.isTTY && !('NO_COLOR' in process.env)));
  } else if (command === 'lessons') {
    const digest = lessons(rules, events, now, top, values.agent);
    console.log(values['active-only'] ? digest.slice(digest.indexOf('## Active rules')) : digest);
  } else if (command === 'charts' && values.output) {
    charts(values.output, summarize(events, now), weigh(rules, events, now), dayLabel(utcDay(now)));
  } else {
    throw new Error('Unknown command or missing --output. See --help.');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    main();
  } catch (error) {
    console.error('points: ' + (error.code === 'EEXIST' ? 'Output already exists or the ledger writer lock is held.' : error.message));
    process.exitCode = 1;
  }
}
