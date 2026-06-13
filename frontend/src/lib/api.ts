import type {
  AuthResponse,
  MemberCard,
  Message,
  NpcCard,
  Room,
  RoomCards,
  User,
} from "./types";

export interface MeCardBody {
  character_name?: string;
  persona?: string;
  appearance?: string | null;
  voice_id?: string | null;
}

export interface NpcBody {
  name: string;
  persona: string;
  appearance?: string | null;
  voice_id?: string | null;
}

export interface GenerateNpcsBody {
  count?: number;
  hint?: string;
}

// Empty base => same-origin (dev proxy / FastAPI static hosting / native shell same host).
const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

const TOKEN_KEY = "duet.token";
const USER_KEY = "duet.user";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): User | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function storeAuth(auth: AuthResponse): void {
  localStorage.setItem(TOKEN_KEY, auth.token);
  localStorage.setItem(USER_KEY, JSON.stringify(auth.user));
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Listeners notified when a 401 is seen, so the app can bounce to /auth.
type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;
export function setUnauthorizedHandler(fn: UnauthorizedHandler | null): void {
  onUnauthorized = fn;
}

async function request<T>(
  path: string,
  options: RequestInit & { auth?: boolean } = {},
): Promise<T> {
  const { auth = true, headers, ...rest } = options;
  const finalHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string>),
  };
  if (auth) {
    const token = getToken();
    if (token) finalHeaders.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}/api${path}`, {
    ...rest,
    headers: finalHeaders,
  });

  if (res.status === 401) {
    clearAuth();
    onUnauthorized?.();
    throw new ApiError(401, "未授权，请重新登录");
  }

  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail ?? body.message ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  register: (body: { username: string; password: string; display_name: string }) =>
    request<AuthResponse>("/auth/register", {
      method: "POST",
      auth: false,
      body: JSON.stringify(body),
    }),

  login: (body: { username: string; password: string }) =>
    request<AuthResponse>("/auth/login", {
      method: "POST",
      auth: false,
      body: JSON.stringify(body),
    }),

  me: () => request<{ user: User }>("/me"),

  listRooms: () => request<Room[]>("/rooms"),

  createRoom: (body: {
    name: string;
    character_name: string;
    world_card?: string | null;
    appearance?: string | null;
  }) => request<Room>("/rooms", { method: "POST", body: JSON.stringify(body) }),

  joinRoom: (
    id: string,
    body: { character_name: string; appearance?: string | null },
  ) =>
    request<Room>(`/rooms/${id}/join`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  messages: (id: string, afterSeq = 0) =>
    request<Message[]>(`/rooms/${id}/messages?after_seq=${afterSeq}`),

  // ---- character cards / NPCs ----

  getCards: (roomId: string) =>
    request<RoomCards>(`/rooms/${roomId}/cards`),

  updateMeCard: (roomId: string, body: MeCardBody) =>
    request<MemberCard>(`/rooms/${roomId}/me-card`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  createNpc: (roomId: string, body: NpcBody) =>
    request<NpcCard>(`/rooms/${roomId}/npcs`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  generateNpcs: (roomId: string, body: GenerateNpcsBody) =>
    request<NpcCard[]>(`/rooms/${roomId}/npcs/generate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateNpc: (roomId: string, npcId: number, body: NpcBody) =>
    request<NpcCard>(`/rooms/${roomId}/npcs/${npcId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  deleteNpc: (roomId: string, npcId: number) =>
    request<{ status: string }>(`/rooms/${roomId}/npcs/${npcId}`, {
      method: "DELETE",
    }),
};

// Resolve a server-relative asset path (e.g. /media/...) against the API origin.
export function assetUrl(path: string): string {
  return `${API_BASE}${path}`;
}

// WebSocket URL builder. Resolves relative to API_BASE (or current origin in dev).
export function roomSocketUrl(roomId: string, token: string): string {
  const base = API_BASE || window.location.origin;
  const wsBase = base.replace(/^http/, "ws");
  return `${wsBase}/ws/rooms/${roomId}?token=${encodeURIComponent(token)}`;
}
