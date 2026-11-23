// Draw 02_er_diagram.png from 03_schema.sql.
//
//   node dbms/tools/er_diagram.js        (needs Graphviz: dot)
//
// Reads every CREATE TABLE, its columns, primary key, foreign keys, UNIQUE
// constraints and unique indexes straight from 03_schema.sql, so the picture can
// not drift from the schema. Writes tools/er_diagram.dot and 02_er_diagram.png.
//
// Notation (crow's foot): the end at a table says how many rows of that table go
// with one row at the other end.  ||  exactly one   |o  zero or one   o{  zero or many

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DBMS = path.dirname(HERE);
const SCHEMA = path.join(DBMS, '03_schema.sql');

const GROUPS = {
  'Accounts and admin': [['users', 'refresh_tokens', 'profiles', 'audit_log'], '#dbeafe', '#1e3a8a'],
  Problems: [['problems', 'test_cases'], '#dcfce7', '#14532d'],
  Matches: [['matches', 'submissions', 'match_events', 'drafts', 'rating_history'], '#fee2e2', '#7f1d1d'],
  'Progress and economy': [['quest_progress', 'achievements', 'inventory', 'purchases'], '#fef3c7', '#78350f'],
  Moderation: [['flags', 'reports'], '#ede9fe', '#4c1d95'],
};
const FONT = 'DejaVu Sans';
const MONO = 'DejaVu Sans Mono';
const esc = (s) => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#x27;');

export function parse(sql) {
  const tables = {};
  for (const m of sql.matchAll(/CREATE TABLE (\w+) \(([\s\S]*?)\n\);/g)) {
    const [, name, body] = m;
    const cols = [];
    const uniques = [];
    for (const raw of body.split('\n')) {
      const line = raw.split('--')[0].trim().replace(/,+$/, '');
      if (!line) continue;
      const u = line.match(/^CONSTRAINT \w+ UNIQUE \(([^)]*)\)/);
      if (u) {
        uniques.push(u[1].split(',').map((c) => c.trim()));
        continue;
      }
      if (line.startsWith('CONSTRAINT')) continue;
      const c = line.match(/^(\w+)\s+([A-Z]+(?:\(\d+\))?)(.*)$/);
      if (!c) continue;
      const rest = c[3];
      const ref = rest.match(/REFERENCES (\w+) \((\w+)\)/);
      cols.push({
        name: c[1], type: c[2].toLowerCase(), pk: rest.includes('PRIMARY KEY'),
        notnull: rest.includes('NOT NULL') || rest.includes('PRIMARY KEY'),
        ref: ref ? [ref[1], ref[2]] : null, cascade: rest.includes('ON DELETE CASCADE'),
      });
    }
    tables[name] = { cols, uniques };
  }
  for (const m of sql.matchAll(/CREATE UNIQUE INDEX \w+ ON (\w+) \(([^)]*)\)/g)) tables[m[1]].uniques.push(m[2].split(',').map((c) => c.trim()));
  return tables;
}

function keysOf(t, col) {
  const marks = [];
  const c = t.cols.find((x) => x.name === col);
  if (c.pk) marks.push('PK');
  if (c.ref) marks.push('FK');
  t.uniques.forEach((u, i) => {
    if (u.includes(col)) marks.push(u.length === 1 ? 'UK' : `UK${i + 1}`);
  });
  return marks.join(', ');
}

function tableLabel(name, t, headBg, headFg) {
  const rows = [`<TR><TD COLSPAN="3" BGCOLOR="${headFg}" ALIGN="CENTER"><FONT COLOR="white" FACE="${FONT}" POINT-SIZE="13"><B>${name}</B></FONT></TD></TR>`];
  let { cols } = t;
  let p1 = [];
  if (name === 'matches') { // 55 columns: show the keys, then the two player groups folded
    p1 = cols.filter((c) => c.name.startsWith('player1_') && c.name !== 'player1_profile_id').map((c) => c.name.slice('player1_'.length));
    cols = [...cols.filter((c) => !c.name.startsWith('player1_') && !c.name.startsWith('player2_')),
      ...t.cols.filter((c) => c.name === 'player1_profile_id' || c.name === 'player2_profile_id')];
  }
  for (const c of cols) {
    const k = keysOf(t, c.name);
    const bold = c.pk || c.ref || k;
    let nm = esc(c.name);
    nm = bold ? `<B>${nm}</B>` : nm;
    if (c.pk) nm = `<U>${nm}</U>`;
    const typ = esc(c.type) + (c.notnull ? '' : ' ?');
    rows.push(`<TR><TD ALIGN="LEFT" BGCOLOR="${headBg}"><FONT FACE="${MONO}" POINT-SIZE="9">${k || '&#160;'}</FONT></TD>`
      + `<TD ALIGN="LEFT" PORT="${c.name}"><FONT FACE="${MONO}" POINT-SIZE="10">${nm}</FONT></TD>`
      + `<TD ALIGN="LEFT"><FONT FACE="${MONO}" POINT-SIZE="9" COLOR="#555555">${typ}</FONT></TD></TR>`);
  }
  if (name === 'matches') {
    const chunks = [];
    let line = '';
    for (const p of p1) {
      const nxt = (line ? `${line}, ` : '') + p;
      if (nxt.length > 44) {
        chunks.push(`${line},`);
        line = p;
      } else {
        line = nxt;
      }
    }
    chunks.push(line);
    const txt = chunks.map(esc).join('<BR ALIGN="LEFT"/>');
    rows.push(`<TR><TD BGCOLOR="${headBg}"></TD><TD COLSPAN="2" ALIGN="LEFT"><FONT FACE="${MONO}" POINT-SIZE="9">`
      + `<B>player1_* and player2_*</B>, ${p1.length} each:<BR ALIGN="LEFT"/>${txt}<BR ALIGN="LEFT"/></FONT></TD></TR>`);
  }
  t.uniques.forEach((u, i) => {
    if (u.length > 1) {
      rows.push(`<TR><TD COLSPAN="3" ALIGN="LEFT" BGCOLOR="#f8fafc"><FONT FACE="${FONT}" POINT-SIZE="9" COLOR="#334155">`
        + `UK${i + 1}: unique (${esc(u.join(', '))})</FONT></TD></TR>`);
    }
  });
  return `<<TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="3" COLOR="#94a3b8">${rows.join('')}</TABLE>>`;
}

