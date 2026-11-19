/** Skin manifest validator: schema, unique ids, known recipe names, no external
 * URLs, a reduced-motion fallback, particle rates within the limit and a
 * text-on-background contrast ratio of at least 4.5. Pure: no I/O. */

export interface Recipes {
  frame: string[];
  particles: string[];
  element: string[];
  projectile: string[];
  trail: string[];
  impact: string[];
  status: string[];
  sfx: string[];
  overlay: string[];
  layer: string[];
  rarity: string[];
  max_particle_rate: number;
}

const HEX = /^#[0-9a-fA-F]{6}$/;

function lum(hex: string): number {
  const ch = (i: number) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5);
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

export function validateManifest(m: any, recipes: Recipes, filename?: string): string[] {
  const e: string[] = [];
  const id = m?.id ?? "?";
  if (filename && filename !== `${id}.json`) e.push(`${filename}: file must be named after its id`);
  const prefix: Record<string, string> = { card: "card.", avatar: "bean.", arena: "arena." };
  if (!prefix[m?.kind]) e.push(`${id}: kind must be card, avatar or arena`);
  else if (!String(id).startsWith(prefix[m.kind])) e.push(`${id}: id prefix does not match kind`);
  if (!recipes.rarity.includes(m?.rarity)) e.push(`${id}: unknown rarity`);
  const u = m?.unlock ?? {};
  if (!["default", "tier", "ap", "achievement", "admin"].includes(u.type)) e.push(`${id}: unknown unlock type`);
  if (u.type === "ap" && !(u.price > 0)) e.push(`${id}: ap unlock needs a price`);
  if (u.type === "ap" && m.rarity === "legendary") e.push(`${id}: legendary skins are not for sale`);
  if (!m?.reducedMotion) e.push(`${id}: missing reducedMotion fallback`);
  if (/https?:\/\//.test(JSON.stringify(m))) e.push(`${id}: external URLs are not allowed`);
  for (const [k, v] of Object.entries(m?.palette ?? {})) {
    for (const c of Array.isArray(v) ? v : [v]) if (c !== "$player" && !HEX.test(String(c))) e.push(`${id}: palette.${k} is not #rrggbb`);
  }
  if (m?.kind === "card") {
    if (!recipes.frame.includes(m.frame?.style)) e.push(`${id}: unknown frame style`);
    for (const f of ["element", "projectile", "trail", "impact", "status", "sfx"] as const) {
      if (!recipes[f].includes(m.attack?.[f])) e.push(`${id}: unknown attack.${f} ${m.attack?.[f]}`);
    }
    if (m.attack?.ramp?.length !== 5) e.push(`${id}: attack.ramp needs 5 colours`);
    for (const part of ["idle", "hover"]) {
      const p = m[part]?.particles;
      if (p !== null && p !== undefined && !recipes.particles.includes(p)) e.push(`${id}: unknown ${part}.particles`);
    }
    if ((m.idle?.rate ?? 0) > recipes.max_particle_rate) e.push(`${id}: idle particle rate over the limit`);
    for (const bg of m.palette?.bg ?? []) {
      if (HEX.test(m.palette.text) && HEX.test(bg) && contrast(m.palette.text, bg) < 4.5) e.push(`${id}: text contrast under 4.5 on ${bg}`);
    }
  } else if (m?.kind === "avatar") {
    for (const o of m.overlays ?? []) {
      if (!recipes.overlay.includes(o.sprite) || !["head", "back", "hand"].includes(o.anchor)) e.push(`${id}: bad overlay ${JSON.stringify(o)}`);
    }
  } else if (m?.kind === "arena") {
    for (const l of m.layers ?? []) if (!recipes.layer.includes(l)) e.push(`${id}: unknown layer ${l}`);
    if ((m.ambient?.rate ?? 0) > recipes.max_particle_rate) e.push(`${id}: ambient particle rate over the limit`);
    for (const sky of m.palette?.sky ?? []) if (contrast(m.palette.text, sky) < 4.5) e.push(`${id}: text contrast under 4.5 on ${sky}`);
  }
  return e;
}

export function validateAll(files: { name: string; data: any }[], recipes: Recipes): string[] {
  const errors: string[] = [];
  const seen = new Set<string>();
  for (const f of files) {
    errors.push(...validateManifest(f.data, recipes, f.name));
    if (seen.has(f.data?.id)) errors.push(`duplicate id ${f.data?.id}`);
    seen.add(f.data?.id);
  }
  return errors;
}
