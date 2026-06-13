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

export type AuthorType = "user" | "ai" | "system";

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

export type WsServerEvent =
  | WsHistory
  | WsMessage
  | WsAiDelta
  | WsAiDone
  | WsPresence
  | WsError;

export type WsClientEvent =
  | { type: "say"; content: string }
  | { type: "advance" }
  | { type: "typing"; is_typing: boolean };

export type ConnectionStatus = "connecting" | "open" | "closed";

// A message that is still streaming token-by-token (not yet finalized).
export interface StreamingTurn {
  turn_id: string;
  seq: number;
  content: string;
}