export function render(tables) {
  if (Object.keys(tables).length !== 17) throw new Error(`expected 17 tables, found ${Object.keys(tables).sort()}`);
  const out = ['digraph er {',
    `  graph [rankdir=TB, splines=true, nodesep=0.45, ranksep=0.9, newrank=true, pad=0.4, bgcolor="white", fontname="${FONT}",`
    + '         label=<<FONT POINT-SIZE="22"><B>AlgoArena (cp_battle): entity-relationship diagram</B></FONT><BR/>'
    + '<FONT POINT-SIZE="12">17 tables from 03_schema.sql · PK primary key · FK foreign key · UK unique (alternate) key · '
    + '<U>underlined</U> = primary key · ? = nullable<BR/>Crow\'s foot at each end: || exactly one · |o zero or one · '
    + 'o&lt; zero or many · edge label = foreign-key column (cardinality parent : child)</FONT>>,'
    + '         labelloc=t];',
    `  node [shape=plaintext, fontname="${FONT}"];`,
    `  edge [fontname="${FONT}", fontsize=9, color="#475569", fontcolor="#334155", dir=both, arrowsize=0.9, penwidth=1.2];`];
  Object.entries(GROUPS).forEach(([gname, [members, bg, fg]], gi) => {
    out.push(`  subgraph cluster_${gi} { label=<<B>${gname}</B>>; fontsize=14; style="rounded,filled"; fillcolor="${bg}50"; color="${fg}"; fontcolor="${fg}";`);
    for (const t of members) out.push(`    ${t} [label=${tableLabel(t, tables[t], bg, fg)}];`);
    out.push('  }');
  });
  let nFk = 0;
  for (const [child, t] of Object.entries(tables)) {
    for (const c of t.cols) {
      if (!c.ref) continue;
      nFk++;
      const [parent] = c.ref;
      const unique = t.uniques.some((u) => u.length === 1 && u[0] === c.name);
      const tail = c.notnull ? 'teetee' : 'teeodot'; // parents per child row
      const head = unique ? 'teeodot' : 'crowodot'; // child rows per parent
      const card = `${c.notnull ? '1' : '0..1'} : ${unique ? '0..1' : '0..N'}`;
      const extra = c.cascade ? ', on delete cascade' : '';
      out.push(`  ${parent} -> ${child} [arrowtail=${tail}, arrowhead=${head}, label="${c.name}\\n${card}${extra}"];`);
    }
  }
  out.push('}');
  if (nFk !== 23) throw new Error(`expected 23 relationships, found ${nFk}`);
  return { dot: `${out.join('\n')}\n`, nFk };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const tables = parse(fs.readFileSync(SCHEMA, 'utf8'));
  const { dot, nFk } = render(tables);
  const dotFile = path.join(HERE, 'er_diagram.dot');
  if (process.argv.includes('--check')) {
    const same = fs.readFileSync(dotFile, 'utf8') === dot;
    console.log(same ? 'er_diagram.dot is up to date' : 'er_diagram.dot differs');
    process.exit(same ? 0 : 1);
  }
  fs.writeFileSync(dotFile, dot);
  execFileSync('dot', ['-Tpng', '-Gdpi=110', '-o', path.join(DBMS, '02_er_diagram.png'), dotFile], { stdio: 'inherit' });
  console.log('wrote', path.join(DBMS, '02_er_diagram.png'), 'with', Object.keys(tables).length, 'tables and', nFk, 'relationships');
}
