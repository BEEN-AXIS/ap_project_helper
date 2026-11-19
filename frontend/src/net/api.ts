import { sessionHint, useAuth, type Profile } from "../state/auth";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

let refreshing: Promise<boolean> | null = null;

export async function refreshSession(): Promise<boolean> {
  if (!sessionHint()) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const r = await fetch("/api/auth/refresh", { method: "POST", credentials: "include" });
        if (!r.ok) return false;
        const d = (await r.json()) as { access_token: string; profile: Profile };
        useAuth.getState().setSession(d.access_token, d.profile);
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

async function parse(r: Response): Promise<unknown> {
  const text = await r.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { error: { code: "server_error", message: text.slice(0, 200) } };
  }
}

/** JSON over REST. The acting user always comes from the bearer token. */
export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; retry?: boolean } = {}): Promise<T> {
  const token = useAuth.getState().token;
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["content-type"] = "application/json";
  if (token) headers.authorization = `Bearer ${token}`;
  const r = await fetch(`/api${path}`, {
    method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
    headers,
    credentials: "include",
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (r.status === 401 && opts.retry !== false && !path.startsWith("/auth/")) {
    if (await refreshSession()) return api<T>(path, { ...opts, retry: false });
    useAuth.getState().clear();
  }
  const data = (await parse(r)) as any;
  if (!r.ok) {
    const e = data?.error ?? {};
    throw new ApiError(r.status, e.code ?? "server_error", e.message ?? r.statusText, e.details ?? {});
  }
  return data as T;
}

export async function wsTicket(scope: "lobby" | "match", matchId?: string): Promise<string> {
  const d = await api<{ ticket: string }>("/auth/ws-ticket", { body: { scope, match_id: matchId } });
  return d.ticket;
}

export async function loadMe(): Promise<Profile> {
  const me = await api<Profile>("/me");
  useAuth.getState().setProfile(me);
  return me;
}

export function wsUrl(path: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}
