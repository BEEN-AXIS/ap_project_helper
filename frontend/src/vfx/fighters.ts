/**
 * Original pixel-art "bean" fighters (no third-party assets). The body is a
 * 32 by 32 palette-indexed sprite written as strings and drawn with
 * nearest-neighbour scaling. Avatar skins swap the palette and add overlay
 * sprites anchored at head, back and hand. Poses come from transforms and
 * tints, not frame art.
 */
import type { AvatarSkin } from "../skins/registry";

// O outline, B body, S shade, L shine, F face visor, E pupil, W eye glint, M mouth, D feet
export const BEAN: string[] = [
  "................................",
  "................................",
  "............OOOOOOO.............",
  "..........OOBBBBBBBOO...........",
  ".........OBBBBBBBBBBBO..........",
  "........OBBBBBBBBBBBBSO.........",
  ".......OBBLLBBBBBBBBBSSO........",
  "......OBBLLBBBBBBBBBBSSSO.......",
  "......OBBLBBBBBBBBBBBSSSO.......",
  ".....OBBBLBBFFFFFFFFBSSSSO......",
  ".....OBBBBFFFFFFFFFFFFSSSO......",
  ".....OBBBFFFEWFFFFEWFFFSSO......",
  ".....OBBBFFFEEFFFFEEFFFSSO......",
  "....OBBBBFFFFFFFFFFFFFFSSSO.....",
  "....OBBBBBFFFFMMMMFFFFSSSSO.....",
  "....OBBBBBBFFFFFFFFFFSSSSSO.....",
  "...OOBBBBBBBBBBBBBBBBSSSSSOO....",
  "..OBBOBBBBBBBBBBBBBBBSSSSOSSO...",
  "..OBBOBBBBBBBBBBBBBBBSSSSOSSO...",
  "...OOOBBBBBBBBBBBBBBBSSSSOOO....",
  ".....OBBBBBBBBBBBBBBBSSSSO......",
  "......OBBBBBBBBBBBBBBSSSO.......",
  "......OBBBBBBBBBBBBBBSSSO.......",
  ".......OBBBBBBBBBBBBBSSO........",
  "........OBBBBBBBBBBBBSO.........",
  ".........OBBBBBBBBBBBO..........",
  "..........OOBBBBBBBOO...........",
  "........ODDDDDOOOODDDDDO........",
  "........ODDDDDO..ODDDDDO........",
  "........OOOOOOO..OOOOOOO........",
  "................................",
  "................................",
];

// Overlays: small sprites, '1' main colour, '2' accent, 'O' outline; drawn at an anchor offset (in sprite pixels).
const OVERLAYS: Record<string, { rows: string[]; at: [number, number]; c1: string; c2: string }> = {
  headband: { rows: ["OOOOOOOOOOOOOOOO", "O11111111111111O", "OOOOOOOOOOOOOO22", "..............2."], at: [6, 5], c1: "#ef4444", c2: "#fca5a5" },
  cape: { rows: ["..O11111111O..", ".O1111111111O.", "O111111111111O", "O111111111111O", "O111111111111O", "O1111111111111O", "OOOOOOOOOOOOOO"], at: [9, 17], c1: "#7c3aed", c2: "#a78bfa" },
  crown: { rows: ["2..2..2..2", "O2O22O22O2", "O11111111O", "OOOOOOOOOO"], at: [11, -1], c1: "#facc15", c2: "#fde68a" },
  armor: { rows: ["..OOOOOOOOO..", ".O111111111O.", "O11122222111O", "O11111111111O"], at: [9.5, 1], c1: "#64748b", c2: "#cbd5e1" },
  sword: { rows: ["....2", "...2.", "..2..", "O1O..", ".O..."], at: [26, 13], c1: "#92400e", c2: "#e2e8f0" },
  mask: { rows: ["OOOOOOOOOOOOOO", "O111111111111O", "OOOOOOOOOOOOOO"], at: [9, 13], c1: "#111827", c2: "#374151" },
  helmet: { rows: ["....OOOOOOOOOOOO....", "..OO222222222222OO..", ".O22............22O.", "O2................2O", "O2................2O", "O2................2O", "O2................2O", ".O22............22O.", "..OO222222222222OO.."], at: [5.5, 3.5], c1: "#e2e8f0", c2: "#cbd5e1" },
  dino: { rows: ["..2.2.2.2..", ".OOOOOOOOO.", "O111111111O", "O1O11111O1O", "OOOOOOOOOOO"], at: [10.5, 0], c1: "#16a34a", c2: "#86efac" },
  tail: { rows: ["....OOO", "..OO11O", "OO1111O", "O11111O", ".OOOOO."], at: [23, 21], c1: "#16a34a", c2: "#86efac" },
};

