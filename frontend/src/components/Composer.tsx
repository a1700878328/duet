import {
  useRef,
  useEffect,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";
import { useI18n } from "../lib/i18n";

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
  const { t } = useI18n();
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
        placeholder={t("composerPlaceholder")}
        value={text}
        onChange={onChange}
        onKeyDown={onKeyDown}
      />
      <button
        className="btn btn-primary send-btn"
        onClick={send}
        disabled={disabled || !text.trim()}
      >
        {t("send")}
      </button>
      {onPolish && (
        <button
          className="btn btn-ghost polish-btn"
          onClick={() => onPolish(text)}
          disabled={disabled || polishing || !text.trim()}
          title={t("polishTitle")}
        >
          {polishing ? (
            <>
              <span className="spinner spinner-dark" />
              {t("polishing")}
            </>
          ) : (
            t("aiPolish")
          )}
        </button>
      )}
    </div>
  );
}
