import { create } from "zustand";
import { persist } from "zustand/middleware";
import { api, ApiError } from "./apiClient";

export interface Permission {
  resource: string;
  action: string;
}

export interface User {
  id: number;
  name: string;
  email: string;
  role_id: number;
  role_name: string;
  is_active: boolean;
  permissions: Permission[];
  store_ids: number[];
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  fetchMe: () => Promise<void>;
  hasPermission: (resource: string, action: string) => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,

      login: async (email: string, password: string) => {
        await api.settleLogout();
        const res = await api.post<{ access_token: string }>("/auth/login", {
          email,
          password,
        });
        api.setToken(res.access_token);
        set({ token: res.access_token, isAuthenticated: true });
        await get().fetchMe();
      },

      logout: async () => {
        // Signed out here immediately; the server-side cookie deletion
        // finishes in the background (after any renewal in flight).
        void api.logout();
        set({ user: null, token: null, isAuthenticated: false });
      },

      fetchMe: async () => {
        try {
          const user = await api.get<User>("/auth/me");
          set({ user, isAuthenticated: true });
        } catch (e) {
          if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
            // The server ended the session (logged out elsewhere by a
            // password change, deactivated, or 90 days unused).
            api.setToken(null);
            set({ user: null, token: null, isAuthenticated: false });
          } else {
            // Network blip, server restart or deploy: stay signed in and
            // try again shortly instead of throwing the user out.
            window.setTimeout(() => {
              if (get().token) get().fetchMe();
            }, 5000);
          }
        }
      },

      hasPermission: (resource: string, action: string) => {
        const user = get().user;
        if (!user) return false;
        return user.permissions.some(
          (p) => p.resource === resource && p.action === action
        );
      },
    }),
    {
      name: "bp-auth",
      partialize: (state) => ({ token: state.token }),
      onRehydrateStorage: () => (state) => {
        if (state?.token) {
          state.isAuthenticated = true;
          api.setToken(state.token);
          state.fetchMe();
        }
      },
    }
  )
);

api.setOnTokenRefreshed((token) => {
  useAuthStore.setState({ token });
});

// Refresh rejected: clear the session; AppLayout then shows the login page.
api.setOnSessionEnded(() => {
  useAuthStore.setState({ user: null, token: null, isAuthenticated: false });
});
