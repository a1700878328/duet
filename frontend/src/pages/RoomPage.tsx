import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CardPanel } from "../components/CardPanel";
import { CharacterSelect } from "../components/CharacterSelect";
import { Composer } from "../components/Composer";
import { MessageBubble } from "../components/MessageBubble";
import {
  ImageLightbox,
  ProfileModal,
  type ProfileView,
} from "../components/RoomOverlays";
import { StatsPanel } from "../components/StatsPanel";
import { api, ApiError, assetUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { MEDIA_GENERATION_ENABLED, VOICE_GENERATION_ENABLED } from "../lib/features";
import { useRoomSocket, type StatsEvent } from "../lib/useRoomSocket";
import type {
  CharStats,
  Message,
  RoomCards,
  Room,
  SceneLogResponse,
  StatValue,
} from "../lib/types";

const NEAR_BOTTOM_PX = 80;

// Strip a leading "[name]:" or "name：" speaker prefix before TTS synthesis.
function stripSpeakerPrefix(text: string): string {
  return text.replace(/^\s*[[【]?[^\]\n：:]{1,24}[\]】]?\s*[：:]\s*/, "").trim();
}

// Render a stat delta into a short flash string, e.g. "口腔经验+5 淫乱+1 金钱-100 ⛓监禁:哥布林".
function formatDelta(delta: Record<string, StatValue>): string {
  const parts: string[] = [];
  for (const [key, val] of Object.entries(delta)) {
    if (key === "状态_add" && Array.isArray(val)) {
      for (const s of val) parts.push(`⛓${s}`);
    } else if (key === "状态_del" && Array.isArray(val)) {
      for (const s of val) parts.push(`✓解除${s}`);
    } else if (key === "物品_add" && Array.isArray(val)) {
      for (const s of val) parts.push(`🎁${s}`);
    } else if (key === "好感度" && val && typeof val === "object") {
      for (const [npc, dv] of Object.entries(val as Record<string, number>)) {
        if (dv) parts.push(`♥${npc}${dv > 0 ? "+" : ""}${dv}`);
      }
    } else if (typeof val === "number") {
      if (val === 0) continue;
      parts.push(`${key}${val > 0 ? "+" : ""}${val}`);
    } else if (typeof val === "string") {
      parts.push(`${key}:${val}`);
    }
  }
  return parts.join(" ");
}

