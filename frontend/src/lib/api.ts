import { ApiError } from "./chatClient";

const TOKEN_KEY = "staff_token";

export function getStaffToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setStaffToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: the session simply does not persist */
  }
}

/** Fetch wrapper for the admin API: JSON in/out, bearer token, structured errors. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getStaffToken();
  if (token) headers.set("authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("content-type", "application/json");
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401 && token) {
    setStaffToken(null);
    window.dispatchEvent(new Event("staff-logout"));
  }
  if (!response.ok) {
    let code = "http_error";
    let message = response.statusText || "Request failed";
    try {
      const body = await response.json();
      code = body?.error?.code ?? code;
      message = body?.error?.message ?? message;
    } catch {
      /* empty or non-JSON body */
    }
    throw new ApiError(response.status, code, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const fetchJson = <T,>(path: string) => () => api<T>(path);
