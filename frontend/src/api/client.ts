import type { ApiErrorBody } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:47823";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly body: ApiErrorBody;

  constructor(status: number, code: string | null, body: ApiErrorBody) {
    super(extractMessage(body) ?? `API error ${status}`);
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

function extractMessage(body: ApiErrorBody): string | undefined {
  if (typeof body.detail === "string") return body.detail;
  return body.detail?.message;
}

function extractCode(body: ApiErrorBody): string | null {
  if (typeof body.detail === "object" && body.detail !== null) {
    return body.detail.error ?? null;
  }
  return null;
}

export interface FetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Skip the global 401-redirect (useful for /auth/me probes). */
  skipAuthRedirect?: boolean;
}

export async function apiFetch<T>(
  path: string,
  opts: FetchOptions = {},
): Promise<T> {
  const { body, skipAuthRedirect, headers, ...rest } = opts;
  const init: RequestInit = {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(headers ?? {}),
    },
  };
  if (body !== undefined) init.body = JSON.stringify(body);

  const res = await fetch(`${BASE}${path}`, init);

  if (res.status === 401 && !skipAuthRedirect) {
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
  }

  if (res.status === 204) return undefined as T;

  let parsed: unknown = null;
  if (res.headers.get("content-type")?.includes("application/json")) {
    parsed = await res.json().catch(() => null);
  }

  if (!res.ok) {
    const errBody: ApiErrorBody = (parsed as ApiErrorBody) ?? {};
    throw new ApiError(res.status, extractCode(errBody), errBody);
  }

  return parsed as T;
}
