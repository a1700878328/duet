import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Composer } from "../components/Composer";
import { MessageBubble } from "../components/MessageBubble";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useRoomSocket } from "../lib/useRoomSocket";
import type { Room } from "../lib/types";

const NEAR_BOTTOM_PX = 80;

export function RoomPage() {
  const { roomId = "" } = useParams();
  const { user, token } = useAuth();
  const navigate = useNavigate();

  const [room, setRoom] = useState<Room | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [autoMode, setAutoMode] = useState(false);

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

  const { status, messages, streaming, presence, aiBusy, say, advance, setTyping } =
    useRoomSocket({ roomId, token: token ?? "", onError: handleWsError });

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
          <span className={`status`}>
            <span className={`dot ${status}`} />
            {status === "open"
              ? "已连接"
              : status === "connecting"
                ? "连接中"
                : "已断开"}
          </span>
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

        {aiBusy && (
          <div className="streaming-hint">
            <span className="pulse" />
            AI 接话中…
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
          onClick={advance}
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
      </div>

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
