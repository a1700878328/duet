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
import { StatsPanel } from "../components/StatsPanel";
import { api, ApiError, assetUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useRoomSocket, type StatsEvent } from "../lib/useRoomSocket";
import type { CharStats, Message, RoomCards, Room, StatValue } from "../lib/types";

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
  const [autoMode, setAutoMode] = useState(false);
  const [nsfw, setNsfw] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [statsOpen, setStatsOpen] = useState(false);
  // 叙事时间：第 N 周（room 元数据 seed，week 事件实时更新）。
  const [week, setWeek] = useState(1);
  // 当前场景标签（""=自由世界无分区）；移动面板开关。
  const [scene, setScene] = useState("");
  const [sceneMoveOpen, setSceneMoveOpen] = useState(false);
  const [sceneDraft, setSceneDraft] = useState("");
  // Forced onboarding: dismissed once chosen or skipped (one-time per visit).
  const [charSelectDismissed, setCharSelectDismissed] = useState(false);

  // My live stat sheet — seeded from my card, updated by "stats" WS events.
  const [myStats, setMyStats] = useState<CharStats | null>(null);
  // Brief floating "增量" flash after a beat (cleared on a timer).
  const [deltaFlash, setDeltaFlash] = useState<string | null>(null);
  const deltaTimer = useRef<number | null>(null);

  // Lifted cards state — shared by bubbles (avatar resolver) and the panel.
  const [cards, setCards] = useState<RoomCards | null>(null);
  const refreshCards = useCallback(async () => {
    try {
      setCards(await api.getCards(roomId));
    } catch {
      /* best-effort; panel surfaces its own errors */
    }
  }, [roomId]);

  // Voice playback (off by default).
  const [voiceOn, setVoiceOn] = useState(false);
  const [voicing, setVoicing] = useState(false);

  const toastTimer = useRef<number | null>(null);
  const showToast = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  }, []);

  const handleWsError = useCallback(
    (code: string, detail: string) => {
      if (code === "ai_busy") showToast("AI 正在接话，请稍候…");
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

  const handleWeek = useCallback((w: number) => setWeek(w), []);
  const handleScene = useCallback((s: string) => {
    setScene(s);
    setSceneMoveOpen(false);
  }, []);

  const {
    status,
    messages,
    streaming,
    presence,
    aiBusy,
    imaging,
    say,
    advance,
    timeskip,
    requestImage,
    gotoScene,
    setTyping,
  } = useRoomSocket({
    roomId,
    token: token ?? "",
    onError: handleWsError,
    onCardsChanged: refreshCards,
    onStats: handleStats,
    onWeek: handleWeek,
    onScene: handleScene,
  });

  // Load room metadata for header.
  useEffect(() => {
    let active = true;
    api
      .listRooms()
      .then((rooms) => {
        if (!active) return;
        const found =
          rooms.find((r) => String(r.id) === String(roomId)) ?? null;
        setRoom(found);
        if (found?.week) setWeek(found.week);
        if (found?.current_scene) setScene(found.current_scene);
        if (!found) setLoadError("未找到房间，或你不在其中。");
      })
      .catch((err) => {
        if (active)
          setLoadError(err instanceof ApiError ? err.message : "加载房间失败");
      });
    return () => {
      active = false;
    };
  }, [roomId]);

  // Load cards once on mount (panel refreshes again on open / after mutations).
  useEffect(() => {
    void refreshCards();
  }, [refreshCards]);

  // 已知场景：当前场景 + 所有 NPC 的 scene 标签（去重）。
  const knownScenes = useMemo(() => {
    const set = new Set<string>();
    if (scene) set.add(scene);
    for (const n of cards?.npcs ?? []) if (n.scene) set.add(n.scene);
    return [...set];
  }, [scene, cards]);

  // ---- avatar resolver ----------------------------------------------------
  // player msg (author_type 'user'): match author_user_id -> MemberCard.avatar_url
  // ai/npc msg  (author_type 'ai'):  match speaker_label === npc.name -> NpcCard.avatar_url
  const playerAvatars = useMemo(() => {
    const m = new Map<string, string | null | undefined>();
    for (const p of cards?.players ?? []) m.set(String(p.user_id), p.avatar_url);
    return m;
  }, [cards]);

  const npcByName = useMemo(() => {
    const m = new Map<string, { voice_id?: string | null; avatar_url?: string | null }>();
    for (const n of cards?.npcs ?? [])
      m.set(n.name, { voice_id: n.voice_id, avatar_url: n.avatar_url });
    return m;
  }, [cards]);

  // Resolve MY member card from the lifted cards (match user_id).
  const myCard = useMemo(
    () =>
      cards?.players.find((p) => String(p.user_id) === String(user?.id)) ??
      null,
    [cards, user?.id],
  );
  // Seed my stat sheet from the lifted card. WS "stats" events take over after
  // the first beat; only seed when we don't already hold live stats.
  useEffect(() => {
    if (myCard?.stats) setMyStats((prev) => prev ?? myCard.stats ?? null);
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
    !charSelectDismissed && myCard !== null && !myCard.persona;

  const dismissCharSelect = useCallback(async () => {
    setCharSelectDismissed(true);
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

  // Auto-mode: when on, advance shortly after my own message lands (minimal logic).
  const lastSeenSeq = useRef(0);
  useEffect(() => {
    if (messages.length === 0) return;
    const last = messages[messages.length - 1];
    if (last.seq <= lastSeenSeq.current) return;
    lastSeenSeq.current = last.seq;
    if (
      autoMode &&
      !aiBusy &&
      last.author_type === "user" &&
      last.author_user_id === user?.id
    ) {
      const t = window.setTimeout(() => advance(), 400);
      return () => window.clearTimeout(t);
    }
  }, [messages, autoMode, aiBusy, advance, user?.id]);

  // ---- voice playback -----------------------------------------------------
  // Serialize TTS via one <audio>; cache by seq so a line is synthesized once.
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const ttsCacheRef = useRef<Map<number, string>>(new Map());
  const playQueueRef = useRef<string[]>([]);
  const playingRef = useRef(false);
  const lastVoiceSeqRef = useRef(0);

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
    void audio.play().catch(() => {
      playingRef.current = false;
      drainQueue();
    });
  }, []);

  const enqueueVoice = useCallback(
    async (msg: Message) => {
      const cached = ttsCacheRef.current.get(msg.seq);
      if (cached) {
        playQueueRef.current.push(cached);
        drainQueue();
        return;
      }
      const text = stripSpeakerPrefix(msg.content);
      if (!text) return;
      const voiceId = npcByName.get(msg.speaker_label)?.voice_id ?? null;
      setVoicing(true);
      try {
        const { url } = await api.tts(roomId, text, voiceId);
        ttsCacheRef.current.set(msg.seq, url);
        playQueueRef.current.push(url);
        drainQueue();
      } catch {
        showToast("配音失败");
      } finally {
        setVoicing(false);
      }
    },
    [roomId, npcByName, drainQueue, showToast],
  );

  // When voice is ON, synthesize+play NEW NPC/AI lines (skip 旁白/system/player).
  useEffect(() => {
    if (!voiceOn || messages.length === 0) return;
    const last = messages[messages.length - 1];
    if (last.seq <= lastVoiceSeqRef.current) return;
    lastVoiceSeqRef.current = last.seq;
    if (last.author_type !== "ai") return;
    const label = last.speaker_label?.trim();
    if (!label || label === "旁白" || label === "NPC") return;
    if (!npcByName.has(label)) return; // only voice known NPCs
    void enqueueVoice(last);
  }, [messages, voiceOn, npcByName, enqueueVoice]);

  // Keep the voice cursor at the latest seq when toggled on, so we don't
  // suddenly synthesize backlog.
  useEffect(() => {
    if (voiceOn && messages.length)
      lastVoiceSeqRef.current = messages[messages.length - 1].seq;
  }, [voiceOn]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return () => {
      audioRef.current?.pause();
    };
  }, []);

  function memberOnline(userId: string): boolean {
    return presence.get(userId) ?? false;
  }

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
          <span className="week-chip" title="叙事时间（每满 4 周月末结算）">
            🗓 第{week}周
          </span>
          {scene && (
            <div className="scene-ctrl">
              <button
                className="week-chip scene-chip"
                onClick={() => setSceneMoveOpen((o) => !o)}
                title="移动到其它场景"
              >
                📍 {scene} ▾
              </button>
              {sceneMoveOpen && (
                <div className="scene-pop">
                  {knownScenes
                    .filter((s) => s !== scene)
                    .map((s) => (
                      <button
                        key={s}
                        className="scene-opt"
                        disabled={aiBusy}
                        onClick={() => gotoScene(s)}
                      >
                        {s}
                      </button>
                    ))}
                  <div className="scene-new">
                    <input
                      value={sceneDraft}
                      onChange={(e) => setSceneDraft(e.target.value)}
                      placeholder="去新地点…"
                      maxLength={64}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && sceneDraft.trim()) {
                          gotoScene(sceneDraft);
                          setSceneDraft("");
                        }
                      }}
                    />
                    <button
                      disabled={aiBusy || !sceneDraft.trim()}
                      onClick={() => {
                        gotoScene(sceneDraft);
                        setSceneDraft("");
                      }}
                    >
                      前往
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
          <span className={`status`}>
            <span className={`dot ${status}`} />
            {status === "open"
              ? "已连接"
              : status === "connecting"
                ? "连接中"
                : "已断开"}
          </span>
          <button
            className={`btn btn-ghost voice-toggle ${voiceOn ? "active" : ""}`}
            onClick={() => setVoiceOn((v) => !v)}
            aria-pressed={voiceOn}
            title={voiceOn ? "关闭 NPC 语音播放" : "开启 NPC 语音播放"}
          >
            {voiceOn ? "🔊" : "🔇"}
          </button>
          <button
            className={`btn btn-ghost cards-toggle ${panelOpen ? "active" : ""}`}
            onClick={() => setPanelOpen((v) => !v)}
            aria-pressed={panelOpen}
            title="角色卡与登场 NPC"
          >
            🎭 角色
          </button>
          <button
            className={`btn btn-ghost cards-toggle ${statsOpen ? "active" : ""}`}
            onClick={() => setStatsOpen((v) => !v)}
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

          <label className="toggle" style={{ marginLeft: "auto" }}>
            <span>自动</span>
            <span
              className={`switch ${autoMode ? "on" : ""}`}
              onClick={() => setAutoMode((v) => !v)}
              role="switch"
              aria-checked={autoMode}
            />
          </label>
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
              m.author_type === "ai" && npcByName.has(m.speaker_label)
                ? () => void enqueueVoice(m)
                : undefined
            }
          />
        ))}

        {streaming && (
          <MessageBubble
            message={{
              author_type: "ai",
              author_user_id: null,
              speaker_label: "NPC",
              content: streaming.content,
            }}
            isMe={false}
            streaming
          />
        )}

        {voicing && (
          <div className="streaming-hint voice-hint">
            <span className="pulse" />
            🔊 配音中…
          </div>
        )}

        {aiBusy && (
          <div className="streaming-hint">
            <span className="pulse" />
            AI 接话中…
          </div>
        )}

        {imaging && (
          <div className="streaming-hint">
            <span className="pulse" />
            生成场景图中…（约 30–60 秒）
          </div>
        )}
      </div>

      <div className="composer">
        <Composer
          onSend={say}
          onTyping={setTyping}
          disabled={status !== "open"}
        />
        <button
          className="btn btn-primary advance-btn"
          onClick={() => advance()}
          disabled={aiBusy || status !== "open"}
        >
          {aiBusy ? (
            <>
              <span className="spinner" />
              AI 接话中…
            </>
          ) : (
            "让 AI 接话"
          )}
        </button>
        <button
          className="btn"
          onClick={() => timeskip()}
          disabled={aiBusy || status !== "open"}
          title="推进剧情时间：跳过一段时间，NPC 各自行动、世界演进"
        >
          ⏩ 推进时间
        </button>
        <button
          className="btn"
          onClick={() => requestImage(nsfw)}
          disabled={imaging || status !== "open"}
          title="根据当前剧情生成一张场景图"
        >
          {imaging ? (
            <>
              <span className="spinner" />
              生成图中…
            </>
          ) : (
            "🎨 生成图"
          )}
        </button>
        <label className="toggle" title="生成 R18 图">
          <input
            type="checkbox"
            checked={nsfw}
            onChange={(e) => setNsfw(e.target.checked)}
          />
          <span>R18</span>
        </label>
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
        onNpcSpeak={(npcId) => {
          advance(npcId);
          setPanelOpen(false);
        }}
      />

      <StatsPanel
        open={statsOpen}
        onClose={() => setStatsOpen(false)}
        stats={myStats}
        characterName={myCard?.character_name}
      />

      {needsCharSelect && (
        <CharacterSelect roomId={roomId} onDone={dismissCharSelect} />
      )}

      {deltaFlash && (
        <div className="delta-flash" role="status">
          {deltaFlash}
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
