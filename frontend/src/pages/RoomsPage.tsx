import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, lobbySocketUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { LanguageSelect, useI18n } from "../lib/i18n";
import type { Room } from "../lib/types";

export function RoomsPage() {
  const { user, token, logout } = useAuth();
  const { locale, t } = useI18n();
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
      setError(err instanceof ApiError ? err.message : t("loadRoomsFailed"));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [t]);

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
      const name =
        newName.trim() ||
        t("myRoomName", { name: user?.display_name ?? t("me") });
      // Character setup happens in-room via CharacterSelect; default to the
      // display name so the member exists — the selector sets the real one.
      const room = await api.createRoom({
        name,
        character_name: user?.display_name || t("player"),
        world_card: newWorld || null,
        locale,
      });
      navigate(`/rooms/${room.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("createFailed"));
      setBusy(false);
    }
  }

  async function deleteRoom(room: Room) {
    if (
      !window.confirm(
        t("deleteRoomConfirm", { room: room.name }),
      )
    )
      return;
    setDeletingId(String(room.id));
    setError(null);
    try {
      await api.deleteRoom(String(room.id));
      setRooms((prev) => prev.filter((r) => String(r.id) !== String(room.id)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("deleteFailed"));
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
        character_name: user?.display_name || t("player"),
        locale,
      });
      navigate(`/rooms/${room.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("joinFailed"));
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
        character_name: user?.display_name || t("player"),
        locale,
      });
      navigate(`/rooms/${joined.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("joinFailed"));
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>{t("publicRooms")}</h2>
        <div className="row">
          <LanguageSelect compact />
          <span className="muted">{user?.display_name}</span>
          <button className="btn btn-ghost" onClick={() => navigate("/agents")}>
            {t("agents")}
          </button>
          <button className="btn btn-ghost" onClick={logout}>
            {t("logout")}
          </button>
        </div>
      </div>

      {error && <div className="error-text" style={{ marginBottom: 12 }}>{error}</div>}

      <div className="panel">
        <h3>{t("createRoom")}</h3>
        <form className="inline-form" onSubmit={createRoom}>
          <input
            className="input"
            placeholder={t("roomNamePlaceholder", {
              name: user?.display_name ?? t("me"),
            })}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <select
            className="input"
            value={newWorld}
            onChange={(e) => setNewWorld(e.target.value)}
            title={t("worldCard")}
          >
            <option value="">{t("noWorldCard")}</option>
            <option value="ksim">{t("ksimWorld")}</option>
          </select>
          <button className="btn btn-primary" disabled={busy}>
            {t("create")}
          </button>
        </form>
        <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>
          {t("createRoomHint")}
        </p>
      </div>

      <div className="panel">
        <h3>{t("joinById")}</h3>
        <form className="inline-form" onSubmit={joinRoom}>
          <input
            className="input"
            placeholder={t("roomId")}
            value={joinId}
            onChange={(e) => setJoinId(e.target.value)}
          />
          <button className="btn" disabled={busy}>
            {t("join")}
          </button>
        </form>
      </div>

      {loading ? (
        <div className="empty">{t("loading")}</div>
      ) : rooms.length === 0 ? (
        <div className="empty">{t("noPublicRooms")}</div>
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
                    title={t("deleteRoomTitle")}
                    aria-label={t("deleteRoomLabel")}
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
                  <span className="chip ai">{t("aiNpc")}</span>
                  {room.world_card === "ksim" && (
                    <span className="chip">🗺 {t("ksimWorld")}</span>
                  )}
                  {!isMember && <span className="chip">{t("joinable")}</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
