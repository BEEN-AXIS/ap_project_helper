import { useEffect, useState } from "react";
import { t } from "../i18n";
import { api } from "../net/api";
import { loadRegistry } from "../skins/registry";
import { useAuth } from "../state/auth";
import { Link, navigate, RouterView, usePath } from "./router";
import { SettingsModal } from "./SettingsModal";

function NotFound() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4">
      <div className="pixel text-sm text-slate-400">404</div>
      <Link to="/lobby" className="btn btn-ghost">
        {t("result.back")}
      </Link>
    </div>
  );
}

export function SandboxBadge() {
  const judge = useAuth((s) => s.profile?.judge);
  if (!judge || judge.sandboxed) return null;
  const label = judge.backend === "fake" ? t("app.test_judge") : t("app.dev_sandbox");
  return (
    <span className="pixel rounded border border-orange-400 bg-orange-900/60 px-2 py-1 text-[9px] text-orange-200" title={label} role="note">
      {judge.backend === "fake" ? "TEST JUDGE" : "DEV SANDBOX"}
    </span>
  );
}

function Nav() {
  const profile = useAuth((s) => s.profile);
  const path = usePath();
  const [settings, setSettings] = useState(false);
  if (!profile || path.startsWith("/battle/") || path === "/") return null;
  const items: [string, string][] = [
    ["/lobby", "nav.lobby"],
    ["/practice", "nav.practice"],
    ["/locker", "nav.locker"],
    ["/leaderboard", "nav.leaderboard"],
    [`/profile/${profile.display_name}`, "nav.profile"],
  ];
  if (profile.role === "admin") items.push(["/admin", "nav.admin"]);
  return (
    <header className="sticky top-0 z-30 flex items-center gap-3 border-b-2 border-slate-700 bg-slate-900/90 px-4 py-2 backdrop-blur">
      <Link to="/lobby" className="pixel text-xs text-green-400">
        ALGOARENA
      </Link>
      <nav className="flex flex-1 flex-wrap gap-1" aria-label="Main">
        {items.map(([to, key]) => (
          <Link key={to} to={to} className={`rounded px-3 py-1.5 text-sm ${path === to ? "bg-slate-700 text-white" : "text-slate-300 hover:bg-slate-800"}`}>
            {t(key)}
          </Link>
        ))}
      </nav>
      <SandboxBadge />
      <span className="pixel text-[10px] text-yellow-300">{profile.points ?? 0} AP</span>
      <button className="btn btn-ghost !min-h-8 !px-2 text-xs" onClick={() => setSettings(true)} aria-label={t("settings.title")}>
        ⚙
      </button>
      <button
        className="btn btn-ghost !min-h-8 !px-2 text-xs"
        onClick={async () => {
          await api("/auth/logout", { body: {} }).catch(() => {});
          useAuth.getState().clear();
          navigate("/");
        }}
      >
        {t("nav.logout")}
      </button>
      {settings && <SettingsModal onClose={() => setSettings(false)} />}
    </header>
  );
}

export function App() {
  const ready = useAuth((s) => s.ready);
  const authed = useAuth((s) => !!s.token);
  useEffect(() => {
    void loadRegistry();
  }, []);
  if (!ready) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="pixel animate-pulse text-xs text-green-400">ALGOARENA</div>
      </div>
    );
  }
  return (
    <div className="flex min-h-full flex-col">
      <Nav />
      <main className="flex-1">
        <RouterView authed={authed} NotFound={NotFound} />
      </main>
    </div>
  );
}
