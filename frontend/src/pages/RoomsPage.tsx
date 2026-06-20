import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, lobbySocketUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { Room } from "../lib/types";

export function RoomsPage() {
  const { user, token, logout } = useAuth();
  const navigate = useNavigate();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [newWorld, setNewWorld] = useState("");
  const [joinId, setJoinId] = useState("");
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      setRooms(await api.listRooms());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载房间失败");
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!token) return;
    let closed = false;
    let retryTimer: number | null = null;
    let ws: WebSocket | null = null;

    const connect = () => {
      ws = new WebSocket(lobbySocketUrl(token));
      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { type?: string };
          if (payload.type === "rooms_changed") void load(false);
        } catch {
          /* ignore malformed lobby frame */
        }
      };
      ws.onclose = () => {
        if (closed) return;
        retryTimer = window.setTimeout(connect, 1200);
      };
      ws.onerror = () => {
        ws?.close();
      };
    };

    connect();
    return () => {
      closed = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      ws?.close();
    };
  }, [token, load]);

  async function createRoom(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const name = newName.trim() || `${user?.display_name ?? "我"}的房间`;
      // Character setup happens in-room via CharacterSelect; default to the
      // display name so the member exists — the selector sets the real one.
      const room = await api.createRoom({
        name,
        character_name: user?.display_name || "玩家",
        world_card: newWorld || null,
      });
      navigate(`/rooms/${room.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "创建失败");
      setBusy(false);
    }
  }

  async function deleteRoom(room: Room) {
    if (
      !window.confirm(
        `删除房间「${room.name}」？房间内所有对话、角色、NPC 都会一并清空，无法恢复。`,
      )
    )
      return;
    setDeletingId(String(room.id));
    setError(null);
    try {
      await api.deleteRoom(String(room.id));
      setRooms((prev) => prev.filter((r) => String(r.id) !== String(room.id)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  }

  async function joinRoom(e: FormEvent) {
    e.preventDefault();
    if (!joinId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const room = await api.joinRoom(joinId.trim(), {
        character_name: user?.display_name || "玩家",
      });
      navigate(`/rooms/${room.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加入失败");
      setBusy(false);
    }
  }

  async function enterRoom(room: Room) {
    const isMember = room.members.some((m) => String(m.user_id) === String(user?.id));
    if (isMember) {
      navigate(`/rooms/${room.id}`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const joined = await api.joinRoom(String(room.id), {
        character_name: user?.display_name || "玩家",
      });
      navigate(`/rooms/${joined.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加入失败");
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>公开房间</h2>
        <div className="row">
          <span className="muted">{user?.display_name}</span>
          <button className="btn btn-ghost" onClick={() => navigate("/agents")}>
            Agents
          </button>
          <button className="btn btn-ghost" onClick={logout}>
            退出
          </button>
        </div>
      </div>

      {error && <div className="error-text" style={{ marginBottom: 12 }}>{error}</div>}

      <div className="panel">
        <h3>创建房间</h3>
        <form className="inline-form" onSubmit={createRoom}>
          <input
            className="input"
            placeholder={`房间名（留空＝${user?.display_name ?? "我"}的房间）`}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <select
            className="input"
            value={newWorld}
            onChange={(e) => setNewWorld(e.target.value)}
            title="世界卡"
          >
            <option value="">无世界卡</option>
            <option value="ksim">女骑士模拟器</option>
          </select>
          <button className="btn btn-primary" disabled={busy}>
            创建
          </button>
        </form>
        <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>
          进入房间后会让你选角色（AI 生成参考图任你挑，或自己描述）。世界卡＝这场戏的背景设定。
        </p>
      </div>

      <div className="panel">
        <h3>按 ID 加入</h3>
        <form className="inline-form" onSubmit={joinRoom}>
          <input
            className="input"
            placeholder="房间 ID"
            value={joinId}
            onChange={(e) => setJoinId(e.target.value)}
          />
          <button className="btn" disabled={busy}>
            加入
          </button>
        </form>
      </div>

      {loading ? (
        <div className="empty">加载中…</div>
      ) : rooms.length === 0 ? (
        <div className="empty">还没有公开房间，创建一个开始吧。</div>
      ) : (
        <div className="room-list">
          {rooms.map((room) => {
            const isOwner = String(room.owner_id) === String(user?.id);
            const isMember = room.members.some(
              (m) => String(m.user_id) === String(user?.id),
            );
            return (
              <div
                key={room.id}
                className="room-card"
                role="button"
                tabIndex={0}
                onClick={() => void enterRoom(room)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void enterRoom(room);
                }}
              >
                {isOwner && (
                  <button
                    className="room-delete"
                    title="删除房间（仅房主）"
                    aria-label="删除房间"
                    disabled={deletingId === String(room.id)}
                    onClick={(e) => {
                      e.stopPropagation();
                      void deleteRoom(room);
                    }}
                  >
                    {deletingId === String(room.id) ? "…" : "🗑"}
                  </button>
                )}
                <div className="room-name">{room.name}</div>
                <div className="room-meta">
                  {room.members.map((m) => (
                    <span key={m.user_id} className="chip">
                      <span className="chip-char">{m.character_name}</span>
                      <span>· {m.display_name}</span>
                    </span>
                  ))}
                  <span className="chip ai">NPC · AI</span>
                  {room.world_card === "ksim" && (
                    <span className="chip">🗺 女骑士模拟器</span>
                  )}
                  {!isMember && <span className="chip">可加入</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
