import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, assetUrl } from "../lib/api";
import { MEDIA_GENERATION_ENABLED } from "../lib/features";
import type { CharDraft, NpcCard, UserCharacterCard } from "../lib/types";

interface Props {
  roomId: string;
  // Called after a candidate is chosen + written back (refresh + dismiss).
  onDone: () => void | Promise<void>;
}

type Mode = "browse" | "describe";

// Full-screen character selector. Slow AI drafts/portraits are opt-in so room
// creation stays fast for quick two-player sessions.
export function CharacterSelect({ roomId, onDone }: Props) {
  const [drafts, setDrafts] = useState<CharDraft[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("browse");
  const [hint, setHint] = useState("");
  const [customName, setCustomName] = useState("");
  const [presetCharacters, setPresetCharacters] = useState<NpcCard[]>([]);
  const [libraryCards, setLibraryCards] = useState<UserCharacterCard[]>([]);
  const [protagonist, setProtagonist] = useState<CharDraft | null>(null);
  const [expectedCount, setExpectedCount] = useState(3);

  // Guard against overlapping fetches (re-roll while a slow one is in flight).
  const reqId = useRef(0);

  const fetchOptions = useCallback(
    async (body: { count?: number; hint?: string }) => {
      const id = ++reqId.current;
      const targetCount = body.count ?? 3;
      setExpectedCount(targetCount);
      setLoading(true);
      setError(null);
      setDrafts([]);
      try {
        const result = await api.characterOptions(roomId, body);
        if (id !== reqId.current) return; // superseded
        if (!result.length) {
          setError("AI 这次没有生成候选。再点一次，或直接自己描述进场。");
        }
        setDrafts(result);
        setMode("browse");
      } catch (err) {
        if (id !== reqId.current) return;
        setError(err instanceof ApiError ? err.message : "生成角色失败");
        setDrafts([]);
      } finally {
        if (id === reqId.current) setLoading(false);
      }
    },
    [roomId],
  );

  useEffect(() => {
    let active = true;
    api
      .presetCharacters(roomId)
      .then((items) => {
        if (active) setPresetCharacters(items);
      })
      .catch(() => {
        if (active) setPresetCharacters([]);
      });
    api
      .listMyCharacterCards()
      .then((items) => {
        if (active) setLibraryCards(items);
      })
      .catch(() => {
        if (active) setLibraryCards([]);
      });
    api
      .getProtagonist(roomId)
      .then((card) => {
        if (active) setProtagonist(card);
      })
      .catch(() => {
        if (active) setProtagonist(null);
      });
    return () => {
      active = false;
    };
  }, [roomId]);

  async function pick(draft: CharDraft, index: number) {
    setPicking(index);
    setError(null);
    try {
      await api.updateMeCard(roomId, {
        character_name: draft.name,
        persona: draft.persona,
        appearance: draft.appearance ?? null,
        voice_id: draft.voice_id ?? null,
        voice_ref_url: draft.voice_ref_url ?? null,
        voice_ref_text: draft.voice_ref_text ?? null,
        voice_variants: draft.voice_variants ?? null,
        avatar_url: draft.avatar_url ?? null,
        avatar_variants: draft.avatar_variants ?? null,
        reset_stats: true,
      });
      await onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "选择角色失败");
      setPicking(null);
    }
  }

  async function pickProtagonist(draft: CharDraft) {
    setPicking(-4);
    setError(null);
    try {
      await api.updateMeCard(roomId, {
        character_name: draft.name,
        persona: draft.persona,
        appearance: draft.appearance ?? null,
        voice_id: draft.voice_id ?? null,
        voice_ref_url: draft.voice_ref_url ?? null,
        voice_ref_text: draft.voice_ref_text ?? null,
        voice_variants: draft.voice_variants ?? null,
        avatar_url: draft.avatar_url ?? null,
        avatar_variants: draft.avatar_variants ?? null,
        reset_stats: true,
      });
      await onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "选择角色失败");
      setPicking(null);
    }
  }

  async function pickPreset(npc: NpcCard) {
    setPicking(-2);
    setError(null);
    try {
      await api.updateMeCard(roomId, {
        character_name: npc.name,
        persona: npc.persona,
        appearance: npc.appearance ?? null,
        voice_id: npc.voice_id ?? null,
        voice_ref_url: npc.voice_ref_url ?? null,
        voice_ref_text: npc.voice_ref_text ?? null,
        voice_variants: npc.voice_variants ?? null,
        avatar_url: npc.avatar_url ?? null,
        avatar_variants: npc.avatar_variants ?? null,
        reset_stats: true,
      });
      await api.setNpcActive(roomId, npc.id, false);
      await onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "选择角色失败");
      setPicking(null);
    }
  }

  async function pickLibraryCard(card: UserCharacterCard) {
    setPicking(-3);
    setError(null);
    try {
      await api.updateMeCard(roomId, {
        character_name: card.name,
        persona: card.persona,
        appearance: card.appearance ?? null,
        voice_id: card.voice_id ?? null,
        voice_ref_url: card.voice_ref_url ?? null,
        voice_ref_text: card.voice_ref_text ?? null,
        voice_variants: card.voice_variants ?? null,
        avatar_url: card.avatar_url ?? null,
        avatar_variants: card.avatar_variants ?? null,
        reset_stats: true,
      });
      await onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "读取账号角色失败");
      setPicking(null);
    }
  }

  function submitHint(e: React.FormEvent) {
    e.preventDefault();
    if (!hint.trim()) return;
    setPicking(null);
    setError(null);
    const namePart = customName.trim() ? `角色名倾向：${customName.trim()}。` : "";
    void fetchOptions({ count: 3, hint: `${namePart}${hint.trim()}` });
  }

  const slots = loading
    ? [
        ...drafts,
        ...Array.from(
          { length: Math.max(0, expectedCount - drafts.length) },
          () => null,
        ),
      ]
    : drafts;

  return (
    <div className="char-select-overlay" role="dialog" aria-modal="true">
      <div className="char-select-box">
        <header className="char-select-head">
          <div>
            <h2>选择你的角色</h2>
            <p className="muted">
              可以直接扮演世界角色，也可以稍后再让 AI 生成带立绘的原创候选。
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
            {MEDIA_GENERATION_ENABLED
              ? "✨ 正在生成角色与立绘…（较慢，约需 1–2 分钟，请稍候）"
              : "✨ 正在生成角色草稿…（生图已关闭，可直接选择文字角色卡）"}
          </p>
        )}

        {libraryCards.length > 0 && (
          <section className="char-select-section">
            <div className="char-select-section-head">
              <h3>账号角色库</h3>
              <span className="muted">跨房间和世界卡永久保存</span>
            </div>
            <div
              className={`char-select-grid ${
                MEDIA_GENERATION_ENABLED ? "" : "text-only"
              }`}
            >
              {libraryCards.map((card) => (
                <div className="char-card" key={card.id}>
                  {MEDIA_GENERATION_ENABLED && (
                    <div className="char-card-portrait">
                      {card.avatar_url ? (
                        <img
                          src={assetUrl(card.avatar_url)}
                          alt={card.name}
                          loading="lazy"
                        />
                      ) : (
                        <div className="char-card-noart muted">（暂无立绘）</div>
                      )}
                    </div>
                  )}
                  <div className="char-card-body">
                    <div className="char-card-name">
                      {card.name}
                      <span className="tag">账号卡</span>
                    </div>
                    <div className="char-card-persona muted">{card.persona}</div>
                    <button
                      className="btn btn-primary btn-block"
                      disabled={picking !== null}
                      onClick={() => void pickLibraryCard(card)}
                    >
                      {picking === -3 ? (
                        <>
                          <span className="spinner" />
                          读取中…
                        </>
                      ) : (
                        "读取此角色"
                      )}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {protagonist && (
          <section className="char-select-section">
            <div className="char-select-section-head">
              <h3>原作主角</h3>
              <span className="muted">该世界卡的默认主角</span>
            </div>
            <div
              className={`char-select-grid ${
                MEDIA_GENERATION_ENABLED ? "" : "text-only"
              }`}
            >
              <div className="char-card char-card-accent">
                {MEDIA_GENERATION_ENABLED && (
                  <div className="char-card-portrait">
                    {protagonist.avatar_url ? (
                      <img
                        src={assetUrl(protagonist.avatar_url)}
                        alt={protagonist.name}
                        loading="lazy"
                      />
                    ) : (
                      <div className="char-card-noart muted">（暂无默认立绘）</div>
                    )}
                  </div>
                )}
                <div className="char-card-body">
                  <div className="char-card-name">
                    {protagonist.name}
                    <span className="tag tag-accent">主角</span>
                  </div>
                  <div className="char-card-persona muted">
                    {protagonist.persona}
                  </div>
                  <button
                    className="btn btn-primary btn-block"
                    disabled={picking !== null}
                    onClick={() => void pickProtagonist(protagonist)}
                  >
                    {picking === -4 ? (
                      <>
                        <span className="spinner" />
                        进场中…
                      </>
                    ) : (
                      "扮演她"
                    )}
                  </button>
                </div>
              </div>
            </div>
          </section>
        )}

        {presetCharacters.length > 0 && (
          <section className="char-select-section">
            <div className="char-select-section-head">
              <h3>世界角色</h3>
              <span className="muted">
                来自当前世界卡的重要 NPC · 共 {presetCharacters.length} 个
              </span>
            </div>
            <div
              className={`char-select-grid ${
                MEDIA_GENERATION_ENABLED ? "" : "text-only"
              }`}
            >
              {presetCharacters.map((npc) => (
                <div className="char-card" key={npc.id}>
                  {MEDIA_GENERATION_ENABLED && (
                    <div className="char-card-portrait">
                      {npc.avatar_url ? (
                        <img
                          src={assetUrl(npc.avatar_url)}
                          alt={npc.name}
                          loading="lazy"
                        />
                      ) : (
                        <div className="char-card-noart muted">（暂无默认立绘）</div>
                      )}
                    </div>
                  )}
                  <div className="char-card-body">
                    <div className="char-card-name">
                      {npc.name}
                      <span className="tag">世界角色</span>
                    </div>
                    <div className="char-card-persona muted">{npc.persona}</div>
                    <button
                      className="btn btn-primary btn-block"
                      disabled={picking !== null}
                      onClick={() => void pickPreset(npc)}
                    >
                      {picking === -2 ? (
                        <>
                          <span className="spinner" />
                          进场中…
                        </>
                      ) : (
                        "扮演 TA"
                      )}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <section className="char-select-section">
          <div className="char-select-section-head">
            <h3>原创角色</h3>
            <span className="muted">按需生成，带立绘会比较慢</span>
          </div>
          {loading || drafts.length > 0 ? (
            <div
              className={`char-select-grid ${
                MEDIA_GENERATION_ENABLED ? "" : "text-only"
              }`}
            >
              {slots.map((draft, i) => (
                <div className="char-card" key={draft ? `${draft.name}-${i}` : i}>
                  {MEDIA_GENERATION_ENABLED && (
                    <div className="char-card-portrait">
                      {draft?.avatar_url ? (
                        <img
                          src={assetUrl(draft.avatar_url)}
                          alt={draft.name}
                          loading="lazy"
                        />
                      ) : draft ? (
                        <div className="char-card-noart muted">（暂无立绘）</div>
                      ) : (
                        <div className="char-card-skeleton">
                          <span className="spinner spinner-dark" />
                        </div>
                      )}
                    </div>
                  )}
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
                          "选 TA"
                        )}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="char-select-empty muted">
              还没有原创候选。点击「AI 发散一批」时才会开始生成角色和立绘。
            </div>
          )}
        </section>

        {mode === "describe" ? (
          <form className="char-select-describe" onSubmit={submitHint}>
            <input
              className="input"
              placeholder="角色名，例如：莉娜"
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              autoFocus
              disabled={picking !== null || loading}
            />
            <input
              className="input"
              placeholder="角色描述，例如：一名失忆的流浪剑士，沉默寡言"
              value={hint}
              onChange={(e) => setHint(e.target.value)}
              disabled={picking !== null || loading}
            />
            <button
              className="btn btn-primary"
              disabled={picking !== null || loading || !hint.trim()}
            >
              {loading ? (
                <>
                  <span className="spinner" />
                  生成候选中…
                </>
              ) : (
                "生成 3 个候选"
              )}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setMode("browse")}
              disabled={picking !== null || loading}
            >
              取消
            </button>
          </form>
        ) : (
          <div className="char-select-actions">
            <button
              className="btn"
              onClick={() => void fetchOptions({ count: 3 })}
              disabled={loading || picking !== null}
            >
              {loading ? (
                <>
                  <span className="spinner spinner-dark" />
                  AI 发散中…
                </>
              ) : (
                "🎲 AI 随机生成"
              )}
            </button>
            <button
              className="btn"
              onClick={() => {
                reqId.current += 1;
                setLoading(false);
                setMode("describe");
              }}
              disabled={picking !== null}
            >
              ✍️ 按描述生成
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
