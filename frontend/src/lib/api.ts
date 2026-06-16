import type {
  AuthResponse,
  CharDraft,
  AvatarVariant,
  MemberCard,
  SceneDesignOut,
  Message,
  NpcCard,
  Room,
  RoomCards,
  SceneLogResponse,
  User,
  UserCharacterCard,
  VoiceVariant,
} from "./types";

export interface MeCardBody {
  character_name?: string;
  persona?: string;
  appearance?: string | null;
  voice_id?: string | null;
  avatar_url?: string | null;
  voice_ref_url?: string | null;
  voice_ref_text?: string | null;
  voice_variants?: VoiceVariant[] | null;
  avatar_variants?: AvatarVariant[] | null;
  reset_stats?: boolean;
}

export interface UserCharacterCardBody {
  name: string;
  persona: string;
  appearance?: string | null;
  voice_id?: string | null;
  voice_ref_url?: string | null;
  voice_ref_text?: string | null;
  voice_variants?: VoiceVariant[] | null;
  avatar_url?: string | null;
  avatar_variants?: AvatarVariant[] | null;
  source_world_card?: string | null;
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
  return sessionStorage.getItem(TOKEN_KEY) ?? localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): User | null {
  const raw = sessionStorage.getItem(USER_KEY) ?? localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function storeAuth(auth: AuthResponse): void {
  sessionStorage.setItem(TOKEN_KEY, auth.token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(auth.user));
  localStorage.setItem(TOKEN_KEY, auth.token);
  localStorage.setItem(USER_KEY, JSON.stringify(auth.user));
}

export function clearAuth(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
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

  listMyCharacterCards: () =>
    request<UserCharacterCard[]>("/me/character-cards"),

  createMyCharacterCard: (body: UserCharacterCardBody) =>
    request<UserCharacterCard>("/me/character-cards", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateMyCharacterCard: (id: number, body: UserCharacterCardBody) =>
    request<UserCharacterCard>(`/me/character-cards/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  deleteMyCharacterCard: (id: number) =>
    request<void>(`/me/character-cards/${id}`, { method: "DELETE" }),

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

  deleteRoom: (id: string) =>
    request<void>(`/rooms/${id}`, { method: "DELETE" }),

  messages: (id: string, afterSeq = 0) =>
    request<Message[]>(`/rooms/${id}/messages?after_seq=${afterSeq}`),

  sceneLog: (id: string) =>
    request<SceneLogResponse>(`/rooms/${id}/scene-log`),

  // ---- character cards / NPCs ----

  getCards: (roomId: string) =>
    request<RoomCards>(`/rooms/${roomId}/cards`),

  presetCharacters: (roomId: string) =>
    request<NpcCard[]>(`/rooms/${roomId}/preset-characters`),

  getProtagonist: (roomId: string) =>
    request<CharDraft | null>(`/rooms/${roomId}/protagonist`),

  updateMeCard: (roomId: string, body: MeCardBody) =>
    request<MemberCard>(`/rooms/${roomId}/me-card`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  // Generate player-character drafts WITH portraits for in-room selection.
  // SLOW (~count*40s): one portrait per draft. Nothing is persisted.
  characterOptions: (
    roomId: string,
    body: { count?: number; hint?: string },
  ) =>
    request<CharDraft[]>(`/rooms/${roomId}/character-options`, {
      method: "POST",
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

  // Generate my portrait from my appearance (slow ~30-60s).
  generateMyAvatar: (roomId: string) =>
    request<MemberCard>(`/rooms/${roomId}/me-card/avatar`, {
      method: "POST",
    }),

  selectMyAvatar: (roomId: string, avatarUrl: string) =>
    request<MemberCard>(`/rooms/${roomId}/me-card/avatar/current`, {
      method: "PUT",
      body: JSON.stringify({ avatar_url: avatarUrl }),
    }),

  // AI character designer: description → structured draft.
  designCharacter: (roomId: string, hint: string) =>
    request<CharDraft>(`/rooms/${roomId}/design-character`, {
      method: "POST",
      body: JSON.stringify({ hint, count: 1 }),
    }),

  selectMyVoice: (roomId: string, voiceRefUrl: string) =>
    request<MemberCard>(`/rooms/${roomId}/me-card/voice/current`, {
      method: "PUT",
      body: JSON.stringify({ voice_ref_url: voiceRefUrl }),
    }),

  // Ask AI to create a role voice design and reference sample.
  generateMyVoice: (roomId: string) =>
    request<MemberCard>(`/rooms/${roomId}/me-card/voice`, {
      method: "POST",
    }),

  // Generate an NPC's portrait (slow ~30-60s).
  generateNpcAvatar: (roomId: string, npcId: number) =>
    request<NpcCard>(`/rooms/${roomId}/npcs/${npcId}/avatar`, {
      method: "POST",
    }),

  selectNpcAvatar: (roomId: string, npcId: number, avatarUrl: string) =>
    request<NpcCard>(`/rooms/${roomId}/npcs/${npcId}/avatar/current`, {
      method: "PUT",
      body: JSON.stringify({ avatar_url: avatarUrl }),
    }),

  selectNpcVoice: (roomId: string, npcId: number, voiceRefUrl: string) =>
    request<NpcCard>(`/rooms/${roomId}/npcs/${npcId}/voice/current`, {
      method: "PUT",
      body: JSON.stringify({ voice_ref_url: voiceRefUrl }),
    }),

  // Generate an NPC's role voice reference sample.
  generateNpcVoice: (roomId: string, npcId: number) =>
    request<NpcCard>(`/rooms/${roomId}/npcs/${npcId}/voice`, {
      method: "POST",
    }),

  // Evolve NPC: adjust appearance tags from current persona → new portrait.
  evolveNpc: (roomId: string, npcId: number) =>
    request<NpcCard>(`/rooms/${roomId}/npcs/${npcId}/evolve`, {
      method: "POST",
    }),

  // Evolve player character: same as evolveNpc but for the logged-in member.
  evolveMyCard: (roomId: string, personaAdd: string) =>
    request<MemberCard>(`/rooms/${roomId}/me-card/evolve`, {
      method: "POST",
      body: JSON.stringify({ persona_add: personaAdd }),
    }),

  // AI scene designer: description + context → scene type/atmosphere/npcs.
  designScene: (roomId: string, sceneName: string, description?: string) =>
    request<SceneDesignOut>(`/rooms/${roomId}/design-scene`, {
      method: "POST",
      body: JSON.stringify({ scene_name: sceneName, description: description ?? null }),
    }),

  // Enable/disable an NPC (= include/exclude from director simulation).
  setNpcActive: (roomId: string, npcId: number, active: boolean) =>
    request<NpcCard>(`/rooms/${roomId}/npcs/${npcId}/active`, {
      method: "PUT",
      body: JSON.stringify({ active }),
    }),

  // Synthesize a line to a wav (~5-10s); returns a /media/audio url.
  tts: (
    roomId: string,
    text: string,
    voiceId?: string | null,
    voiceRefUrl?: string | null,
    voiceRefText?: string | null,
    regenerate = false,
  ) =>
    request<{ url: string }>(`/rooms/${roomId}/tts`, {
      method: "POST",
      body: JSON.stringify({
        text,
        voice_id: voiceId ?? null,
        voice_ref_url: voiceRefUrl ?? null,
        voice_ref_text: voiceRefText ?? null,
        regenerate,
      }),
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

export function lobbySocketUrl(token: string): string {
  const base = API_BASE || window.location.origin;
  const wsBase = base.replace(/^http/, "ws");
  return `${wsBase}/ws/lobby?token=${encodeURIComponent(token)}`;
}
