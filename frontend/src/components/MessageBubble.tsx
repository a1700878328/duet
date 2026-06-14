import { assetUrl } from "../lib/api";
import type { Message } from "../lib/types";

interface Props {
  message: Pick<Message, "author_type" | "author_user_id" | "speaker_label" | "content">;
  isMe: boolean;
  streaming?: boolean;
  // Resolved portrait for the speaker (player or NPC); null/undefined = fallback circle.
  avatarUrl?: string | null;
  // If provided (NPC lines with a voice), shows a 🔊 play/replay button.
  onPlayVoice?: () => void;
  // Click the speaker's avatar → open the in-page profile popover.
  onAvatarClick?: () => void;
  // Click a scene image → open the in-page lightbox.
  onImageClick?: () => void;
}

// A round avatar; falls back to a tinted circle with the speaker's initial.
// Clicking opens the profile popover (never navigates away).
function Avatar({
  url,
  label,
  variant,
  onClick,
}: {
  url?: string | null;
  label: string;
  variant: "me" | "ai" | "other";
  onClick?: () => void;
}) {
  const initial = label.trim().charAt(0) || (variant === "ai" ? "🎭" : "?");
  const inner = url ? (
    <img src={assetUrl(url)} alt={label} loading="lazy" />
  ) : (
    <span aria-hidden>{initial}</span>
  );
  return (
    <button
      type="button"
      className={`bubble-avatar${url ? "" : ` fallback ${variant}`}`}
      title={label}
      onClick={onClick}
      disabled={!onClick}
    >
      {inner}
    </button>
  );
}

export function MessageBubble({
  message,
  isMe,
  streaming = false,
  avatarUrl,
  onPlayVoice,
  onAvatarClick,
  onImageClick,
}: Props) {
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
        <button
          type="button"
          className="image-bubble"
          onClick={onImageClick}
          title="点击查看大图"
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
        </button>
      </div>
    );
  }

  const isAi = author_type === "ai";
  const rowClass = isMe ? "me" : isAi ? "ai" : "other";
  const variant = isMe ? "me" : isAi ? "ai" : "other";
  const label = speaker_label || (isAi ? "NPC" : isMe ? "我" : "对方");

  const avatar = (
    <Avatar
      url={avatarUrl}
      label={label}
      variant={variant}
      onClick={onAvatarClick}
    />
  );

  return (
    <div className={`bubble-row ${rowClass} has-avatar`}>
      {!isMe && avatar}
      <div className="bubble-col">
        {!isMe && (
          <div className="speaker">
            {speaker_label || (isAi ? "NPC" : "对方")}
            {isAi && <span className="tag">NPC / 旁白</span>}
            {onPlayVoice && (
              <button
                type="button"
                onClick={onPlayVoice}
                title="播放/重播配音"
                aria-label="播放配音"
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontSize: 13,
                  padding: "0 2px",
                  marginLeft: 4,
                  opacity: 0.75,
                }}
              >
                🔊
              </button>
            )}
          </div>
        )}
        <div className="bubble">
          {content}
          {streaming && <span className="cursor" aria-hidden />}
        </div>
      </div>
      {isMe && avatar}
    </div>
  );
}
