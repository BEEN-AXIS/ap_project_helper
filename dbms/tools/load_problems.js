// Print SQL that loads the game's 17 real problems and their 144 test cases.
//
//   node dbms/tools/load_problems.js | psql -d algoarena
//
// Tier, base damage and base recoil come from shared/game-config.json exactly as
// server/scripts/seed.js derives them.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'shared/game-config.json'), 'utf8'));
const tiers = [...cfg.tiers].sort((a, b) => a.min_rating - b.min_rating);
const PROBLEMS = path.join(ROOT, 'server/seed/problems');

const tierRow = (rating) => tiers.filter((t) => rating >= t.min_rating).at(-1);

/** JSON as Python's json.dumps writes it: ", " and ": " separators, non-ASCII escaped. */
function pyJson(v) {
  if (v === null) return 'null';
  if (Array.isArray(v)) return `[${v.map(pyJson).join(', ')}]`;
  if (typeof v === 'object') return `{${Object.entries(v).map(([k, x]) => `${pyJson(k)}: ${pyJson(x)}`).join(', ')}}`;
  return JSON.stringify(v).replace(/[\u0080-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

function lit(v) {
  if (v === null || v === undefined) return 'NULL';
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  if (typeof v === 'number') return String(v);
  if (typeof v === 'object') v = pyJson(v);
  let tag = '$q$';
  while (v.includes(tag)) tag = `${tag.slice(0, -1)}x$`;
  return `${tag}${v}${tag}`;
}

const out = ['BEGIN;'];
const files = fs.readdirSync(PROBLEMS).filter((f) => f.endsWith('.json')).sort();
files.forEach((f, n) => {
  const i = n + 1;
  const d = JSON.parse(fs.readFileSync(path.join(PROBLEMS, f), 'utf8'));
  const t = tierRow(d.rating);
  const cols = {
    id: i, slug: d.slug, title: d.title, statement_md: d.statement_md, input_md: d.input_md ?? '',
    output_md: d.output_md ?? '', constraints_md: d.constraints_md ?? '', biome: d.biome,
    rating: d.rating, tier: t.tier, base_damage: d.base_damage ?? t.base_damage,
    base_recoil: d.base_recoil ?? t.base_recoil, time_limit_ms: d.time_limit_ms ?? 2000,
    memory_mb: d.memory_mb ?? 256, checker: d.checker ?? 'exact', checker_script: d.checker_script ?? null,
    tags: d.tags ?? [], hints: d.hints ?? [], stubs: d.stubs ?? {},
    reference_solution: d.reference_solution ?? '', status: 'published',
  };
  out.push(`INSERT INTO problems (${Object.keys(cols).join(', ')}) VALUES (${Object.values(cols).map(lit).join(', ')});`);
  d.tests.forEach((tc, k) => {
    out.push(`INSERT INTO test_cases (problem_id, idx, input_text, expected_text, is_sample) VALUES (${i}, ${k}, ${lit(tc.input)}, ${lit(tc.expected)}, ${lit(Boolean(tc.is_sample))});`);
  });
});
out.push("SELECT setval('problems_id_seq', (SELECT max(id) FROM problems));");
out.push('COMMIT;');
process.stdout.write(`${out.join('\n')}\n`);
