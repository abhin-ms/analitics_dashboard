import { io, Socket } from "socket.io-client";
import { useAuthStore } from "./authStore";
import { api } from "./apiClient";

let socket: Socket | null = null;

export function getSocket(): Socket {
  // Reuse the existing instance even while it's still connecting/reconnecting
  // (socket.connected is false during that window) — socket.io-client's own
  // reconnection logic re-authenticates with the latest token on each
  // attempt via the auth callback below, so tearing down and recreating
  // here on every call would only race multiple callers against each other.
  if (socket) return socket;

  if (!useAuthStore.getState().token) return null as unknown as Socket;

  socket = io(window.location.origin, {
    auth: (cb) => cb({ token: useAuthStore.getState().token }),
    transports: ["polling", "websocket"],
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionAttempts: Infinity,
  });

  // The server refuses an expired 15-minute pass. socket.io doesn't retry a
  // refused connection by itself, so renew the pass (sharing any renewal an
  // API call already started) and reconnect — live lead alerts keep working
  // after the app has been idle or the network dropped. A rejected renewal
  // ends the session instead, so this can't loop.
  socket.on("connect_error", async () => {
    if (!useAuthStore.getState().token) return;
    const renewed = await api.renewSession();
    if (renewed === "ok" && socket && !socket.active) {
      window.setTimeout(() => socket?.connect(), 500);
    }
  });

  return socket;
}

export function disconnectSocket() {
  if (socket) {
    socket.removeAllListeners();
    socket.disconnect();
    socket = null;
  }
}
