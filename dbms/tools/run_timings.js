// Time every query in 04_queries.sql three times and save the raw plans.
//
//   node dbms/tools/run_timings.js [--restart "pg_ctl -D ... restart"] [psql connection args...]
//
// Each run executes the whole file top to bottom inside one transaction that is
// rolled back at the end, so every run starts from the same data and a query can
// use what an earlier one wrote (Q38 reads the submission Q37 inserted), as the
// app does. Every statement is wrapped in EXPLAIN (ANALYZE, BUFFERS): PostgreSQL
// runs it for real and reports the plan, the rows and the time.
//
// The number recorded is the "Execution Time" line: time spent executing on the
// server, without planning and without sending rows to the client. Planning time
// is kept in the plan files. Run 1 follows a server restart (empty shared
// buffers); runs 2 and 3 follow straight after.
//
// Writes plans/Qnn.txt (the statement and its three plans) and plans/timings.json.
// Set PLANS_DIR to write somewhere else (plans/with_recommended_indexes/ was made
// that way) and QUERIES_FILE to time a different file.

import { execSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DBMS = path.dirname(HERE);
const QUERIES = process.env.QUERIES_FILE || path.join(DBMS, '04_queries.sql');
const PLANS = process.env.PLANS_DIR || path.join(DBMS, 'plans');
const HEADER = /^-- (Q\d\d) · (READ|WRITE) · (.+)$/;

/** Split 04_queries.sql into blocks: id, kind, title, notes, source and the statement. */
export function parseBlocks(text) {
  const blocks = [];
  let cur = null;
  for (const line of text.split('\n')) {
    if (line.trim() === '-- END') break;
    const m = line.match(HEADER);
    if (m) {
      cur = { id: m[1], kind: m[2], title: m[3].trim(), notes: [], sql: [], titled: false };
      blocks.push(cur);
      continue;
    }
    if (!cur) continue;
    if (line.startsWith('--')) {
      if (!cur.sql.length && !line.startsWith('-- ===') && !['-- READ', '-- WRITE'].includes(line.trim())) {
        if (!cur.notes.length && !line.startsWith('-- App:') && !cur.titled) {
          cur.title += ` ${line.slice(3).trim()}`; // a title wrapped onto a second line
          continue;
        }
        cur.titled = true;
        cur.notes.push(line.slice(3));
      }
      continue;
    }
    if (line.startsWith('#') || line.startsWith('-- ###')) continue;
    if (line.trim() || cur.sql.length) cur.sql.push(line);
  }
  for (const b of blocks) {
    delete b.titled;
    const sql = b.sql.join('\n').trim().replace(/\n-- #+.*/g, '').trim();
    if (!sql.endsWith(';')) throw new Error(`${b.id}: ${sql.slice(-80)}`);
    b.sql = sql;
    const app = b.notes.findIndex((n) => n.startsWith('App:'));
    b.source = app >= 0 ? b.notes[app].slice(5).split(' (')[0].split(';')[0].trim() : '';
  }
  return blocks;
}

function runOnce(blocks, psql) {
  const script = ['\\set ON_ERROR_STOP on', '\\pset format unaligned', '\\pset tuples_only on', 'BEGIN;'];
  for (const b of blocks) script.push(`\\echo @@${b.id}`, `EXPLAIN (ANALYZE, BUFFERS) ${b.sql}`);
  script.push('\\echo @@END', 'ROLLBACK;');
  const out = spawnSync(psql[0], [...psql.slice(1), '-X', '-q'], { input: script.join('\n'), encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 });
  if (out.status !== 0) {
    console.error(`psql failed:\n${(out.stderr || '').slice(-2000)}`);
    process.exit(1);
  }
  const res = {};
  let cur = null;
  let lines = [];
  for (const line of out.stdout.split('\n')) {
    if (line.startsWith('@@')) {
      if (cur) res[cur] = { plan: lines.join('\n') };
      cur = line.slice(2);
      lines = [];
      continue;
    }
    lines.push(line);
  }
  for (const [qid, r] of Object.entries(res)) {
    const ex = r.plan.match(/Execution Time: ([\d.]+) ms/);
    const pl = r.plan.match(/Planning Time: ([\d.]+) ms/);
    if (!ex) {
      console.error(`${qid}: no execution time in\n${r.plan}`);
      process.exit(1);
    }
    r.exec_ms = Number(ex[1]);
    r.plan_ms = pl ? Number(pl[1]) : 0;
  }
  return res;
}

const r3 = (x) => Math.round(x * 1000) / 1000;

function main() {
  let args = process.argv.slice(2);
  let restart = null;
  if (args[0] === '--restart') {
    restart = args[1];
    args = args.slice(2);
  }
  const psql = ['psql', ...args];
  const blocks = parseBlocks(fs.readFileSync(QUERIES, 'utf8'));
  if (restart) execSync(restart, { stdio: 'ignore' });
  const runs = [0, 1, 2].map(() => runOnce(blocks, psql));
  fs.mkdirSync(PLANS, { recursive: true });
  const summary = [];
  for (const b of blocks) {
    const ex = runs.map((r) => r[b.id].exec_ms);
    const pl = runs.map((r) => r[b.id].plan_ms);
    summary.push({
      id: b.id, kind: b.kind, title: b.title, source: b.source, runs_ms: ex,
      avg_ms: r3(ex.reduce((a, x) => a + x, 0) / 3), planning_avg_ms: r3(pl.reduce((a, x) => a + x, 0) / 3),
    });
    const body = [`${b.id} · ${b.kind} · ${b.title}`, ...b.notes, '', b.sql, ''];
    runs.forEach((r, i) => body.push(`---- Run ${i + 1}: execution ${r[b.id].exec_ms.toFixed(3)} ms, planning ${r[b.id].plan_ms.toFixed(3)} ms ----`, r[b.id].plan.trimEnd(), ''));
    fs.writeFileSync(path.join(PLANS, `${b.id}.txt`), body.join('\n'));
  }
  fs.writeFileSync(path.join(PLANS, 'timings.json'), `${JSON.stringify(summary, null, 1)}\n`);
  for (const s of summary) {
    const [a, b, c] = s.runs_ms.map((x) => x.toFixed(3).padStart(9));
    console.log(`${s.id} ${s.kind.padEnd(5)} ${a} ${b} ${c}  avg ${s.avg_ms.toFixed(3).padStart(9)}  ${s.title.slice(0, 60)}`);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
