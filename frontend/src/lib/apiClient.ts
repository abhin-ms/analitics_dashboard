const API_BASE = "/api/v1";

/** A failed API call, with its HTTP status so callers can tell "signed
 * out" (401/403) apart from a network blip (status 0) or a server error. */
export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

/** Result of renewing the 15-minute access pass with the refresh cookie. */
export type RenewResult = "ok" | "denied" | "offline";

// The session calls themselves never trigger a renewal. /auth/me is
// deliberately NOT listed: when the app is reopened with an expired pass,
// "who am I?" must renew like any other call — skipping it is what used to
// sign people out after 15 idle minutes.
const NO_RENEW = ["/auth/login", "/auth/refresh", "/auth/logout", "/auth/forgot-password", "/auth/set-password"];
const shouldRenew = (path: string) => !NO_RENEW.some((p) => path.startsWith(p));

async function errorFrom(res: Response): Promise<ApiError> {
  const err = await res.json().catch(() => ({}));
  return new ApiError(err.detail || `Request failed: ${res.status}`, res.status);
}

class ApiClient {
  private accessToken: string | null = null;
  private onTokenRefreshed: ((token: string) => void) | null = null;
  private onSessionEnded: (() => void) | null = null;
  private renewing: Promise<RenewResult> | null = null;
  private loggingOut = false;
  private pendingLogout: Promise<void> | null = null;

  setToken(token: string | null) {
    this.accessToken = token;
    if (token) this.loggingOut = false; // signed in again
  }

  /**
   * Sign out of this browser. The pass is dropped at once (the UI can show
   * the login page immediately) and renewals stop. The server is asked to
   * delete the cookie right away — and, if a renewal was still in flight,
   * once more after it lands, because that late renewal's response would
   * otherwise re-set the cookie and revive the session. keepalive lets the
   * request complete even if the tab is closed right after.
   */
  logout(): Promise<void> {
    this.loggingOut = true;
    this.accessToken = null;
    const inFlight = this.renewing;
    const deleteCookie = () =>
      fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include", keepalive: true })
        .then(() => undefined, () => undefined); // offline: the local session is already gone
    this.pendingLogout = (async () => {
      await deleteCookie();
      if (inFlight) {
        await inFlight;
        await deleteCookie();
      }
    })().finally(() => {
      this.pendingLogout = null;
    });
    return this.pendingLogout;
  }

  /** Signing in waits for a sign-out still finishing, so its cookie deletion
   * can't land after (and wipe) the new session's cookie. */
  async settleLogout(): Promise<void> {
    if (this.pendingLogout) await this.pendingLogout;
  }

  setOnTokenRefreshed(cb: (token: string) => void) {
    this.onTokenRefreshed = cb;
  }

  /** Called when the server says the session is over (refresh rejected). */
  setOnSessionEnded(cb: () => void) {
    this.onSessionEnded = cb;
  }

  private sessionEnded() {
    this.accessToken = null;
    this.onSessionEnded?.();
  }

  private async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };
    const send = () => {
      if (this.accessToken) headers["Authorization"] = `Bearer ${this.accessToken}`;
      return fetch(`${API_BASE}${path}`, { ...options, headers, credentials: "include" });
    };

    let res: Response;
    try {
      res = await send();
    } catch {
      throw new ApiError("Can't reach the server — check your connection", 0);
    }

    if (res.status === 401 && shouldRenew(path)) {
      const renewed = await this.renewSession();
      if (renewed === "denied") {
        this.sessionEnded();
        throw new ApiError("Your session has ended — please sign in again", 401);
      }
      if (renewed === "offline") throw new ApiError("Can't reach the server — check your connection", 0);
      try {
        res = await send();
      } catch {
        throw new ApiError("Can't reach the server — check your connection", 0);
      }
    }

    if (!res.ok) throw await errorFrom(res);
    if (res.status === 204) return undefined as T;
    return res.json();
  }

  async get<T>(path: string): Promise<T> {
    return this.request<T>(path, { method: "GET" });
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  async put<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>(path, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  async patch<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>(path, {
      method: "PATCH",
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  async del<T>(path: string): Promise<T> {
    return this.request<T>(path, { method: "DELETE" });
  }

  /**
   * Like fetch(), but attaches the current bearer token and silently
   * renews-and-retries once on a 401. Path is relative to /api/v1.
   * Use this instead of raw fetch() so pages don't fall out of sync
   * with the token after a silent renewal.
   */
  async fetchRaw(path: string, options: RequestInit = {}): Promise<Response> {
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };
    const send = () => {
      if (this.accessToken) headers["Authorization"] = `Bearer ${this.accessToken}`;
      return fetch(`${API_BASE}${path}`, { ...options, headers, credentials: "include" });
    };

    let res = await send();
    if (res.status === 401 && shouldRenew(path)) {
      const renewed = await this.renewSession();
      if (renewed === "ok") res = await send();
      else if (renewed === "denied") this.sessionEnded();
    }
    return res;
  }

  /**
   * Swap the refresh cookie for a new 15-minute access pass (and a renewed
   * cookie). Concurrent callers share one request, so a burst of expired
   * calls after the app wakes up triggers a single renewal.
   */
  renewSession(): Promise<RenewResult> {
    if (this.loggingOut) return Promise.resolve("denied");
    if (!this.renewing) {
      this.renewing = (async (): Promise<RenewResult> => {
        try {
          const res = await fetch(`${API_BASE}/auth/refresh`, {
            method: "POST",
            credentials: "include",
          });
          if (res.status === 401 || res.status === 403) return "denied";
          if (!res.ok) return "offline";
          const data = await res.json();
          if (this.loggingOut) return "denied"; // logout started meanwhile: don't revive the session
          this.accessToken = data.access_token;
          this.onTokenRefreshed?.(data.access_token);
          return "ok";
        } catch {
          return "offline";
        }
      })().finally(() => {
        this.renewing = null;
      });
    }
    return this.renewing;
  }
}

export const api = new ApiClient();
