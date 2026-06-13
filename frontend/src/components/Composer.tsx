import {
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";

interface Props {
  onSend: (text: string) => void;
  onTyping?: (isTyping: boolean) => void;
  disabled?: boolean;
}

export function Composer({ onSend, onTyping, disabled = false }: Props) {
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
    </div>
  );
}
