import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, navigate } from "../app/router";
import { t } from "../i18n";
import { fmt, tierColor } from "../lib/format";
import { api, ApiError, loadMe } from "../net/api";
import { useAuth, type MatchBrief, type Profile } from "../state/auth";

type Mode = "ranked" | "bot" | "practice";
const MAPS = [
  { id: "bit", minTier: 1 },
  { id: "binary", minTier: 1 },
  { id: "prestige", minTier: 3 },
];

export function TierBadge({ tier, title }: { tier: number; title?: string }) {
  return (
    <span className="pixel rounded px-1.5 py-1 text-[9px] text-slate-950" style={{ background: tierColor(tier) }}>
      {title ?? `T${tier}`}
    </span>
  );
}

function ProfileCard({ p }: { p: Profile }) {
  const nextHp = p.next_tier?.max_hp;
  return (
    <section className="panel p-4" data-testid="profile-card">
      <div className="flex items-center gap-3">
        <div className="h-12 w-12 rounded-full border-4 border-slate-900" style={{ background: p.avatar_color }} aria-hidden />
        <div className="flex-1">
          <div className="text-lg font-bold">{p.display_name}</div>
          <div className="flex items-center gap-2 text-sm">
            <TierBadge tier={p.tier} title={p.tier_title} />
            <span className="pixel text-[10px] text-yellow-300" data-testid="my-rating">
              {p.rating}
            </span>
          </div>
        </div>
      </div>
      <div className="mt-3">
        <div className="mb-1 flex justify-between text-xs text-slate-400">
          <span>HP {fmt(p.max_hp)}</span>
          {nextHp && <span>{t("lobby.next_tier_hp", { hp: fmt(nextHp) })}</span>}
        </div>
        <div className="hp-track">
          <div className="hp-fill" style={{ width: `${nextHp ? (p.max_hp / nextHp) * 100 : 100}%`, background: "var(--hp-high)" }} />
          {nextHp && <div className="absolute inset-y-0 right-0 w-1 bg-slate-300/60" title="next tier" />}
        </div>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center text-sm">
        <div>
          <div className="pixel text-xs text-green-400">{p.wins}</div>W
        </div>
        <div>
          <div className="pixel text-xs text-red-400">{p.losses}</div>L
        </div>
        <div>
          <div className="pixel text-xs text-slate-300">{p.draws}</div>D
        </div>
      </div>
    </section>
  );
}

export function MatchRow({ m }: { m: MatchBrief }) {
  const me = m.your_side;
  const opp = m.players.find((p) => p.side !== me);
  const label = me ? m.labels?.[String(me)] : null;
  return (
    <Link to={`/result/${m.id}`} className="flex items-center justify-between rounded px-2 py-1.5 text-sm hover:bg-slate-700">
      <span className="truncate">
        <span className={label === "victory" || label === "hollow_victory" ? "text-green-400" : label === "draw" ? "text-slate-300" : m.status === "aborted" ? "text-slate-500" : "text-red-400"}>
          {label ? t(`result.${label}`) : m.status === "aborted" ? t("result.aborted") : m.status}
        </span>{" "}
        vs {opp?.name}
        {opp?.is_bot && " (BOT)"}
      </span>
      <span className="text-xs text-slate-400">
        {m.rating_delta !== null && m.rating_delta !== undefined ? (m.rating_delta >= 0 ? `+${m.rating_delta}` : m.rating_delta) : "–"}
      </span>
    </Link>
  );
}

