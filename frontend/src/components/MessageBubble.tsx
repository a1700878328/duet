import { assetUrl } from "../lib/api";
import type { Message } from "../lib/types";

interface Props {
  message: Pick<Message, "author_type" | "author_user_id" | "speaker_label" | "content">;
  isMe: boolean;
  streaming?: boolean;
}

export function MessageBubble({ message, isMe, streaming = false }: Props) {
  const { author_type, speaker_label, content } = message;

  if (author_type === "system") {
    return (
      <div className="bubble-row system">
        <div className="bubble">{content}</div>
      </div>
    );
  }

  if (author_type === "image") {
    return (
      <div className={`bubble-row ${isMe ? "me" : "other"}`}>
        {!isMe && <div className="speaker">{speaker_label || "场景图"}</div>}
        <a
          className="image-bubble"
          href={assetUrl(content)}
          target="_blank"
          rel="noreferrer"
        >
          <img
            src={assetUrl(content)}
            alt="场景图"
            loading="lazy"
            style={{
              maxWidth: "min(360px, 80vw)",
              borderRadius: 12,
              display: "block",
            }}
          />
        </a>
      </div>
    );
  }

  const isAi = author_type === "ai";
  const rowClass = isMe ? "me" : isAi ? "ai" : "other";

  return (
    <div className={`bubble-row ${rowClass}`}>
      {!isMe && (
        <div className="speaker">
          {speaker_label || (isAi ? "NPC" : "对方")}
          {isAi && <span className="tag">NPC / 旁白</span>}
        </div>
      )}
      <div className="bubble">
        {content}
        {streaming && <span className="cursor" aria-hidden />}
      </div>
    </div>
  );
}
