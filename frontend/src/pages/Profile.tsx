import { useQuery } from "@tanstack/react-query";
import { Link } from "../app/router";
import { t } from "../i18n";
import { tierColor } from "../lib/format";
import { api, ApiError } from "../net/api";
import type { MatchBrief } from "../state/auth";
import { MatchRow, TierBadge } from "./Lobby";

interface PublicProfile {
  display_name: string;
  rating: number;
  peak_rating: number;
  tier: number;
  tier_title: string;
  wins: number;
  losses: number;
  draws: number;
  badges: string[];
  avatar_color: string;
  rating_history: { before: number; after: number; delta: number; at: string; match_id: string }[];
  matches: MatchBrief[];
  accuracy: { accepted: number; judged: number };
}

function RatingChart({ points }: { points: number[] }) {
  if (points.length < 2) return <p className="text-sm text-slate-500">Play a few matches to draw the chart.</p>;
  const W = 600;
  const H = 160;
  const lo = Math.min(...points) - 20;
  const hi = Math.max(...points) + 20;
  const xy = points.map((p, i) => [(i / (points.length - 1)) * W, H - ((p - lo) / (hi - lo)) * H]);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-40 w-full" role="img" aria-label="Rating history">
      {[1200, 1400, 1600, 1900].filter((r) => r > lo && r < hi).map((r, i) => (
        <line key={r} x1={0} x2={W} y1={H - ((r - lo) / (hi - lo)) * H} y2={H - ((r - lo) / (hi - lo)) * H} stroke={tierColor(i + 2)} strokeDasharray="4 4" opacity={0.5} />
      ))}
      <polyline fill="none" stroke="#22c55e" strokeWidth={2.5} points={xy.map((p) => p.join(",")).join(" ")} />
      {xy.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={3} fill="#bbf7d0" />
      ))}
    </svg>
  );
}

export default function Profile({ params }: { params: { username: string } }) {
  const { data, error } = useQuery({ queryKey: ["profile", params.username], queryFn: () => api<PublicProfile>(`/profiles/${params.username}`) });
  if (error) return <div className="p-8 text-red-300">{error instanceof ApiError ? error.message : String(error)}</div>;
  if (!data) return <div className="p-8 text-slate-400">{t("common.loading")}</div>;
  const points = data.rating_history.length ? [data.rating_history[0].before, ...data.rating_history.map((h) => h.after)] : [];
  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4">
      <section className="panel flex items-center gap-4 p-4">
        <div className="h-16 w-16 rounded-full border-4 border-slate-900" style={{ background: data.avatar_color }} />
        <div>
          <h1 className="text-xl font-bold">{data.display_name}</h1>
          <div className="mt-1 flex items-center gap-2">
            <TierBadge tier={data.tier} title={data.tier_title} />
            <span className="text-yellow-300">{data.rating}</span>
            <span className="text-xs text-slate-400">peak {data.peak_rating}</span>
          </div>
        </div>
        <div className="ml-auto grid grid-cols-4 gap-4 text-center text-sm">
          <div>
            <div className="pixel text-xs text-green-400">{data.wins}</div>W
          </div>
          <div>
            <div className="pixel text-xs text-red-400">{data.losses}</div>L
          </div>
          <div>
            <div className="pixel text-xs">{data.draws}</div>D
          </div>
          <div>
            <div className="pixel text-xs">{data.accuracy.judged ? Math.round((100 * data.accuracy.accepted) / data.accuracy.judged) : 0}%</div>
            {t("stat.accuracy")}
          </div>
        </div>
      </section>
      <section className="panel p-4">
        <RatingChart points={points} />
      </section>
      {data.badges.length > 0 && (
        <section className="panel flex flex-wrap gap-2 p-4">
          {data.badges.map((b) => (
            <span key={b} className="rounded bg-purple-900/50 px-2 py-1 text-sm">
              🏅 {t(`ach.${b}`)}
            </span>
          ))}
        </section>
      )}
      <section className="panel p-4">
        <h2 className="pixel mb-2 text-[10px] text-slate-400">{t("lobby.recent")}</h2>
        {data.matches.map((m) => (
          <div key={m.id} className="flex items-center gap-2">
            <div className="flex-1">
              <MatchRow m={m} />
            </div>
            {m.status === "finished" && (
              <Link to={`/replay/${m.id}`} className="text-xs text-cyan-300">
                {t("result.replay")}
              </Link>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
