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
  voice_ref_url?: string | null;
  voice_ref_text?: string | null;
  voice_variants?: VoiceVariant[];
  avatar_url?: string | null;
  avatar_variants?: AvatarVariant[];
  stats?: CharStats | null;
}

export interface AvatarVariant {
  url: string;
  label?: string | null;
  source?: string | null;
  created_at?: string | null;
  appearance?: string | null;
  appearance_tags?: string | null;
}

export interface VoiceVariant {
  url: string;
  voice_id?: string | null;
  text?: string | null;
  label?: string | null;
  source?: string | null;
  created_at?: string | null;
}

export interface TaskRewards {
  金钱?: number;
  经验?: number;
  物品?: string[];
  好感度?: Record<string, number>;
  [key: string]: number | string | string[] | Record<string, number> | undefined;
}

export interface TaskInfo {
  id: string;
  title?: string;
  issuer?: string;
  issuer_npc_id?: number | null;
  status?: string;
  description?: string;
  objectives?: string[];
  rewards?: TaskRewards;
  created_at?: string;
  accepted_at?: string;
  completed_at?: string;
}

// 结构化物品（对应后端 game_models.Item）
export interface InventoryItem {
  id: string;
  name: string;
  type: string; // 武器/防具/消耗品/任务道具/贵重品/素材
  quantity: number;
  description: string;
  equippable: boolean;
  usable: boolean;
  effects?: Record<string, number>;
  icon?: string;
}

// 结构化状态（对应后端 game_models.StatusEffect）
export interface StatusEffect {
  id: string;
  name: string;
  group: string; // 监禁/怀孕/诅咒/契约/标记/债务
  source: string;
  days: number;
  severity: number;
  effects?: Record<string, number>;
  escape_dc: number;
  description: string;
}

// A 《女骑士模拟器》-style stat sheet. Mostly numeric stats (经验/开发/淫乱向),
// plus structured sub-objects for 物品栏 and 状态.
export type StatValue =
  | number
  | string
  | string[]
  | TaskRewards
  | Record<string, number>
  | InventoryItem[]
  | StatusEffect[];

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
  // 结构化子对象（新版）
  物品栏?: InventoryItem[];
  状态?: StatusEffect[];
  // 旧版兼容（字符串列表）
  好感度?: Record<string, number>;
  物品?: string[];
  // 旧版状态字符串列表（新版用时=空数组）
  // 经验·开发 与未知字段
  [key: string]: StatValue | undefined;
}

// A character card for a member (player). Returned by GET /rooms/{id}/cards.
export interface MemberCard {
  user_id: number;
  display_name: string;
  character_name: string;
  appearance: string | null;
  appearance_tags?: string | null;
  persona: string | null;
  voice_id: string | null;
  voice_ref_url?: string | null;
  voice_ref_text?: string | null;
  voice_variants?: VoiceVariant[];
  avatar_url?: string | null;
  avatar_variants?: AvatarVariant[];
  stats?: CharStats | null;
}

// An NPC card living in a room (AI- or hand-authored).
export interface NpcCard {
  id: number;
  name: string;
  persona: string;
  appearance?: string | null;
  appearance_tags?: string | null;
  voice_id?: string | null;
  voice_ref_url?: string | null;
  voice_ref_text?: string | null;
  voice_variants?: VoiceVariant[];
  created_by_ai: boolean;
  active: boolean;
  avatar_url?: string | null;
  avatar_variants?: AvatarVariant[];
  scene?: string | null;
  discovered?: string | null;
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
  appearance_tags?: string | null;
  voice_id?: string | null;
  voice_ref_url?: string | null;
  voice_ref_text?: string | null;
  voice_variants?: VoiceVariant[];
  avatar_url?: string | null;
  avatar_variants?: AvatarVariant[];
}