function shade(hex: string, f: number): string {
  const n = parseInt(hex.slice(1), 16);
  const ch = (v: number) => Math.max(0, Math.min(255, Math.round(f >= 0 ? v + (255 - v) * f : v * (1 + f))));
  return `rgb(${ch((n >> 16) & 255)},${ch((n >> 8) & 255)},${ch(n & 255)})`;
}

const spriteCache = new Map<string, HTMLCanvasElement>();

/** Render a bean with the avatar's palette and overlays into a 32x32 canvas (cached). */
export function renderBean(skin: AvatarSkin, playerColor: string): HTMLCanvasElement {
  const body = skin.palette.body === "$player" ? playerColor : skin.palette.body;
  const key = `${skin.id}:${body}`;
  const hit = spriteCache.get(key);
  if (hit) return hit;
  const c = document.createElement("canvas");
  c.width = c.height = 32;
  const g = c.getContext("2d")!;
  const pal: Record<string, string> = {
    O: skin.palette.outline,
    B: body,
    S: shade(body, -0.32),
    L: shade(body, 0.6),
    F: "#e2e8f0",
    E: skin.palette.eye,
    W: skin.palette.shine,
    M: "#334155",
    D: shade(body, -0.5),
  };
  const back = skin.overlays.filter((o) => o.anchor === "back");
  const front = skin.overlays.filter((o) => o.anchor !== "back");
  const paint = (rows: string[], ox: number, oy: number, p: Record<string, string>) => {
    rows.forEach((row, y) => {
      for (let x = 0; x < row.length; x++) {
        const col = p[row[x]];
        if (col) {
          g.fillStyle = col;
          g.fillRect(Math.round(ox + x), Math.round(oy + y), 1, 1);
        }
      }
    });
  };
  for (const o of back) {
    const ov = OVERLAYS[o.sprite];
    if (ov) paint(ov.rows, ov.at[0], ov.at[1], { O: pal.O, "1": ov.c1, "2": ov.c2 });
  }
  paint(BEAN, 0, 0, pal);
  for (const o of front) {
    const ov = OVERLAYS[o.sprite];
    if (ov) paint(ov.rows, ov.at[0], ov.at[1], { O: pal.O, "1": ov.c1, "2": ov.c2 });
  }
  spriteCache.set(key, c);
  return c;
}

const variantCache = new WeakMap<HTMLCanvasElement, Map<string, HTMLCanvasElement>>();

/** A recoloured copy of a sprite: a solid tint, or grayscale ("gray"). Made once, works without ctx.filter. */
export function spriteVariant(sprite: HTMLCanvasElement, variant: string): HTMLCanvasElement {
  let m = variantCache.get(sprite);
  if (!m) variantCache.set(sprite, (m = new Map()));
  const hit = m.get(variant);
  if (hit) return hit;
  const c = document.createElement("canvas");
  c.width = sprite.width;
  c.height = sprite.height;
  const g = c.getContext("2d")!;
  g.drawImage(sprite, 0, 0);
  if (variant === "gray" || variant.startsWith("dark")) {
    const img = g.getImageData(0, 0, c.width, c.height);
    const k = variant === "gray" ? 1 : 0.45;
    for (let i = 0; i < img.data.length; i += 4) {
      const y = 0.3 * img.data[i] + 0.59 * img.data[i + 1] + 0.11 * img.data[i + 2];
      if (variant === "gray") img.data[i] = img.data[i + 1] = img.data[i + 2] = y;
      else for (let j = 0; j < 3; j++) img.data[i + j] *= k;
    }
    g.putImageData(img, 0, 0);
  } else {
    g.globalCompositeOperation = "source-in";
    g.fillStyle = variant;
    g.fillRect(0, 0, c.width, c.height);
  }
  m.set(variant, c);
  return c;
}

export type Pose = "idle" | "windup" | "cast" | "hurt" | "block" | "ko" | "victory" | "flee";

export interface Anchors {
  muzzle: [number, number];
  head: [number, number];
  chest: [number, number];
  feet: [number, number];
}

