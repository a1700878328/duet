import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, assetUrl } from "../lib/api";
import type { CharDraft } from "../lib/types";

interface Props {
  roomId: string;
  // Called after a candidate is chosen + written back (refresh + dismiss).
  onDone: () => void | Promise<void>;
}

type Mode = "browse" | "describe";

// Full-screen forced-onboarding character selector. On open it requests AI
// drafts (each with a slow-to-generate 立绘) and lets the player pick one,
// re-roll, or self-describe. "用默认/跳过" dismisses without choosing.
export function CharacterSelect({ roomId, onDone }: Props) {
  const [drafts, setDrafts] = useState<CharDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("browse");
  const [hint, setHint] = useState("");

  // Guard against overlapping fetches (re-roll while a slow one is in flight).
  const reqId = useRef(0);

  const fetchOptions = useCallback(
    async (body: { count?: number; hint?: string }) => {
      const id = ++reqId.current;
      setLoading(true);
      setError(null);
      setDrafts([]);
      try {
        const result = await api.characterOptions(roomId, body);
        if (id !== reqId.current) return; // superseded
        setDrafts(result);
        setMode("browse");
      } catch (err) {
        if (id !== reqId.current) return;
        setError(err instanceof ApiError ? err.message : "生成角色失败");
      } finally {
        if (id === reqId.current) setLoading(false);
      }
    },
    [roomId],
  );

  // Initial load: 3 candidates.
  useEffect(() => {
    void fetchOptions({ count: 3 });
  }, [fetchOptions]);

  async function pick(draft: CharDraft, index: number) {
    setPicking(index);
    setError(null);
    try {
      await api.updateMeCard(roomId, {
        character_name: draft.name,
        persona: draft.persona,
        appearance: draft.appearance ?? null,
        voice_id: draft.voice_id ?? null,
        avatar_url: draft.avatar_url ?? null,
      });
      await onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "选择角色失败");
      setPicking(null);
    }
  }

  function submitHint(e: React.FormEvent) {
    e.preventDefault();
    if (!hint.trim()) return;
    void fetchOptions({ hint: hint.trim(), count: 1 });
  }

  const slots = loading ? Array.from({ length: 3 }, () => null) : drafts;

  return (
    <div className="char-select-overlay" role="dialog" aria-modal="true">
      <div className="char-select-box">
        <header className="char-select-head">
          <div>
            <h2>选择你的角色</h2>
            <p className="muted">
              挑一个 AI 为你生成的角色入场，或自己描述一个。
            </p>
          </div>
          <button
            className="btn btn-ghost char-select-skip"
            onClick={() => void onDone()}
            title="先用默认设定进场，之后可在「🎭 角色」里修改"
          >
            用默认/跳过
          </button>
        </header>

        {error && <div className="error-text">{error}</div>}

        {loading && (
          <p className="muted char-select-hint">
            ✨ 正在生成角色与立绘…（较慢，约需 1–2 分钟，请稍候）
          </p>
        )}

        <div className="char-select-grid">
          {slots.map((draft, i) => (
            <div className="char-card" key={draft ? `${draft.name}-${i}` : i}>
              <div className="char-card-portrait">
                {draft?.avatar_url ? (
                  <img
                    src={assetUrl(draft.avatar_url)}
                    alt={draft.name}
                    loading="lazy"
                  />
                ) : draft ? (
                  <div className="char-card-noart muted">（立绘生成失败）</div>
                ) : (
                  <div className="char-card-skeleton">
                    <span className="spinner spinner-dark" />
                  </div>
                )}
              </div>
              <div className="char-card-body">
                <div className="char-card-name">
                  {draft?.name ?? <span className="skeleton-line" />}
                </div>
                <div className="char-card-persona muted">
                  {draft ? (
                    draft.persona
                  ) : (
                    <>
                      <span className="skeleton-line" />
                      <span className="skeleton-line short" />
                    </>
                  )}
                </div>
                {draft && (
                  <button
                    className="btn btn-primary btn-block"
                    disabled={picking !== null}
                    onClick={() => pick(draft, i)}
                  >
                    {picking === i ? (
                      <>
                        <span className="spinner" />
                        进场中…
                      </>
                    ) : (
                      "✅ 选 TA"
                    )}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        {mode === "describe" ? (
          <form className="char-select-describe" onSubmit={submitHint}>
            <input
              className="input"
              placeholder="描述你想扮演的角色，例如：一名失忆的流浪女剑士，沉默寡言"
              value={hint}
              onChange={(e) => setHint(e.target.value)}
              autoFocus
              disabled={loading}
            />
            <button
              className="btn btn-primary"
              disabled={loading || !hint.trim()}
            >
              生成这个角色
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setMode("browse")}
              disabled={loading}
            >
              取消
            </button>
          </form>
        ) : (
          <div className="char-select-actions">
            <button
              className="btn"
              onClick={() => void fetchOptions({ count: 3 })}
              disabled={loading}
            >
              🎲 换一批
            </button>
            <button
              className="btn"
              onClick={() => setMode("describe")}
              disabled={loading}
            >
              ✍️ 自己描述
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
