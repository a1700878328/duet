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

// A character card for a member (player). Returned by GET /rooms/{id}/cards.
export interface MemberCard {
  user_id: number;
  display_name: string;
  character_name: string;
  appearance: string | null;
  persona: string | null;
  voice_id: string | null;
  avatar_url?: string | null;
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

export type WsServerEvent =
  | WsHistory
  | WsMessage
  | WsAiDelta
  | WsAiDone
  | WsPresence
  | WsImagePending
  | WsCardsChanged
  | WsError;

export type WsClientEvent =
  | { type: "say"; content: string }
  | { type: "advance"; npc_id?: number }
  | { type: "timeskip" }
  | { type: "image"; nsfw: boolean }
  | { type: "typing"; is_typing: boolean };

export type ConnectionStatus = "connecting" | "open" | "closed";

// A message that is still streaming token-by-token (not yet finalized).
export interface StreamingTurn {
  turn_id: string;
  seq: number;
  content: string;
}