export function RoomPage() {
  const { roomId = "" } = useParams();
  const { user, token } = useAuth();
  const navigate = useNavigate();

  const [room, setRoom] = useState<Room | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [sayDraft, setSayDraft] = useState<string | null>(null);
  const [polishingSay, setPolishingSay] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [statsOpen, setStatsOpen] = useState(false);
  // 叙事时间：世界进度 / 日内节点。
  const [timeLabel, setTimeLabel] = useState("冒险第1周·第1天·清晨");
  // 当前场景标签（""=自由世界无分区）。
  const [scene, setScene] = useState("");
  const [sceneLogOpen, setSceneLogOpen] = useState(false);
  const [sceneLog, setSceneLog] = useState<SceneLogResponse | null>(null);
  const [sceneLogLoading, setSceneLogLoading] = useState(false);
  const [selectedScene, setSelectedScene] = useState("");
  const sceneLogEntriesRef = useRef<HTMLDivElement>(null);
  // 页内悬浮窗：点头像看资料 / 点图看大图。
  const [overlay, setOverlay] = useState<
    { kind: "image"; url: string } | { kind: "profile"; profile: ProfileView } | null
  >(null);
  // Forced onboarding: dismissed once chosen or skipped (one-time per visit).
  const [charSelectDismissed, setCharSelectDismissed] = useState(false);
  const [charSelectForced, setCharSelectForced] = useState(false);

  // My live stat sheet — seeded from my card, updated by "stats" WS events.
  const [myStats, setMyStats] = useState<CharStats | null>(null);
  // Brief floating "增量" flash after a beat (cleared on a timer).
  const [deltaFlash, setDeltaFlash] = useState<string | null>(null);
  const deltaTimer = useRef<number | null>(null);

  // Lifted cards state — shared by bubbles (avatar resolver) and the panel.
  const [cards, setCards] = useState<RoomCards | null>(null);
  const refreshRoom = useCallback(async () => {
    const rooms = await api.listRooms();
    const found = rooms.find((r) => String(r.id) === String(roomId)) ?? null;
    setRoom(found);
    if (found?.time_label) setTimeLabel(found.time_label);
    if (found?.current_scene) setScene(found.current_scene);
    if (!found) setLoadError("未找到房间，或你不在其中。");
  }, [roomId]);
  const refreshCards = useCallback(async () => {
    try {
      setCards(await api.getCards(roomId));
    } catch {
      /* best-effort; panel surfaces its own errors */
    }
  }, [roomId]);
  const handleCardsChanged = useCallback(() => {
    void refreshCards();
    void refreshRoom();
  }, [refreshCards, refreshRoom]);

  const [voicing, setVoicing] = useState(false);
  const [imageModalOpen, setImageModalOpen] = useState(false);
  const [imageText, setImageText] = useState("");
  const [imageChars, setImageChars] = useState<Set<string>>(new Set());
  const [moveModalOpen, setMoveModalOpen] = useState(false);
  const [moveScene, setMoveScene] = useState("");
  const [selectedMoveNpcs, setSelectedMoveNpcs] = useState<Set<string>>(new Set());

  const toastTimer = useRef<number | null>(null);
  const showToast = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  }, []);
  const refreshSceneLog = useCallback(async () => {
    setSceneLogLoading(true);
    try {
      const data = await api.sceneLog(roomId);
      setSceneLog(data);
      if (data.current_scene) setScene(data.current_scene);
      setSelectedScene((prev) =>
        prev && data.scenes.includes(prev) ? prev : data.current_scene,
      );
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "加载场景记录失败");
    } finally {
      setSceneLogLoading(false);
    }
  }, [roomId, showToast]);
  const openSceneLog = useCallback(() => {
    setSceneLogOpen(true);
    void refreshSceneLog();
  }, [refreshSceneLog]);

  const handleWsError = useCallback(
    (code: string, detail: string) => {
      setPolishingSay(false);
      if (code === "ai_busy") showToast("剧情正在推进，请稍候…");
      else showToast(detail || `错误：${code}`);
    },
    [showToast],
  );

  // A "stats" event for ME: refresh my sheet + flash the just-applied delta.
  const handleStats = useCallback(
    (ev: StatsEvent) => {
      if (String(ev.user_id) !== String(user?.id)) return;
      setMyStats(ev.stats);
      const text = formatDelta(ev.delta);
      if (!text) return;
      setDeltaFlash(text);
      if (deltaTimer.current) window.clearTimeout(deltaTimer.current);
      deltaTimer.current = window.setTimeout(() => setDeltaFlash(null), 3200);
    },
    [user?.id],
  );

  const handleTime = useCallback(
    (ev: { week: number; day: number; time_slot: number; time_label: string }) => {
      setTimeLabel(ev.time_label);
    },
    [],
  );
  const handleScene = useCallback((s: string) => {
    setScene(s);
    setSelectedScene((prev) => prev || s);
  }, []);

  const {
    status,
    messages,
    streaming,
    presence,
    aiBusy,
    imaging,
    say,
    polishSay,
    advance,
    payNpc,
    describeScene,
    requestImage,
    moveNpcs,
    godWhisper,
    setTyping,
  } = useRoomSocket({
    roomId,
    token: token ?? "",
    onError: handleWsError,
    onCardsChanged: handleCardsChanged,
    onStats: handleStats,
    onTime: handleTime,
    onScene: handleScene,
    onSceneLogsChanged: () => {
      if (sceneLogOpen) void refreshSceneLog();
    },
    onSayDraft: (content) => {
      setPolishingSay(false);
      setSayDraft(content);
      showToast("AI 已把改写填进输入框");
    },
    onGodReply: (content) => {
      showToast(content || "上帝已回应");
    },
  });

  // Load room metadata for header.
  useEffect(() => {
    let active = true;
    refreshRoom()
      .then(() => {
        if (!active) return;
      })
      .catch((err) => {
        if (active)
          setLoadError(err instanceof ApiError ? err.message : "加载房间失败");
      });
    return () => {
      active = false;
    };
  }, [refreshRoom]);

  // Load cards once on mount (panel refreshes again on open / after mutations).
  useEffect(() => {
    void refreshCards();
  }, [refreshCards]);

  // ---- avatar resolver ----------------------------------------------------
  // player msg (author_type 'user'): match author_user_id -> MemberCard.avatar_url
  // ai/npc msg  (author_type 'ai'):  match speaker_label === npc.name -> NpcCard.avatar_url
  const playerAvatars = useMemo(() => {
    const m = new Map<string, string | null | undefined>();
    for (const p of cards?.players ?? []) m.set(String(p.user_id), p.avatar_url);
    return m;
  }, [cards]);

  const npcByName = useMemo(() => {
    const m = new Map<
      string,
      {
        voice_id?: string | null;
        voice_ref_url?: string | null;
        voice_ref_text?: string | null;
        avatar_url?: string | null;
      }
    >();
    for (const n of cards?.npcs ?? [])
      m.set(n.name, {
        voice_id: n.voice_id,
        voice_ref_url: n.voice_ref_url,
        voice_ref_text: n.voice_ref_text,
        avatar_url: n.avatar_url,
      });
    return m;
  }, [cards]);

  // Player voice lookup (author_type "user") by character_name → voice settings.
  const playerByName = useMemo(() => {
    const m = new Map<
      string,
      {
        voice_id?: string | null;
        voice_ref_url?: string | null;
        voice_ref_text?: string | null;
      }
    >();
    for (const p of cards?.players ?? []) {
      const key = p.character_name || p.display_name;
      m.set(key, {
        voice_id: p.voice_id,
        voice_ref_url: p.voice_ref_url,
        voice_ref_text: p.voice_ref_text,
      });
    }
    return m;
  }, [cards]);

  // Resolve MY member card from the lifted cards (match user_id).
  const myCard = useMemo(
    () =>
      cards?.players.find((p) => String(p.user_id) === String(user?.id)) ??
      null,
    [cards, user?.id],
  );
  const sceneLogScenes = sceneLog?.scenes.length
    ? sceneLog.scenes
    : scene
      ? [scene]
      : ["自由场景"];
  const activeScene =
    selectedScene || sceneLog?.current_scene || scene || "自由场景";
  const activeSceneEntries = sceneLog?.logs[activeScene] ?? [];
  useLayoutEffect(() => {
    if (!sceneLogOpen) return;
    const el = sceneLogEntriesRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [sceneLogOpen, activeScene, activeSceneEntries.length, sceneLogLoading]);
  // Keep my stat sheet aligned with the persisted card. This matters when
  // re-selecting a character resets the sheet before the next WS stat event.
  useEffect(() => {
    if (myCard) setMyStats(myCard.stats ?? null);
  }, [myCard]);

  useEffect(
    () => () => {
      if (deltaTimer.current) window.clearTimeout(deltaTimer.current);
    },
    [],
  );

  // Force in-room character selection when cards have loaded and my card has
  // no persona set yet. Dismissible; never blocks the room if skipped.
  const needsCharSelect =
    charSelectForced ||
    (!charSelectDismissed && myCard !== null && !myCard.persona);

  const dismissCharSelect = useCallback(async () => {
    setCharSelectDismissed(true);
    setCharSelectForced(false);
    await refreshCards();
  }, [refreshCards]);

  const resolveAvatar = useCallback(
    (msg: Pick<Message, "author_type" | "author_user_id" | "speaker_label">) => {
      if (msg.author_type === "user")
        return playerAvatars.get(String(msg.author_user_id)) ?? null;
      if (msg.author_type === "ai")
        return npcByName.get(msg.speaker_label)?.avatar_url ?? null;
      return null;
    },
    [playerAvatars, npcByName],
  );

  // Resolve a message's speaker → profile popover (player stats / NPC info).
  const openProfile = useCallback(
    (msg: Message) => {
      if (msg.author_type === "user") {
        const p = cards?.players.find(
          (x) => String(x.user_id) === String(msg.author_user_id),
        );
        if (!p) return;
        const isSelf = String(p.user_id) === String(user?.id);
        setOverlay({
          kind: "profile",
          profile: {
            kind: "player",
            name: p.character_name,
            avatarUrl: p.avatar_url,
            appearance: p.appearance,
            persona: p.persona,
            stats: isSelf ? (myStats ?? p.stats ?? null) : (p.stats ?? null),
          },
        });
      } else if (msg.author_type === "ai") {
        const n = cards?.npcs.find((x) => x.name === msg.speaker_label);
        if (!n) return; // 旁白/未知讲述者不弹资料
        setOverlay({
          kind: "profile",
          profile: {
            kind: "npc",
            id: n.id,
            name: n.name,
            avatarUrl: n.avatar_url,
            appearance: n.appearance,
            persona: n.persona,
            scene: n.scene,
            discovered: n.discovered,
          },
        });
      }
    },
    [cards, user?.id, myStats],
  );

  // Auto-scroll handling: stick to bottom unless the user scrolled up.
  const timelineRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  const onScroll = useCallback(() => {
    const el = timelineRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickRef.current = distance < NEAR_BOTTOM_PX;
  }, []);

  useLayoutEffect(() => {
    const el = timelineRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, streaming]);

  // ---- voice playback -----------------------------------------------------
  // Serialize TTS via one <audio>; cache by seq so a line is synthesized once.
  // The seq→url map is persisted to localStorage so replays survive reloads
  // (the backend also dedupes by content hash, so even a cache miss won't
  // re-synthesize — it just re-points to the same durable /media file).
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const ttsCacheKey = `duet:tts:${roomId}`;
  const ttsCacheRef = useRef<Map<string, string>>(new Map());
  // Hydrate the cache once from localStorage on mount.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(ttsCacheKey);
      if (raw) ttsCacheRef.current = new Map(JSON.parse(raw));
    } catch {
      /* ignore corrupt cache */
    }
  }, [ttsCacheKey]);
  const persistTtsCache = useCallback(() => {
    try {
      window.localStorage.setItem(
        ttsCacheKey,
        JSON.stringify([...ttsCacheRef.current]),
      );
    } catch {
      /* quota / disabled storage — non-fatal */
    }
  }, [ttsCacheKey]);
  const playQueueRef = useRef<string[]>([]);
  const playingRef = useRef(false);

  const drainQueue = useCallback(() => {
    if (playingRef.current) return;
    const next = playQueueRef.current.shift();
    if (!next) return;
    let audio = audioRef.current;
    if (!audio) {
      audio = new Audio();
      audio.onended = () => {
        playingRef.current = false;
        drainQueue();
      };
      audio.onerror = () => {
        playingRef.current = false;
        drainQueue();
      };
      audioRef.current = audio;
    }
    playingRef.current = true;
    audio.src = assetUrl(next);
    audio.currentTime = 0;
    void audio.play().catch(() => {
      playingRef.current = false;
      drainQueue();
    });
  }, []);

  const enqueueVoice = useCallback(
    async (
      msg: Message,
      regenerate = false,
      voiceOverride?: {
        voice_id?: string | null;
        voice_ref_url?: string | null;
        voice_ref_text?: string | null;
      } | null,
    ) => {
      const speaker = voiceOverride ?? npcByName.get(msg.speaker_label);
      // Composite cache key: seq + voice config — so changing voice = cache miss.
      const cfgKey = `${speaker?.voice_id ?? ""}|${speaker?.voice_ref_url ?? ""}`;
      const cacheKey = `${msg.seq}:${cfgKey}`;
      const cached = ttsCacheRef.current.get(cacheKey);
      if (cached && !regenerate) {
        playQueueRef.current.push(cached);
        drainQueue();
        return;
      }
      const text = stripSpeakerPrefix(msg.content);
      if (!text) return;
      setVoicing(true);
      try {
        const { url } = await api.tts(
          roomId,
          text,
          speaker?.voice_id ?? null,
          speaker?.voice_ref_url ?? null,
          speaker?.voice_ref_text ?? null,
          regenerate,
        );
        ttsCacheRef.current.set(cacheKey, url);
        persistTtsCache();
        playQueueRef.current.push(url);
        drainQueue();
      } catch {
        showToast("配音失败");
      } finally {
        setVoicing(false);
      }
    },
    [roomId, npcByName, drainQueue, showToast, persistTtsCache],
  );

  useEffect(() => {
    return () => {
      audioRef.current?.pause();
    };
  }, []);

  function memberOnline(userId: string): boolean {
    return presence.get(userId) ?? false;
  }

  const sendPlayerText = useCallback(
    (text: string) => {
      setSayDraft(null);
      say(text);
    },
    [say],
  );
  const polishPlayerText = useCallback(
    (text: string) => {
      setPolishingSay(true);
      polishSay(text);
    },
    [polishSay],
  );
  if (loadError) {
    return (
      <div className="center-screen">
        <div style={{ textAlign: "center" }}>
          <p>{loadError}</p>
          <button className="btn" onClick={() => navigate("/rooms")}>
            返回房间列表
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="room">
      <header className="room-header">
        <div className="room-header-top">
          <button
            className="btn btn-ghost"
            onClick={() => navigate("/rooms")}
            aria-label="返回"
          >
            ←
          </button>
          <h2>{room?.name ?? "房间"}</h2>
          <span
            className="week-chip"
            title="当前世界时间"
          >
            🗓 {timeLabel}
          </span>
          <button
            className="week-chip scene-chip"
            onClick={openSceneLog}
            title="打开当前场景与其他已知场景的记录"
          >
            📍 当前：{scene || "自由场景"}
          </button>
          <button
            className="week-chip scene-chip"
            onClick={() => describeScene()}
            disabled={aiBusy || status !== "open"}
            title="让旁白盘点当前场景里玩家与 NPC 的状态"
          >
            🧭 场景状态
          </button>
          <span className={`status`}>
            <span className={`dot ${status}`} />
            {status === "open"
              ? "已连接"
              : status === "connecting"
                ? "连接中"
                : "已断开"}
          </span>
          <button
            className="btn btn-ghost cards-toggle"
            onClick={() => {
              setCharSelectForced(true);
              setPanelOpen(false);
              setStatsOpen(false);
            }}
            title="重新打开房间选人，选择账号卡、主角、世界角色或 AI 原创角色"
          >
            选角
          </button>
          <button
            className={`btn btn-ghost cards-toggle ${panelOpen ? "active" : ""}`}
            onClick={() => {
              setPanelOpen((v) => {
                const next = !v;
                if (next) setStatsOpen(false);
                return next;
              });
            }}
            aria-pressed={panelOpen}
            title="角色卡与登场 NPC"
          >
            🎭 角色
          </button>
          <button
            className={`btn btn-ghost cards-toggle ${statsOpen ? "active" : ""}`}
            onClick={() => {
              setStatsOpen((v) => {
                const next = !v;
                if (next) setPanelOpen(false);
                return next;
              });
            }}
            aria-pressed={statsOpen}
            title="我的角色状态（女骑士模拟器式数值表）"
          >
            📊 状态
          </button>
        </div>

        <div className="room-header-top">
          <div className="member-chips">
            {room?.members.map((m) => (
              <span key={m.user_id} className="chip">
                <span
                  className={`dot ${memberOnline(m.user_id) ? "online" : ""}`}
                />
                <span className="chip-char">{m.character_name}</span>
                <span>· {m.display_name}</span>
              </span>
            ))}
            <span className="chip ai">NPC · AI</span>
          </div>
        </div>
      </header>

      <div className="timeline" ref={timelineRef} onScroll={onScroll}>
        {messages.length === 0 && !streaming && (
          <div className="empty">还没有对话。说点什么，或让 AI 起个头。</div>
        )}

        {messages.map((m) => (
          <MessageBubble
            key={`${m.seq}-${m.id}`}
            message={m}
            isMe={m.author_type === "user" && m.author_user_id === user?.id}
            avatarUrl={resolveAvatar(m)}
            onPlayVoice={
              VOICE_GENERATION_ENABLED
                ? m.author_type === "ai" && npcByName.has(m.speaker_label)
                  ? () => void enqueueVoice(m)
                  : m.author_type === "user"
                    ? (() => {
                        const pv = playerByName.get(m.speaker_label);
                        return pv ? () => void enqueueVoice(m, false, pv) : undefined;
                      })()
                    : undefined
                : undefined
            }
            onAvatarClick={() => openProfile(m)}
            onImageClick={
              m.author_type === "image"
                ? () => setOverlay({ kind: "image", url: m.content })
                : undefined
            }
          />
        ))}

        {streaming && (
          <MessageBubble
            message={{
              author_type: "ai",
              author_user_id: null,
              speaker_label: streaming.speaker_label ?? "NPC",
              content: streaming.content,
            }}
            isMe={false}
            streaming
          />
        )}

        {VOICE_GENERATION_ENABLED && voicing && (
          <div className="streaming-hint voice-hint">
            <span className="pulse" />
            🔊 配音中…
          </div>
        )}

        {aiBusy && (
          <div className="streaming-hint">
            <span className="pulse" />
            剧情推进中…
          </div>
        )}

        {MEDIA_GENERATION_ENABLED && imaging && (
          <div className="streaming-hint">
            <span className="pulse" />
            生成场景图中…（约 30–60 秒）
          </div>
        )}
      </div>

      <div className="composer">
        <Composer
          onSend={sendPlayerText}
          onPolish={polishPlayerText}
          onTyping={setTyping}
          disabled={status !== "open"}
          polishing={polishingSay}
          draftText={sayDraft}
        />
        <div className="composer-actions">
          {MEDIA_GENERATION_ENABLED && (
            <button
              className="btn"
              onClick={() => setImageModalOpen(true)}
              disabled={imaging}
              title="生成场景图像"
            >
              {imaging ? <><span className="spinner" />生成中</> : "生成场景图"}
            </button>
          )}
          <button
            className="btn"
            onClick={() => setMoveModalOpen(true)}
            title="前往其他场景"
          >
            🚶 移动
          </button>
        </div>
      </div>

      <CardPanel
        roomId={roomId}
        myUserId={user?.id}
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        aiBusy={aiBusy}
        onError={showToast}
        cards={cards}
        onRefresh={refreshCards}
        onOpenProfile={(profile) => setOverlay({ kind: "profile", profile })}
        onOpenCharacterSelect={() => setCharSelectForced(true)}
        onNpcSpeak={(npcId) => {
          advance(npcId);
          setPanelOpen(false);
        }}
        onGodWhisper={(params) => {
          godWhisper(params);
          setPanelOpen(false);
        }}
        currentScene={room?.current_scene}
        sceneOptions={room?.scene_options}
      />

      <StatsPanel
        open={statsOpen}
        onClose={() => setStatsOpen(false)}
        stats={myStats}
        characterName={myCard?.character_name}
      />

      {sceneLogOpen && (
        <div
          className="overlay-backdrop scene-log-overlay"
          onClick={() => setSceneLogOpen(false)}
        >
          <div className="scene-log-card" onClick={(e) => e.stopPropagation()}>
            <div className="scene-log-head">
              <div>
                <h3>场景记录</h3>
                <p>{timeLabel}</p>
              </div>
              <div className="scene-log-actions">
                <button
                  className="btn btn-sm"
                  onClick={() => void refreshSceneLog()}
                  disabled={sceneLogLoading}
                >
                  刷新
                </button>
                <button
                  className="pf-close"
                  onClick={() => setSceneLogOpen(false)}
                  aria-label="关闭"
                >
                  ✕
                </button>
              </div>
            </div>
            <div className="scene-log-npc-avatars">
              {(cards?.npcs ?? [])
                .filter((n) => n.name !== "上帝" && n.name !== "旁白")
                .map((n) => (
                  <button
                    key={n.id}
                    className={`scene-npc-avatar ${n.scene === activeScene ? "active" : ""}`}
                    title={`${n.name} · ${n.scene || "随队/当前场景"}`}
                    onClick={() => {
                      if (n.scene) setSelectedScene(n.scene);
                    }}
                  >
                    {n.name.slice(0, 2)}
                  </button>
                ))}
            </div>
            <div className="scene-log-body">
              <div className="scene-log-list">
                {sceneLogScenes.map((s) => (
                  <div
                    key={s}
                    className={`scene-log-tab ${s === activeScene ? "active" : ""}`}
                  >
                    <button
                      type="button"
                      className="scene-log-tab-main"
                      onClick={() => setSelectedScene(s)}
                    >
                      <span>{s}</span>
                      {s === sceneLog?.current_scene && <em>当前</em>}
                    </button>
                  </div>
                ))}
              </div>
              <div className="scene-log-entries" ref={sceneLogEntriesRef}>
                <div className="scene-log-title">
                  <strong>{activeScene}</strong>
                  {sceneLogLoading && <span>加载中…</span>}
                </div>
                <div className="scene-log-npcs">
                  👥 {(cards?.npcs ?? [])
                    .filter((n) => n.name !== "上帝")
                    .filter((n) => !n.scene || n.scene === activeScene)
                    .map((n) => n.name)
                    .join("、") || "无"}
                </div>
                {activeSceneEntries.length > 0 ? (
                  activeSceneEntries.map((entry, idx) => (
                    <div
                      key={`${entry.time_label}-${idx}`}
                      className={`scene-log-entry kind-${entry.kind}`}
                    >
                      <div className="scene-log-meta">
                        <span>{entry.time_label}</span>
                        <b>{entry.speaker_label}</b>
                      </div>
                      <div className="scene-log-text">{entry.content}</div>
                    </div>
                  ))
                ) : (
                  <div className="scene-log-empty">
                    这个场景还没有记录。NPC 会随着玩家发言在各自场景持续行动。
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {needsCharSelect && (
        <CharacterSelect roomId={roomId} onDone={dismissCharSelect} />
      )}

      {overlay?.kind === "profile" && (
        <ProfileModal
          profile={overlay.profile}
          onClose={() => setOverlay(null)}
          onPayNpc={(npcId, amount) => payNpc(npcId, amount)}
          currentMoney={
            typeof myStats?.金钱 === "number" ? myStats.金钱 : null
          }
          paymentBusy={aiBusy}
        />
      )}
      {overlay?.kind === "image" && (
        <ImageLightbox url={overlay.url} onClose={() => setOverlay(null)} />
      )}

      {deltaFlash && (
        <div className="delta-flash" role="status">
          {deltaFlash}
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}

      {imageModalOpen && (
        <div className="overlay-backdrop" onClick={() => setImageModalOpen(false)}>
          <div className="move-modal" onClick={(e) => e.stopPropagation()}>
            <h3>📷 生成场景图</h3>
            <label>动作描述</label>
            <input
              type="text"
              className="input"
              placeholder="如：银发紫瞳的盲眼圣女，跪坐在教堂长椅上"
              value={imageText}
              onChange={(e) => setImageText(e.target.value)}
              autoFocus
            />
            <label style={{ marginTop: 12 }}>出场角色（勾选要出场的角色）</label>
            <div className="npc-checklist">
              {cards?.players?.map((p) => (
                <label key={p.user_id} className="npc-check-item">
                  <input
                    type="checkbox"
                    checked={imageChars.has(p.character_name)}
                    onChange={() => {
                      const next = new Set(imageChars);
                      if (next.has(p.character_name)) next.delete(p.character_name);
                      else next.add(p.character_name);
                      setImageChars(next);
                    }}
                  />
                  {p.character_name}（我）
                </label>
              ))}
              {(cards?.npcs ?? [])
                .filter((n) => n.name !== "上帝")
                .filter((n) => !n.scene || n.scene === room?.current_scene)
                .map((n) => (
                  <label key={n.id} className="npc-check-item">
                    <input
                      type="checkbox"
                      checked={imageChars.has(n.name)}
                      onChange={() => {
                        const next = new Set(imageChars);
                        if (next.has(n.name)) next.delete(n.name);
                        else next.add(n.name);
                        setImageChars(next);
                      }}
                    />
                    {n.name}
                  </label>
                ))}
            </div>
            <div className="move-actions">
              <button
                className="btn"
                disabled={imaging || (!imageText.trim() && imageChars.size === 0)}
                onClick={() => {
                  requestImage(imageText.trim(), [...imageChars]);
                  setImageText("");
                  setImageChars(new Set());
                  setImageModalOpen(false);
                }}
              >
                {imaging ? <><span className="spinner" />生成中</> : "生成"}
              </button>
              <button className="btn btn-ghost" onClick={() => { setImageModalOpen(false); setImageText(""); setImageChars(new Set()); }}>
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {moveModalOpen && (
        <div className="overlay-backdrop" onClick={() => setMoveModalOpen(false)}>
          <div className="move-modal" onClick={(e) => e.stopPropagation()}>
            <h3>🚶 移动</h3>
            <label>目标场景</label>
            <input
              type="text"
              className="input"
              placeholder="输入场景名"
              value={moveScene}
              onChange={(e) => setMoveScene(e.target.value)}
            />
            {room?.scene_options && room.scene_options.length > 0 && (
              <div className="scene-options">
                {room.scene_options.map((s) => (
                  <button
                    key={s}
                    className={`btn btn-sm ${s === moveScene ? "active" : ""}`}
                    onClick={() => setMoveScene(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            <label style={{ marginTop: 12 }}>携带 NPC</label>
            <div className="npc-checklist">
              {(cards?.npcs ?? [])
                .filter((n) => n.name !== "上帝")
                .filter((n) => !n.scene || n.scene === room?.current_scene)
                .map((n) => (
                  <label key={n.id} className="npc-check-item">
                    <input
                      type="checkbox"
                      checked={selectedMoveNpcs.has(n.name)}
                      onChange={() => {
                        const next = new Set(selectedMoveNpcs);
                        if (next.has(n.name)) next.delete(n.name);
                        else next.add(n.name);
                        setSelectedMoveNpcs(next);
                      }}
                    />
                    {n.name}
                  </label>
                ))}
            </div>
            <div className="move-actions">
              <button
                className="btn"
                disabled={!moveScene.trim()}
                onClick={() => {
                  moveNpcs(moveScene.trim(), [...selectedMoveNpcs]);
                  setMoveModalOpen(false);
                  setMoveScene("");
                  setSelectedMoveNpcs(new Set());
                }}
              >
                移动
              </button>
              <button className="btn btn-ghost" onClick={() => setMoveModalOpen(false)}>
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