export interface UserCharacterCard {
  id: number;
  name: string;
  persona: string;
  appearance?: string | null;
  appearance_tags?: string | null;
  voice_id?: string | null;
  voice_ref_url?: string | null;
  voice_ref_text?: string | null;
  voice_variants?: VoiceVariant[];
  avatar_url?: string | null;
  avatar_variants?: AvatarVariant[];
  source_world_card?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentTask {
  name: string;
  system_prompt: string;
  default_system_prompt: string;
  tutorial_name: string;
  default_tutorial_name: string;
  tutorial_chars: number;
  jailbreak: boolean;
  default_jailbreak: boolean;
  temperature: number;
  default_temperature: number;
  max_tokens: number;
  default_max_tokens: number;
  timeout: number;
  default_timeout: number;
  extra_body: Record<string, unknown>;
  default_extra_body: Record<string, unknown>;
  output_schema: string;
  overridden: boolean;
  overrides: string[];
}

export interface AgentTaskUpdate {
  system_prompt?: string;
  tutorial_name?: string;
  jailbreak?: boolean;
  temperature?: number;
  max_tokens?: number;
  timeout?: number;
  extra_body?: Record<string, unknown>;
}

export type AiMode = "manual" | "auto";

export type CurrentTask = TaskInfo;

export interface Room {
  id: string;
  name: string;
  owner_id: string;
  ai_mode: AiMode;
  world_card?: string | null;
  week?: number;
  day?: number;
  time_slot?: number;
  time_label?: string;
  current_scene?: string;
  scene_options?: string[];
  current_task?: CurrentTask | null;
  task_offers?: TaskInfo[];
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
  speaker_label?: string;
  delta: string;
}

export interface WsAiDone {
  type: "ai_done";
  turn_id: string;
  seq: number;
  speaker_label?: string;
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

export interface WsSayDraft {
  type: "say_draft";
  content: string;
}

export interface WsGodReply {
  type: "god_reply";
  content: string;
  private_to?: number;
}

export interface WsAiStatus {
  type: "ai_status";
  busy: boolean;
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

export interface WsTaskOffer {
  type: "task_offer";
  task: TaskInfo;
}

export interface WsTaskState {
  type: "task_state";
  current_task: TaskInfo | null;
  offers: TaskInfo[];
}

// 叙事时间推进到第 N 周（timeskip 或导演跳时；每满 4 周月末结算）。
export interface WsWeek {
  type: "week";
  week: number;
}

export interface WsTime {
  type: "time";
  week: number;
  day: number;
  time_slot: number;
  time_label: string;
}

// 切换到新场景（导演只调当前场景 NPC）。
export interface WsScene {
  type: "scene";
  scene: string;
}

export interface WsSceneLogsChanged {
  type: "scene_logs_changed";
}

export interface SceneLogEntry {
  scene: string;
  time_label: string;
  speaker_label: string;
  content: string;
  kind: string;
}

export interface SceneLogResponse {
  current_scene: string;
  scenes: string[];
  logs: Record<string, SceneLogEntry[]>;
}

export interface SceneDesignOut {
  scene_name: string;
  scene_type: string;
  atmosphere: string;
  potential_npcs: { name: string; persona: string; appearance: string }[];
  scene_intro: string;
  unlocked: boolean;
}

export type WsServerEvent =
  | WsHistory
  | WsMessage
  | WsAiDelta
  | WsAiDone
  | WsAiStatus
  | WsPresence
  | WsImagePending
  | WsCardsChanged
  | WsStats
  | WsWeek
  | WsTime
  | WsScene
  | WsSceneLogsChanged
  | WsSayDraft
  | WsGodReply
  | WsError;

export type WsClientEvent =
  | { type: "say"; content: string }
  | { type: "polish_say"; content: string }
  | { type: "advance"; npc_id?: number }
  | { type: "timeskip" }
  | { type: "goto_scene"; scene: string }
  | { type: "describe_scene" }
  | { type: "god_whisper"; content: string; target_npcs?: string[]; scene?: string; action?: string }
  | { type: "pay_npc"; npc_id: number; amount: number }
  | {
      type: "image";
      custom_prompt?: string;
      characters?: string[];
      designed_appearance?: string;
      nsfw?: boolean;
      quality?: "fast" | "refined";
    }
  | { type: "typing"; is_typing: boolean }
  | { type: "move"; scene: string; npcs: string[] };

export type ConnectionStatus = "connecting" | "open" | "closed";

// A message that is still streaming token-by-token (not yet finalized).
export interface StreamingTurn {
  turn_id: string;
  seq: number;
  speaker_label?: string;
  content: string;
}
