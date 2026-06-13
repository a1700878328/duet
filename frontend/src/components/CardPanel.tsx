import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { MemberCard, NpcCard } from "../lib/types";
import { CardEditor, type CardDraft } from "./CardEditor";

interface Props {
  roomId: string;
  myUserId: string | undefined;
  open: boolean;
  onClose: () => void;
  // Make the given NPC react in the timeline (advance with npc_id).
  onNpcSpeak: (npcId: number) => void;
  onError?: (msg: string) => void;
  // Disable speak actions while an AI turn is in flight.
  aiBusy?: boolean;
}

const EMPTY_DRAFT: CardDraft = {
  name: "",
  persona: "",
  appearance: "",
  voice_id: "",
};

// Editing target: my member card, an existing NPC, or a new NPC.
type EditTarget =
  | { kind: "me" }
  | { kind: "npc"; npc: NpcCard }
  | { kind: "new" }
  | null;

export function CardPanel({
  roomId,
  myUserId,
  open,
  onClose,
  onNpcSpeak,
  onError,
  aiBusy = false,
}: Props) {
  const [players, setPlayers] = useState<MemberCard[]>([]);
  const [npcs, setNpcs] = useState<NpcCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [editing, setEditing] = useState<EditTarget>(null);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genCount, setGenCount] = useState(4);
  const [genHint, setGenHint] = useState("");

  const fail = useCallback(
    (err: unknown, fallback: string) => {
      const msg = err instanceof ApiError ? err.message : fallback;
      onError?.(msg);
    },
    [onError],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const cards = await api.getCards(roomId);
      setPlayers(cards.players);
      setNpcs(cards.npcs);
      setLoaded(true);
    } catch (err) {
      fail(err, "加载角色卡失败");
    } finally {
      setLoading(false);
    }
  }, [roomId, fail]);

  // Load cards when the panel opens (first time / each open keeps fresh).
  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  const myCard = players.find((p) => String(p.user_id) === String(myUserId));

  async function saveMe(draft: CardDraft) {
    setSaving(true);
    try {
      await api.updateMeCard(roomId, {
        character_name: draft.name,
        persona: draft.persona,
        appearance: draft.appearance || null,
        voice_id: draft.voice_id || null,
      });
      setEditing(null);
      await refresh();
    } catch (err) {
      fail(err, "保存我的角色卡失败");
    } finally {
      setSaving(false);
    }
  }

  async function saveNpc(npcId: number, draft: CardDraft) {
    setSaving(true);
    try {
      await api.updateNpc(roomId, npcId, {
        name: draft.name,
        persona: draft.persona,
        appearance: draft.appearance || null,
        voice_id: draft.voice_id || null,
      });
      setEditing(null);
      await refresh();
    } catch (err) {
      fail(err, "保存 NPC 失败");
    } finally {
      setSaving(false);
    }
  }

  async function createNpc(draft: CardDraft) {
    setSaving(true);
    try {
      await api.createNpc(roomId, {
        name: draft.name,
        persona: draft.persona,
        appearance: draft.appearance || null,
        voice_id: draft.voice_id || null,
      });
      setEditing(null);
      await refresh();
    } catch (err) {
      fail(err, "创建 NPC 失败");
    } finally {
      setSaving(false);
    }
  }

  async function removeNpc(npc: NpcCard) {
    if (!window.confirm(`删除 NPC「${npc.name}」？此操作无法撤销。`)) return;
    try {
      await api.deleteNpc(roomId, npc.id);
      if (editing?.kind === "npc" && editing.npc.id === npc.id) setEditing(null);
      await refresh();
    } catch (err) {
      fail(err, "删除 NPC 失败");
    }
  }

  async function generate() {
    setGenerating(true);
    try {
      await api.generateNpcs(roomId, {
        count: genCount,
        hint: genHint.trim() || undefined,
      });
      setGenHint("");
      await refresh();
    } catch (err) {
      fail(err, "AI 生成 NPC 失败");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <>
      <div
        className={`card-panel-backdrop ${open ? "open" : ""}`}
        onClick={onClose}
        aria-hidden
      />
      <aside className={`card-panel ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="card-panel-head">
          <h3>🎭 角色与登场 NPC</h3>
          <button
            className="btn btn-ghost card-panel-close"
            onClick={onClose}
            aria-label="关闭"
          >
            ✕
          </button>
        </div>

        <div className="card-panel-body">
          {loading && !loaded && (
            <div className="empty">加载角色卡中…</div>
          )}

          {/* ---- 我的角色卡 ---- */}
          <section className="card-section">
            <div className="card-section-head">
              <h4>我的角色卡</h4>
              {myCard && editing?.kind !== "me" && (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setEditing({ kind: "me" })}
                >
                  编辑
                </button>
              )}
            </div>

            {editing?.kind === "me" && myCard ? (
              <CardEditor
                title="编辑我的角色卡"
                nameLabel="角色名"
                initial={{
                  name: myCard.character_name ?? "",
                  persona: myCard.persona ?? "",
                  appearance: myCard.appearance ?? "",
                  voice_id: myCard.voice_id ?? "",
                }}
                saving={saving}
                onSubmit={saveMe}
                onCancel={() => setEditing(null)}
              />
            ) : myCard ? (
              <div className="card-row">
                <div className="card-row-main">
                  <div className="card-row-name">{myCard.character_name}</div>
                  <div className="card-row-sub muted">
                    {myCard.persona || "（还没有人设，点编辑补充）"}
                  </div>
                </div>
              </div>
            ) : (
              loaded && <div className="muted">未找到你的角色卡。</div>
            )}
          </section>

          {/* ---- 登场 NPC ---- */}
          <section className="card-section">
            <div className="card-section-head">
              <h4>登场 NPC（{npcs.length}）</h4>
            </div>

            {loaded && npcs.length === 0 && editing?.kind !== "new" && (
              <div className="muted card-empty-npc">
                还没有 NPC。让 AI 生成几个，或手动添加。
              </div>
            )}

            <div className="npc-list">
              {npcs.map((npc) =>
                editing?.kind === "npc" && editing.npc.id === npc.id ? (
                  <CardEditor
                    key={npc.id}
                    title={`编辑 NPC「${npc.name}」`}
                    initial={{
                      name: npc.name,
                      persona: npc.persona,
                      appearance: npc.appearance ?? "",
                      voice_id: npc.voice_id ?? "",
                    }}
                    saving={saving}
                    onSubmit={(d) => saveNpc(npc.id, d)}
                    onCancel={() => setEditing(null)}
                  />
                ) : (
                  <div className="card-row npc-row" key={npc.id}>
                    <div className="card-row-main">
                      <div className="card-row-name">
                        {npc.name}
                        {npc.created_by_ai && (
                          <span className="tag npc-ai-tag">✨AI</span>
                        )}
                      </div>
                      <div className="card-row-sub muted">{npc.persona}</div>
                    </div>
                    <div className="npc-actions">
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => onNpcSpeak(npc.id)}
                        disabled={aiBusy}
                        title="让这个 NPC 在时间线里接话"
                      >
                        让 TA 接话
                      </button>
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => setEditing({ kind: "npc", npc })}
                      >
                        编辑
                      </button>
                      <button
                        className="btn btn-ghost btn-sm btn-danger"
                        onClick={() => removeNpc(npc)}
                      >
                        删除
                      </button>
                    </div>
                  </div>
                ),
              )}
            </div>

            {editing?.kind === "new" ? (
              <CardEditor
                title="手建 NPC"
                submitLabel="创建"
                initial={EMPTY_DRAFT}
                saving={saving}
                onSubmit={createNpc}
                onCancel={() => setEditing(null)}
              />
            ) : (
              <button
                className="btn btn-block npc-add-btn"
                onClick={() => setEditing({ kind: "new" })}
              >
                ➕ 手建 NPC
              </button>
            )}
          </section>

          {/* ---- AI 生成 NPC ---- */}
          <section className="card-section">
            <div className="card-section-head">
              <h4>✨ AI 生成 NPC</h4>
            </div>
            <div className="gen-controls">
              <label className="field gen-count-field">
                <span>数量</span>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={6}
                  value={genCount}
                  onChange={(e) =>
                    setGenCount(
                      Math.max(1, Math.min(6, Number(e.target.value) || 1)),
                    )
                  }
                  disabled={generating}
                />
              </label>
              <label className="field gen-hint-field">
                <span>提示（可选）</span>
                <input
                  className="input"
                  value={genHint}
                  onChange={(e) => setGenHint(e.target.value)}
                  placeholder="例如：酒馆里的常客"
                  disabled={generating}
                />
              </label>
            </div>
            <button
              className="btn btn-primary btn-block"
              onClick={generate}
              disabled={generating}
            >
              {generating ? (
                <>
                  <span className="spinner" />
                  AI 生成中…（约 10–25 秒）
                </>
              ) : (
                "✨ 从世界观生成 NPC"
              )}
            </button>
          </section>
        </div>
      </aside>
    </>
  );
}
