import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const ink = '#f2f7fb';
const muted = '#aabbd0';
const gain = '#69e4b3';
const loss = '#ff9a8d';
const panel = '#182b3c';
const neutral = '#58718a';
const escape = value => String(value).replace(/[&<>"']/g, char =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[char]);
const label = (x, y, value, size = 16, fill = ink) =>
  '<text x="' + x + '" y="' + y + '" font-size="' + size + '" fill="' + fill + '">' + escape(value) + '</text>';
const rect = (x, y, width, height, fill, radius = 4) =>
  '<rect x="' + x + '" y="' + y + '" width="' + width + '" height="' + height +
  '" rx="' + radius + '" fill="' + fill + '"/>';
const sign = value => value > 0 ? '+' + value : String(value);
const color = value => value > 0 ? gain : value < 0 ? loss : neutral;
const short = value => [...value].length > 25 ? [...value].slice(0, 24).join('') + '…' : value;
const range = values => Math.max(1, ...values.map(Math.abs));

function line(values, x, y, width, height) {
  const max = range(values);
  const points = values.map((value, index) =>
    (x + index * width / Math.max(1, values.length - 1)).toFixed(1) + ',' +
    (y + height / 2 - value * height / (2 * max)).toFixed(1));
  return '<path d="M' + x + ' ' + (y + height / 2) + 'h' + width + '" stroke="' + neutral + '"/>' +
    '<polyline points="' + points.join(' ') + '" fill="none" stroke="' + gain + '" stroke-width="2"/>';
}

export function charts(directory, summary, weights, date) {
  mkdirSync(directory, { recursive: true });
  function save(name, title, description, height, content) {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 ' + height +
      '" role="img" aria-labelledby="title description" font-family="system-ui, sans-serif">' +
      '<title id="title">' + escape(title) + '</title><desc id="description">' + escape(description) + '</desc>' +
      rect(0, 0, 760, height, '#0d1925', 18) + label(30, 43, title, 28) +
      label(30, 68, 'Through ' + date + ' UTC', 14, muted) + content + '</svg>\n';
    writeFileSync(join(directory, name + '.svg'), svg);
  }
  const agents = summary.agents.slice(0, 8);
  const maximum = range(agents.map(agent => agent.total));
  const rows = agents.map((agent, index) => {
    const y = 130 + 38 * index;
    return label(36, y, short(agent.label)) + label(245, y, sign(agent.total)) +
      rect(350, y - 12, Math.abs(agent.total) / maximum * 150, 12, color(agent.total)) +
      line(agent.days.map(day => day.total), 555, y - 15, 162, 22);
  }).join('');
  save('scoreboard', 'Points scoreboard', agents.map(agent => agent.label + ' ' + sign(agent.total)).join(', ') ||
    'No awards recorded.', 150 + 38 * agents.length,
    label(36, 99, 'Agent', 14, muted) + label(245, 99, 'Balance', 14, muted) +
    label(555, 99, '30-day activity', 14, muted) + (rows || label(36, 132, 'No awards recorded.')));

  const days = summary.days.map(day => day.total);
  const monthly = days.reduce((total, value) => total + value, 0);
  const activity = summary.days.map(day => day.date + ': ' + sign(day.total)).join(', ');
  const limit = range(days);
  save('points-over-time', 'Points over time', activity, 294,
    label(30, 102, 'Daily net points · 30 UTC days', 15, muted) +
    label(30, 132, sign(limit), 13, muted) + label(30, 238, sign(-limit), 13, muted) +
    line(days, 100, 126, 620, 108) + label(100, 264, summary.days[0].date, 13, muted) +
    label(640, 264, date, 13, muted));

  const offset = (new Date(summary.days[0].date).getUTCDay() + 6) % 7;
  const weekdayLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((day, index) =>
    label(36, 120 + index * 29, day, 13, muted)).join('');
  const cells = summary.days.map(({ date: day, total }, index) => {
    const slot = index + offset;
    const x = 104 + Math.floor(slot / 7) * 112;
    const y = 100 + (slot % 7) * 29;
    return '<g><title>' + day + ' ' + sign(total) + '</title>' + rect(x, y, 100, 24, panel) +
      label(x + 10, y + 17, day.slice(5) + '  ' + sign(total), 13, total ? color(total) : muted) + '</g>';
  }).join('');
  save('heatmap', 'Gains and losses calendar', activity, 340, weekdayLabels + cells +
    label(105, 321, 'Green + gain     Salmon − loss     Gray 0 net', 14, muted));

  const rules = weights.slice(0, 8);
  const maxWeight = range(rules.map(rule => rule.weight));
  save('rule-strength', 'Rule strength', rules.map(rule => rule.id + ' ' + rule.weight.toFixed(2)).join(', ') ||
    'No rules configured.', 120 + 35 * rules.length, rules.map((rule, index) => {
    const y = 105 + index * 35;
    return label(36, y, short(rule.id)) + label(280, y, rule.weight.toFixed(2)) +
      rect(395, y - 12, rule.weight / maxWeight * 320, 12, gain);
  }).join('') || label(36, 103, 'No rules configured.'));

  const boxes = [
    ['Agents scored', summary.agents.length],
    ['30-day net points', sign(monthly)],
    ['Rules tracked', weights.length],
  ].map(([name, value], index) => {
    const x = 30 + 238 * index;
    return rect(x, 96, 224, 80, panel, 8) + label(x + 14, 124, name, 15, muted) +
      label(x + 14, 156, value, 25);
  }).join('');
  save('dashboard', 'Ship-gate · local points dashboard', summary.agents.length + ' agents scored, ' +
    sign(monthly) + ' net points in 30 days, ' + weights.length + ' rules tracked.', 306,
    boxes + label(32, 215, 'Daily net points', 15, muted) + line(days, 32, 228, 696, 50));
}