export default function Lobby() {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: loadMe, refetchInterval: 15000 });
  const { data: lb } = useQuery({ queryKey: ["lb", "all"], queryFn: () => api<{ rows: { rank: number; name: string; rating: number; tier: number }[] }>("/leaderboard") });
  const [mode, setMode] = useState<Mode>("ranked");
  const [map, setMap] = useState("bit");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const profile = me ?? useAuth.getState().profile;
  if (!profile) return <div className="p-8 text-slate-400">{t("common.loading")}</div>;

  const start = async () => {
    setErr(null);
    setBusy(true);
    try {
      if (mode === "ranked") {
        await api("/queue/join", { body: { mode: "ranked", map } });
        navigate("/queue");
      } else {
        const r = await api<{ match_id: string }>(mode === "bot" ? "/matches/bot" : "/matches/practice", { body: { map: map === "any" ? "bit" : map } });
        navigate(`/battle/${r.match_id}`);
      }
    } catch (e) {
      if (e instanceof ApiError && e.code === "conflict" && e.details.match_id) navigate(`/battle/${e.details.match_id}`);
      else setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const claim = async (id: string) => {
    await api(`/quests/${id}/claim`, { body: {} }).catch(() => {});
    void qc.invalidateQueries({ queryKey: ["me"] });
  };

  const tiles: { id: Mode | "team"; label: string; note?: string }[] = [
    { id: "ranked", label: t("lobby.ranked") },
    { id: "bot", label: t("lobby.bot"), note: t("lobby.bot_label") },
    { id: "practice", label: t("lobby.practice"), note: t("lobby.practice_note") },
    { id: "team", label: t("lobby.team"), note: t("lobby.soon") },
  ];
  return (
    <div className="mx-auto grid max-w-6xl gap-4 p-4 lg:grid-cols-[20rem_1fr_18rem]">
      <div className="space-y-4">
        <ProfileCard p={profile} />
        {profile.active_match && (
          <button className="btn btn-primary w-full" onClick={() => navigate(`/battle/${profile.active_match}`)}>
            {t("lobby.resume")}
          </button>
        )}
        <section className="panel p-4">
          <h2 className="pixel mb-2 text-[10px] text-slate-400">{t("lobby.quests")}</h2>
          {(profile.quests ?? []).map((q) => (
            <div key={q.id} className="mb-2 text-sm">
              <div className="flex justify-between gap-2">
                <span>{t(`quest.${q.id}`)}</span>
                <span className="text-yellow-300">{q.ap} AP</span>
              </div>
              <div className="mt-1 flex items-center gap-2">
                <div className="h-2 flex-1 rounded bg-slate-900">
                  <div className="h-2 rounded bg-yellow-400" style={{ width: `${(q.progress / q.target) * 100}%` }} />
                </div>
                {q.complete && !q.claimed && (
                  <button className="rounded bg-yellow-500 px-2 text-xs font-bold text-yellow-950" onClick={() => void claim(q.id)}>
                    {t("lobby.claim")}
                  </button>
                )}
                {q.claimed && <span className="text-xs text-slate-500">{t("lobby.claimed")}</span>}
              </div>
            </div>
          ))}
        </section>
      </div>

      <section className="panel space-y-4 p-4">
        <div className="grid grid-cols-2 gap-3">
          {tiles.map((tile) => (
            <button
              key={tile.id}
              disabled={tile.id === "team"}
              onClick={() => tile.id !== "team" && setMode(tile.id)}
              className={`rounded-xl border-2 p-4 text-left transition ${mode === tile.id ? "border-green-400 bg-green-900/30" : "border-slate-600 bg-slate-700/40 hover:border-slate-400"} disabled:opacity-40`}
              data-testid={`mode-${tile.id}`}
            >
              <div className="font-bold">{tile.label}</div>
              {tile.note && <div className="mt-1 text-xs text-slate-400">{tile.note}</div>}
            </button>
          ))}
        </div>
        <div>
          <h3 className="pixel mb-2 text-[10px] text-slate-400">{t("lobby.map")}</h3>
          <div className="flex flex-wrap gap-2">
            {[...MAPS, ...(mode === "ranked" ? [{ id: "any", minTier: 1 }] : [])].map((m) => {
              const locked = profile.tier < m.minTier;
              return (
                <button key={m.id} disabled={locked} onClick={() => setMap(m.id)} className={`rounded-lg border-2 px-3 py-2 text-sm ${map === m.id ? "border-cyan-400 bg-cyan-900/30" : "border-slate-600"} disabled:opacity-40`} title={locked ? t("map.locked", { tier: m.minTier }) : ""}>
                  {t(`map.${m.id}`)}
                  {locked && ` 🔒`}
                </button>
              );
            })}
          </div>
        </div>
        {err && <div className="rounded bg-red-950 px-3 py-2 text-sm text-red-300">{err}</div>}
        <button className="btn btn-primary w-full !min-h-12 text-base" disabled={busy} onClick={() => void start()} data-testid="start">
          {mode === "ranked" ? t("lobby.queue") : mode === "bot" ? t("lobby.fight_bot") : t("lobby.start_practice")}
        </button>
        <div>
          <h3 className="pixel mb-2 text-[10px] text-slate-400">{t("lobby.recent")}</h3>
          {(profile.recent_matches ?? []).length === 0 ? <p className="text-sm text-slate-500">{t("lobby.no_recent")}</p> : profile.recent_matches!.map((m) => <MatchRow key={m.id} m={m} />)}
        </div>
      </section>

      <section className="panel p-4">
        <h2 className="pixel mb-2 text-[10px] text-slate-400">{t("lobby.top5")}</h2>
        {(lb?.rows ?? []).slice(0, 5).map((r) => (
          <div key={r.rank} className="flex items-center justify-between py-1 text-sm">
            <span>
              #{r.rank} {r.name}
            </span>
            <span className="flex items-center gap-1">
              <TierBadge tier={r.tier} /> <span className="text-yellow-300">{r.rating}</span>
            </span>
          </div>
        ))}
        <Link to="/leaderboard" className="mt-2 block text-sm text-cyan-300">
          {t("nav.leaderboard")} →
        </Link>
      </section>
    </div>
  );
}
