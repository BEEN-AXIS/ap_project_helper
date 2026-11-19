import { create } from "zustand";
import { api } from "../net/api";

export interface Settings {
  master: number;
  effects: number;
  music: boolean;
  quality: "auto" | "high" | "low" | "off";
  reducedMotion: "auto" | "on" | "off";
  shake: number;
  flash: number;
  crt: boolean;
  cbPalette: boolean;
  fontSize: number;
  muted: boolean;
  autoBot: boolean;
  language: string;
}

export const DEFAULT_SETTINGS: Settings = {
  master: 0.7,
  effects: 0.8,
  music: false,
  quality: "auto",
  reducedMotion: "auto",
  shake: 1,
  flash: 1,
  crt: false,
  cbPalette: false,
  fontSize: 14,
  muted: false,
  autoBot: false,
  language: "en",
};

const KEY = "algoarena.settings";

function load(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : DEFAULT_SETTINGS;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

let saveTimer: number | undefined;

interface SettingsStore {
  s: Settings;
  set: (patch: Partial<Settings>) => void;
  hydrate: (server: Partial<Settings> | undefined) => void;
}

export const useSettings = create<SettingsStore>((set, get) => ({
  s: load(),
  set: (patch) => {
    const next = { ...get().s, ...patch };
    set({ s: next });
    applyDocumentSettings(next);
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* storage can be unavailable; settings stay in memory */
    }
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => void api("/me/settings", { method: "PATCH", body: { settings: next } }).catch(() => {}), 1200);
  },
  hydrate: (server) => {
    if (!server || Object.keys(server).length === 0) return;
    const next = { ...DEFAULT_SETTINGS, ...server, ...{} } as Settings;
    set({ s: next });
    applyDocumentSettings(next);
  },
}));

export function prefersReducedMotion(s: Settings = useSettings.getState().s): boolean {
  if (s.reducedMotion === "on") return true;
  if (s.reducedMotion === "off") return false;
  return typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function applyDocumentSettings(s: Settings): void {
  const root = document.documentElement;
  root.dataset.palette = s.cbPalette ? "cb" : "default";
  root.dataset.reducedMotion = s.reducedMotion;
  document.body.classList.toggle("crt", s.crt);
}