/** One fighter: position, pose timeline and per-frame anchors in arena coordinates. */
export class Fighter {
  sprite: HTMLCanvasElement | null = null;
  baseX = 0;
  baseY = 0;
  scale = 4;
  facing: 1 | -1 = 1; // +1 faces right (you), -1 faces left (opponent)
  pose: Pose = "idle";
  poseT = 0;
  poseDur = 0;
  knock = 0; // knockback distance for hurt
  tint: string | null = null;
  tintUntil = 0;
  soot = 0;
  burnUntil = 0;
  dizzyUntil = 0;
  grayscale = false;
  offsetX = 0;
  offsetY = 0;
  rot = 0;
  sx = 1;
  sy = 1;
  alpha = 1;
  time = 0;
  shieldColor = "#4ade80";
  victoryJumps = 0;
  anchors: Anchors = { muzzle: [0, 0], head: [0, 0], chest: [0, 0], feet: [0, 0] };

  setPose(pose: Pose, durMs = 0, knock = 0): void {
    if (this.pose === "ko" && pose !== "idle") return;
    this.pose = pose;
    this.poseT = 0;
    this.poseDur = durMs;
    this.knock = knock;
  }

  get size(): number {
    return 32 * this.scale;
  }

  update(dtMs: number, frozen: boolean): void {
    this.time += frozen ? 0 : dtMs;
    if (!frozen) this.poseT += dtMs;
    const t = this.poseT;
    const p = this.poseDur > 0 ? Math.min(1, t / this.poseDur) : 1;
    const bob = Math.sin((this.time / 1600) * Math.PI * 2);
    let ox = 0;
    let oy = 3 * bob;
    let sx = 1 + 0.02 * bob;
    let sy = 1 - 0.02 * bob;
    let rot = 0;
    switch (this.pose) {
      case "windup":
        sy = 1 - 0.12 * p;
        sx = 1 + 0.06 * p;
        ox = -14 * this.facing * p;
        break;
      case "cast": {
        const k = t < 120 ? t / 120 : Math.max(0, 1 - (t - 120) / 180);
        sx = 1 + 0.1 * k;
        sy = 1 + 0.1 * k;
        ox = 30 * this.facing * k;
        if (t > 300) this.pose = "idle";
        break;
      }
      case "hurt": {
        const k = t < 90 ? t / 90 : Math.max(0, 1 - (t - 90) / 400);
        ox = -this.knock * this.facing * k;
        if (t > 490) this.pose = "idle";
        break;
      }
      case "block":
        sy = 0.96;
        ox = -6 * this.facing;
        break;
      case "ko": {
        const k = Math.min(1, t / 600);
        rot = ((540 * Math.PI) / 180) * k * -this.facing;
        ox = -80 * this.facing * k;
        oy = -60 * Math.sin(Math.PI * k);
        this.alpha = 1 - 0.7 * Math.max(0, (t - 600) / 600);
        this.grayscale = true;
        break;
      }
      case "victory": {
        const cycle = (t % 500) / 500;
        const jump = Math.floor(t / 500) < 3 ? Math.sin(Math.PI * cycle) : 0;
        oy = -26 * jump;
        const land = jump < 0.15 && Math.floor(t / 500) < 3 ? 0.12 : 0;
        sy = 1 - land;
        sx = 1 + land;
        break;
      }
      case "flee": {
        ox = -this.facing * (t / 600) * 400;
        this.alpha = Math.max(0, 1 - t / 700);
        break;
      }
    }
    this.offsetX = ox;
    this.offsetY = oy;
    this.sx = sx;
    this.sy = sy;
    this.rot = rot;
    const s = this.size;
    const cx = this.baseX + ox;
    const cy = this.baseY + oy;
    this.anchors.muzzle = [cx + this.facing * s * 0.42, cy - s * 0.02];
    this.anchors.head = [cx, cy - s * 0.42];
    this.anchors.chest = [cx, cy + s * 0.05];
    this.anchors.feet = [cx, cy + s * 0.44];
  }

  draw(g: CanvasRenderingContext2D, now: number): void {
    if (!this.sprite) return;
    const s = this.size;
    g.save();
    g.globalAlpha = this.alpha;
    g.translate(this.baseX + this.offsetX, this.baseY + this.offsetY);
    g.rotate(this.rot);
    g.scale(this.sx * this.facing, this.sy);
    g.imageSmoothingEnabled = false;
    const base = this.grayscale ? spriteVariant(this.sprite, "gray") : this.soot > 0 ? spriteVariant(this.sprite, "dark") : this.sprite;
    g.drawImage(base, -s / 2, -s / 2, s, s);
    if (this.tint && now < this.tintUntil) {
      g.globalAlpha = 0.8 * this.alpha;
      g.drawImage(spriteVariant(this.sprite, this.tint), -s / 2, -s / 2, s, s);
    }
    g.restore();
  }
}
