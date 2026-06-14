export interface User {
  id: string;
  username: string;
  display_name: string;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export interface RoomMember {
  user_id: string;
  display_name: string;
  character_name: string;
  appearance?: string | null;
  persona?: string | null;
  voice_id?: string | null;
  avatar_url?: string | null;
}

// A 《女骑士模拟器》-style stat sheet. Mostly numeric stats (经验/开发/淫乱向),
// plus a few string fields (职业/冒险者等级), a 状态 tag list, and a 好感度 map.
// Loose by design: the AI judge may emit new keys, so we keep an index signature.
export type StatValue = number | string | string[] | Record<string, number>;

export interface CharStats {
  // 基础
  职业?: string;
  冒险者等级?: string;
  等级?: number;
  经验?: number;
  力量?: number;
  敏捷?: number;
  智力?: number;
  意志?: number;
  金钱?: number;
  支出?: number;
  // 状态 / 关系
  状态?: string[];
  好感度?: Record<string, number>;
  // 经验·开发 与未知字段
  [key: string]: StatValue | undefined;
}

// A character card for a member (player). Returned by GET /rooms/{id}/cards.
export interface MemberCard {
  user_id: number;
  display_name: string;
  character_name: string;
  appearance: string | null;
  persona: string | null;
  voice_id: string | null;
  avatar_url?: string | null;
  stats?: CharStats | null;
}

// An NPC card living in a room (AI- or hand-authored).
export interface NpcCard {
  id: number;
  name: string;
  persona: string;
  appearance?: string | null;
  voice_id?: string | null;
  created_by_ai: boolean;
  active: boolean;
  avatar_url?: string | null;
  scene?: string | null;
}

export interface RoomCards {
  players: MemberCard[];
  npcs: NpcCard[];
}

// A non-persisted player-character draft for in-room selection (onboarding).
export interface CharDraft {
  name: string;
  persona: string;
  appearance?: string | null;
  voice_id?: string | null;
  avatar_url?: string | null;
}

export type AiMode = "manual" | "auto";

export interface Room {
  id: string;
  name: string;
  owner_id: string;
  ai_mode: AiMode;
  world_card?: string | null;
  week?: number;
  current_scene?: string;
  members: RoomMember[];
}

export type AuthorType = "user" | "ai" | "system" | "image";

export interface Message {
  id: string;
  room_id: string;
  seq: number;
  author_type: AuthorType;
  author_user_id: string | null;
  speaker_label: string;
  content: string;
  created_at: string;
}

// ---- WebSocket wire types ----

export interface WsHistory {
  type: "history";
  messages: Message[];
}

export interface WsMessage {
  type: "message";
  message: Message;
}

export interface WsAiDelta {
  type: "ai_delta";
  turn_id: string;
  seq: number;
  delta: string;
}

export interface WsAiDone {
  type: "ai_done";
  turn_id: string;
  seq: number;
  content: string;
  finish_reason: string;
}

export interface WsPresence {
  type: "presence";
  user_id: string;
  display_name: string;
  online: boolean;
}

export interface WsError {
  type: "error";
  code: string;
  detail: string;
}

export interface WsImagePending {
  type: "image_pending";
  user_id: string;
  display_name: string;
}

export interface WsCardsChanged {
  type: "cards_changed";
}

// Broadcast after a beat for the player who acted: the full refreshed sheet
// plus the just-applied delta (e.g. {"口腔经验":5,"淫乱":1,"状态_add":["监禁:哥布林"]}).
export interface WsStats {
  type: "stats";
  user_id: number;
  stats: CharStats;
  delta: Record<string, StatValue>;
}

// 叙事时间推进到第 N 周（timeskip 或导演跳时；每满 4 周月末结算）。
export interface WsWeek {
  type: "week";
  week: number;
}

// 切换到新场景（导演只调当前场景 NPC）。
export interface WsScene {
  type: "scene";
  scene: string;
}

export type WsServerEvent =
  | WsHistory
  | WsMessage
  | WsAiDelta
  | WsAiDone
  | WsPresence
  | WsImagePending
  | WsCardsChanged
  | WsStats
  | WsWeek
  | WsScene
  | WsError;

export type WsClientEvent =
  | { type: "say"; content: string }
  | { type: "advance"; npc_id?: number }
  | { type: "timeskip" }
  | { type: "goto_scene"; scene: string }
  | { type: "image"; nsfw: boolean }
  | { type: "typing"; is_typing: boolean };

export type ConnectionStatus = "connecting" | "open" | "closed";

// A message that is still streaming token-by-token (not yet finalized).
export interface StreamingTurn {
  turn_id: string;
  seq: number;
  content: string;
}
