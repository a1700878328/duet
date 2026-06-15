import {
  useRef,
  useEffect,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";

interface Props {
  onSend: (text: string) => void;
  onPolish?: (text: string) => void;
  onTyping?: (isTyping: boolean) => void;
  disabled?: boolean;
  polishing?: boolean;
  draftText?: string | null;
}

export function Composer({
  onSend,
  onPolish,
  onTyping,
  disabled = false,
  polishing = false,
  draftText,
}: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  function autosize() {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  }

  function send() {
    const value = text.trim();
    if (!value || disabled) return;
    onSend(value);
    setText("");
    onTyping?.(false);
    requestAnimationFrame(() => {
      if (ref.current) ref.current.style.height = "auto";
    });
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function onChange(e: ChangeEvent<HTMLTextAreaElement>) {
    setText(e.target.value);
    onTyping?.(e.target.value.length > 0);
    autosize();
  }

  useEffect(() => {
    if (draftText === null || draftText === undefined) return;
    setText(draftText);
    onTyping?.(draftText.length > 0);
    requestAnimationFrame(autosize);
  }, [draftText]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="composer-row">
      <textarea
        ref={ref}
        rows={1}
        placeholder="说点什么…（Enter 发送，Shift+Enter 换行）"
        value={text}
        onChange={onChange}
        onKeyDown={onKeyDown}
      />
      <button
        className="btn btn-primary send-btn"
        onClick={send}
        disabled={disabled || !text.trim()}
      >
        发送
      </button>
      {onPolish && (
        <button
          className="btn btn-ghost polish-btn"
          onClick={() => onPolish(text)}
          disabled={disabled || polishing || !text.trim()}
          title="让 AI 按你的角色卡改写到输入框，不会自动发送"
        >
          {polishing ? (
            <>
              <span className="spinner spinner-dark" />
              改写中…
            </>
          ) : (
            "AI 改写"
          )}
        </button>
      )}
    </div>
  );
}
