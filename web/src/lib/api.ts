// Cliente HTTP do painel. Autentica pelo cookie de sessão (HttpOnly) e envia o header que a API
// exige contra CSRF em requisições que alteram dados.

export const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public termosPendentes = false,
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function qs(params: Query): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v)) v.forEach((item) => sp.append(k, String(item)));
    else sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

let onUnauthorized: (() => void) | null = null;
let onTermsPending: (() => void) | null = null;

export function setAuthHandlers(handlers: { unauthorized: () => void; termsPending: () => void }) {
  onUnauthorized = handlers.unauthorized;
  onTermsPending = handlers.termsPending;
}

export async function api<T>(path: string, init: RequestInit & { query?: Query } = {}): Promise<T> {
  const { query, ...rest } = init;
  const headers = new Headers(rest.headers);
  headers.set("X-Requested-With", "cnpj-web");
  if (rest.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(`${API_BASE}${path}${query ? qs(query) : ""}`, {
    ...rest,
    headers,
    credentials: "same-origin",
  });
  if (res.status === 204) return undefined as T;
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = typeof body === "object" && body && "detail" in body ? body.detail : body;
    const message = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : String(detail || res.statusText);
    const termos = res.status === 403 && res.headers.has("X-Termos-Pendentes");
    if (res.status === 401 && !path.startsWith("/v1/auth/login")) onUnauthorized?.();
    if (termos) onTermsPending?.();
    throw new ApiError(res.status, message, termos);
  }
  return body as T;
}

export const post = <T>(path: string, data?: unknown) =>
  api<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data) });
export const patch = <T>(path: string, data: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(data) });
export const put = <T>(path: string, data: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(data) });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });
