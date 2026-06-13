import { useCallback, useEffect, useRef, useState } from "react";
import { api, roomSocketUrl } from "./api";
import type {
  ConnectionStatus,
  Message,
  StreamingTurn,
  WsClientEvent,
  WsServerEvent,
} from "./types";

interface UseRoomSocketOptions {
  roomId: string;
  token: string;
  onError?: (code: string, detail: string) => void;
}

interface UseRoomSocketResult {
  status: ConnectionStatus;
  messages: Message[];
  streaming: StreamingTurn | null;
  presence: Map<string, boolean>;
  aiBusy: boolean;
  imaging: boolean;
  say: (content: string) => void;
  advance: () => void;
  requestImage: (nsfw: boolean) => void;
  setTyping: (isTyping: boolean) => void;
}

const RECONNECT_BASE_MS = 800;
const RECONNECT_MAX_MS = 8000;

/**
 * Encapsulates the room WebSocket lifecycle: connect, reconnect with backoff,
 * streaming AI-delta accumulation, presence, and after_seq backfill on reconnect.
 */
export function useRoomSocket({
  roomId,
  token,
  onError,
}: UseRoomSocketOptions): UseRoomSocketResult {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState<StreamingTurn | null>(null);
  const [presence, setPresence] = useState<Map<string, boolean>>(new Map());
  const [aiBusy, setAiBusy] = useState(false);
  const [imaging, setImaging] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const lastSeqRef = useRef(0);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const closedByUserRef = useRef(false);
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  // Merge messages keeping seq order and de-duping by seq.
  const mergeMessages = useCallback((incoming: Message[]) => {
    setMessages((prev) => {
      const bySeq = new Map<number, Message>();
      for (const m of prev) bySeq.set(m.seq, m);
      for (const m of incoming) bySeq.set(m.seq, m);
      const merged = [...bySeq.values()].sort((a, b) => a.seq - b.seq);
      const maxSeq = merged.length ? merged[merged.length - 1].seq : 0;
      if (maxSeq > lastSeqRef.current) lastSeqRef.current = maxSeq;
      return merged;
    });
  }, []);

  const backfill = useCallback(async () => {
    try {
      const history = await api.messages(roomId, lastSeqRef.current);
      if (history.length) mergeMessages(history);
    } catch {
      /* best-effort backfill; WS history event also seeds */
    }
  }, [roomId, mergeMessages]);

  const handleEvent = useCallback(
    (event: WsServerEvent) => {
      switch (event.type) {
        case "history":
          mergeMessages(event.messages);
          break;
        case "message":
          mergeMessages([event.message]);
          if (event.message.author_type === "image") setImaging(false);
          break;
        case "image_pending":
          setImaging(true);
          break;
        case "ai_delta":
          setAiBusy(true);
          setStreaming((prev) => {
            if (prev && prev.turn_id === event.turn_id) {
              return { ...prev, content: prev.content + event.delta };
            }
            return {
              turn_id: event.turn_id,
              seq: event.seq,
              content: event.delta,
            };
          });
          break;
        case "ai_done": {
          setStreaming(null);
          setAiBusy(false);
          mergeMessages([
            {
              id: `ai-${event.turn_id}`,
              room_id: roomId,
              seq: event.seq,
              author_type: "ai",
              author_user_id: null,
              speaker_label: "NPC",
              content: event.content,
              created_at: new Date().toISOString(),
            },
          ]);
          break;
        }
        case "presence":
          setPresence((prev) => {
            const next = new Map(prev);
            next.set(event.user_id, event.online);
            return next;
          });
          break;
        case "error":
          if (event.code === "ai_busy") setAiBusy(false);
          if (event.code === "image_failed" || event.code === "image_busy")
            setImaging(false);
          onErrorRef.current?.(event.code, event.detail);
          break;
      }
    },
    [roomId, mergeMessages],
  );

  const connect = useCallback(() => {
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    setStatus("connecting");
    const ws = new WebSocket(roomSocketUrl(roomId, token));
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptsRef.current = 0;
      setStatus("open");
      // Backfill anything missed while disconnected.
      void backfill();
    };

    ws.onmessage = (ev) => {
      try {
        handleEvent(JSON.parse(ev.data) as WsServerEvent);
      } catch {
        /* ignore malformed frame */
      }
    };

    ws.onclose = () => {
      setStatus("closed");
      setStreaming(null);
      setAiBusy(false);
      if (closedByUserRef.current) return;
      const attempt = reconnectAttemptsRef.current++;
      const delay = Math.min(
        RECONNECT_BASE_MS * 2 ** attempt,
        RECONNECT_MAX_MS,
      );
      reconnectTimerRef.current = window.setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [roomId, token, backfill, handleEvent]);

  useEffect(() => {
    closedByUserRef.current = false;
    connect();
    return () => {
      closedByUserRef.current = true;
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((payload: WsClientEvent) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }, []);

  const say = useCallback(
    (content: string) => {
      const trimmed = content.trim();
      if (trimmed) send({ type: "say", content: trimmed });
    },
    [send],
  );

  const advance = useCallback(() => {
    setAiBusy(true);
    send({ type: "advance" });
  }, [send]);

  const requestImage = useCallback(
    (nsfw: boolean) => {
      setImaging(true);
      send({ type: "image", nsfw });
    },
    [send],
  );

  const setTyping = useCallback(
    (isTyping: boolean) => send({ type: "typing", is_typing: isTyping }),
    [send],
  );

  return {
    status,
    messages,
    streaming,
    presence,
    aiBusy,
    imaging,
    say,
    advance,
    requestImage,
    setTyping,
  };
}
