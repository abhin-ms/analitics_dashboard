const API_BASE = "/api/v1";

class ApiClient {
  private accessToken: string | null = null;
  private onTokenRefreshed: ((token: string) => void) | null = null;

  setToken(token: string | null) {
    this.accessToken = token;
  }

  setOnTokenRefreshed(cb: (token: string) => void) {
    this.onTokenRefreshed = cb;
  }

  private async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };

    if (this.accessToken) {
      headers["Authorization"] = `Bearer ${this.accessToken}`;
    }

    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      credentials: "include",
    });

    if (res.status === 401 && !path.startsWith("/auth/")) {
      const refreshed = await this.refresh();
      if (refreshed) {
        headers["Authorization"] = `Bearer ${this.accessToken}`;
        const retryRes = await fetch(`${API_BASE}${path}`, {
          ...options,
          headers,
          credentials: "include",
        });
        if (!retryRes.ok) {
          const err = await retryRes.json().catch(() => ({}));
          throw new Error(err.detail || `Request failed: ${retryRes.status}`);
        }
        return retryRes.json();
      }
      window.location.href = "/login";
      throw new Error("Session expired");
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed: ${res.status}`);
    }

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
   * refreshes-and-retries once on a 401. Path is relative to /api/v1.
   * Use this instead of raw fetch() so pages don't fall out of sync
   * with the token after a silent refresh.
   */
  async fetchRaw(path: string, options: RequestInit = {}): Promise<Response> {
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };
    if (this.accessToken) {
      headers["Authorization"] = `Bearer ${this.accessToken}`;
    }

    const doFetch = () =>
      fetch(`${API_BASE}${path}`, { ...options, headers, credentials: "include" });

    let res = await doFetch();
    if (res.status === 401 && !path.startsWith("/auth/")) {
      const refreshed = await this.refresh();
      if (refreshed) {
        headers["Authorization"] = `Bearer ${this.accessToken}`;
        res = await doFetch();
      } else {
        window.location.href = "/login";
      }
    }
    return res;
  }

  private async refresh(): Promise<boolean> {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) return false;
      const data = await res.json();
      this.accessToken = data.access_token;
      this.onTokenRefreshed?.(data.access_token);
      return true;
    } catch {
      return false;
    }
  }
}

export const api = new ApiClient();
