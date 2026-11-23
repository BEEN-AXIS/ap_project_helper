// Time a few writes many times each, to measure what the extra indexes cost them.
//
//   node dbms/tools/write_cost.js LABEL [-n 300] [psql connection args...]
//
// Each repetition runs one write under EXPLAIN (ANALYZE) inside its own
// transaction and rolls it back, so the data never changes; a write that needs an
// earlier one (Q33 makes live the match Q31 creates) runs that one first,
// untimed. The whole file's three runs are too noisy for differences this small;
// 300 repetitions and the median are not. Results are added to
// plans/write_cost.json under LABEL (05_query_timings.md used "with", "without",
// "with again").

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseBlocks } from './run_timings.js';

const DBMS = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

// the writes that insert into or change indexed columns of profiles and matches, and Q36 as a
// control (match_events has no new index), with what each needs to have run first
const TARGETS = { Q02: [], Q31: [], Q33: ['Q31'], Q35: [], Q36: [], Q46: [], Q51: [], Q72: [] };

const median = (v) => {
  const s = [...v].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const r3 = (x) => Math.round(x * 1000) / 1000;

const [label, ...rest] = process.argv.slice(2);
let args = rest;
let n = 300;
if (args[0] === '-n') {
  n = Number(args[1]);
  args = args.slice(2);
}
const blocks = Object.fromEntries(parseBlocks(fs.readFileSync(path.join(DBMS, '04_queries.sql'), 'utf8')).map((b) => [b.id, b]));
const script = ['\\set ON_ERROR_STOP on', '\\pset tuples_only on', '\\pset format unaligned'];
for (let i = 0; i < n; i++) {
  for (const [q, before] of Object.entries(TARGETS)) {
    script.push('BEGIN;');
    for (const p of before) script.push('\\o /dev/null', blocks[p].sql, '\\o');
    script.push(`\\echo @@${q}`, `EXPLAIN (ANALYZE) ${blocks[q].sql}`, 'ROLLBACK;');
  }
}
const out = spawnSync('psql', ['-X', '-q', ...args], { input: script.join('\n'), encoding: 'utf8', maxBuffer: 512 * 1024 * 1024 });
if (out.status !== 0) {
  console.error(out.stderr);
  process.exit(1);
}
const times = Object.fromEntries(Object.keys(TARGETS).map((q) => [q, []]));
let cur = null;
for (const line of out.stdout.split('\n')) {
  if (line.startsWith('@@')) cur = line.slice(2);
  const m = line.match(/Execution Time: ([\d.]+) ms/);
  if (m && cur) times[cur].push(Number(m[1]));
}
const file = path.join(DBMS, 'plans', 'write_cost.json');
const data = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
data[label] = Object.fromEntries(Object.entries(times).map(([q, v]) => [q, {
  title: blocks[q].title, n: v.length, median_ms: r3(median(v)), mean_ms: r3(v.reduce((a, x) => a + x, 0) / v.length),
}]));
fs.writeFileSync(file, `${JSON.stringify(data, null, 1)}\n`);
for (const [q, r] of Object.entries(data[label])) {
  console.log(`${q}  median ${r.median_ms.toFixed(3).padStart(7)}  mean ${r.mean_ms.toFixed(3).padStart(7)}  n=${r.n}  ${r.title}`);
}
