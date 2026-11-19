/** Skin manifests, fetched once from the server (which reads shared/skins/*.json). */

export interface CardSkin {
  id: string;
  kind: "card";
  name: string;
  rarity: string;
  unlock: Unlock;
  palette: { bg: string[]; border: string; text: string; accent: string };
  frame: { style: string; animated: boolean };
  idle: { particles: string | null; rate: number };
  hover: { particles: string; glow: number; tilt: number };
  attack: {
    element: string;
    projectile: string;
    ramp: string[];
    trail: string;
    impact: string;
    status: string;
    number: { fill: string; stroke: string };
    sfx: string;
  };
  block: { dome: string };
  reducedMotion: Record<string, unknown>;
}

export interface AvatarSkin {
  id: string;
  kind: "avatar";
  name: string;
  rarity: string;
  unlock: Unlock;
  palette: { body: string; eye: string; outline: string; shine: string };
  overlays: { sprite: string; anchor: "head" | "back" | "hand" }[];
  reducedMotion: Record<string, unknown>;
}

export interface ArenaSkin {
  id: string;
  kind: "arena";
  name: string;
  rarity: string;
  unlock: Unlock;
  palette: { sky: string[]; floor: string; accent: string; text: string };
  layers: string[];
  ambient: { particles: string | null; rate: number };
  reducedMotion: Record<string, unknown>;
}

export interface Unlock {
  type: "default" | "tier" | "ap" | "achievement" | "admin";
  tier?: number;
  price?: number;
  id?: string;
  label?: string;
  map?: string;
}

export type Skin = CardSkin | AvatarSkin | ArenaSkin;

export const DEFAULT_CARD: CardSkin = {
  id: "card.classic",
  kind: "card",
  name: "Classic Terminal",
  rarity: "common",
  unlock: { type: "default" },
  palette: { bg: ["#334155", "#1e293b"], border: "#475569", text: "#f8fafc", accent: "#22c55e" },
  frame: { style: "terminal", animated: false },
  idle: { particles: "scanlines", rate: 0 },
  hover: { particles: "sparks", glow: 1.2, tilt: 12 },
  attack: {
    element: "fire",
    projectile: "orb",
    ramp: ["#fff7d6", "#ffd23f", "#ff7a1a", "#d62718", "#2a1a1a"],
    trail: "flame",
    impact: "fire-burst",
    status: "burning",
    number: { fill: "#fff3c4", stroke: "#7a1d08" },
    sfx: "fire",
  },
  block: { dome: "#4ade80" },
  reducedMotion: { frame: "static", idle: null },
};

export const DEFAULT_AVATAR: AvatarSkin = {
  id: "bean.plain",
  kind: "avatar",
  name: "Plain Bean",
  rarity: "common",
  unlock: { type: "default" },
  palette: { body: "$player", eye: "#0f172a", outline: "#020617", shine: "#ffffff" },
  overlays: [],
  reducedMotion: { idle: "static" },
};

export const DEFAULT_ARENA: ArenaSkin = {
  id: "arena.bit",
  kind: "arena",
  name: "Binary Rain Stage",
  rarity: "common",
  unlock: { type: "default", map: "bit" },
  palette: { sky: ["#0f172a", "#052e16"], floor: "#14532d", accent: "#22c55e", text: "#dcfce7" },
  layers: ["digits"],
  ambient: { particles: "bits", rate: 10 },
  reducedMotion: { ambient: null },
};

const registry = new Map<string, Skin>([DEFAULT_CARD, DEFAULT_AVATAR, DEFAULT_ARENA].map((s) => [s.id, s]));
let loading: Promise<void> | null = null;
const subs = new Set<() => void>();

export function loadRegistry(): Promise<void> {
  if (!loading) {
    loading = fetch("/api/skins/registry")
      .then((r) => (r.ok ? r.json() : { skins: [] }))
      .then((d: { skins: Skin[] }) => {
        for (const s of d.skins) registry.set(s.id, s);
        subs.forEach((f) => f());
      })
      .catch(() => {
        loading = null;
      });
  }
  return loading;
}

export function onRegistry(fn: () => void): () => void {
  subs.add(fn);
  return () => subs.delete(fn);
}

export function allSkins(): Skin[] {
  return Array.from(registry.values());
}

/** An unknown id falls back to the default for its kind. */
export function cardSkin(id: unknown): CardSkin {
  const s = typeof id === "string" ? registry.get(id) : undefined;
  return s?.kind === "card" ? s : DEFAULT_CARD;
}

export function avatarSkin(id: unknown): AvatarSkin {
  const s = typeof id === "string" ? registry.get(id) : undefined;
  return s?.kind === "avatar" ? s : DEFAULT_AVATAR;
}

export function arenaSkin(id: unknown): ArenaSkin {
  const s = typeof id === "string" ? registry.get(id) : undefined;
  return s?.kind === "arena" ? s : DEFAULT_ARENA;
}

/** CSS custom properties a card skin sets; skins override only these. */
export function cardVars(skin: CardSkin): Record<string, string> {
  const [a, b] = skin.palette.bg;
  return {
    "--card-bg-grad": `linear-gradient(160deg, ${a}, ${b})`,
    "--card-border": skin.palette.border,
    "--card-text": skin.palette.text,
    "--card-accent": skin.palette.accent,
    "--card-glow": `${skin.palette.accent}${Math.round(Math.min(1, 0.35 * skin.hover.glow) * 255).toString(16).padStart(2, "0")}`,
    "--accent": skin.palette.accent,
  };
}

export const RARITY_COLORS: Record<string, string> = {
  common: "#94a3b8",
  rare: "#38bdf8",
  epic: "#c084fc",
  legendary: "#facc15",
  mythic: "#f472b6",
};
