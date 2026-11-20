import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { t } from "../i18n";
import { useSettings, type Settings } from "../state/settings";

/** A modal that traps focus. Settings are saved locally and to the profile. */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    const prev = document.activeElement as HTMLElement | null;
    el?.querySelector<HTMLElement>("button, input, select")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key !== "Tab" || !el) return;
      const f = Array.from(el.querySelectorAll<HTMLElement>("button, input, select, a[href], textarea"));
      if (!f.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [onClose]);
  // Rendered at the page root: an ancestor with a backdrop blur or transform
  // (like the sticky header) would otherwise trap this fixed overlay in its box.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div ref={ref} className="panel my-auto flex max-h-[calc(100dvh-2rem)] w-full max-w-md flex-col p-5">
        <div className="mb-4 flex shrink-0 items-center justify-between">
          <h2 className="pixel text-xs text-green-400">{title}</h2>
          <button className="btn btn-ghost !min-h-8 !px-2" onClick={onClose} aria-label={t("common.close")}>
            ✕
          </button>
        </div>
        <div className="-mr-2 min-h-0 overflow-y-auto pr-2">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center justify-between gap-4 py-1.5 text-sm text-slate-300">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const { s, set } = useSettings();
  const slider = (k: keyof Settings, max = 1, step = 0.05) => (
    <input type="range" min={0} max={max} step={step} value={s[k] as number} onChange={(e) => set({ [k]: Number(e.target.value) } as Partial<Settings>)} />
  );
  return (
    <Modal title={t("settings.title")} onClose={onClose}>
      <Row label={t("settings.volume")}>{slider("master")}</Row>
      <Row label={t("settings.effects")}>{slider("effects")}</Row>
      <Row label={t("settings.music")}>
        <input type="checkbox" checked={s.music} onChange={(e) => set({ music: e.target.checked })} />
      </Row>
      <Row label={t("settings.quality")}>
        <select className="rounded bg-slate-800 px-2 py-1" value={s.quality} onChange={(e) => set({ quality: e.target.value as Settings["quality"] })}>
          <option value="auto">{t("common.auto")}</option>
          <option value="high">{t("common.high")}</option>
          <option value="low">{t("common.low")}</option>
          <option value="off">{t("common.off")}</option>
        </select>
      </Row>
      <Row label={t("settings.reduced_motion")}>
        <select className="rounded bg-slate-800 px-2 py-1" value={s.reducedMotion} onChange={(e) => set({ reducedMotion: e.target.value as Settings["reducedMotion"] })}>
          <option value="auto">{t("common.auto")}</option>
          <option value="on">{t("common.on")}</option>
          <option value="off">{t("common.off")}</option>
        </select>
      </Row>
      <Row label={t("settings.shake")}>{slider("shake")}</Row>
      <Row label={t("settings.flash")}>{slider("flash")}</Row>
      <Row label={t("settings.crt")}>
        <input type="checkbox" checked={s.crt} onChange={(e) => set({ crt: e.target.checked })} />
      </Row>
      <Row label={t("settings.cb")}>
        <input type="checkbox" checked={s.cbPalette} onChange={(e) => set({ cbPalette: e.target.checked })} />
      </Row>
      <Row label={t("settings.font")}>
        <input type="number" min={11} max={24} className="w-16 rounded bg-slate-800 px-2 py-1" value={s.fontSize} onChange={(e) => set({ fontSize: Number(e.target.value) })} />
      </Row>
    </Modal>
  );
}
