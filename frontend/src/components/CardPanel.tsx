import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, assetUrl } from "../lib/api";
import { MEDIA_GENERATION_ENABLED, VOICE_GENERATION_ENABLED } from "../lib/features";
import type {
  AvatarVariant,
  MemberCard,
  NpcCard,
  RoomCards,
  UserCharacterCard,
  VoiceVariant,
} from "../lib/types";
import { CardEditor, type CardDraft } from "./CardEditor";
import type { ProfileView } from "./RoomOverlays";

interface Props {
  roomId: string;
  myUserId: string | undefined;
  open: boolean;
  onClose: () => void;
  // Make the given NPC react in the timeline (advance with npc_id).
  onNpcSpeak: (npcId: number) => void;
  onGodWhisper?: (params: { target_npc: string; scene?: string; action: string }) => void;
  onError?: (msg: string) => void;
  // Disable speak actions while an AI turn is in flight.
  aiBusy?: boolean;
  // Cards are owned by RoomPage so bubbles + panel share one source.
  cards: RoomCards | null;
  onRefresh: () => Promise<void> | void;
  onOpenProfile?: (profile: ProfileView) => void;
  onOpenCharacterSelect?: () => void;
  currentScene?: string;
  sceneOptions?: string[];
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

// A portrait thumbnail that opens the same in-page profile modal as chat avatars.
function AvatarThumb({
  url,
  alt,
  onClick,
}: {
  url: string;
  alt: string;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      className="card-avatar-thumb"
      onClick={onClick}
      title="查看角色资料"
    >
      <img src={assetUrl(url)} alt={alt} loading="lazy" />
    </button>
  );
}

function AvatarVariantStrip({
  variants,
  currentUrl,
  busyUrl,
  onSelect,
}: {
  variants?: AvatarVariant[] | null;
  currentUrl?: string | null;
  busyUrl?: string | null;
  onSelect: (url: string) => void;
}) {
  const items = (variants ?? []).filter((v) => v.url);
  if (items.length <= 1) return null;
  return (
    <div className="avatar-variant-strip">
      {items.map((variant) => {
        const active = variant.url === currentUrl;
        const busy = variant.url === busyUrl;
        return (
          <button
            type="button"
            key={variant.url}
            className={`avatar-variant ${active ? "active" : ""}`}
            disabled={active || busy}
            onClick={() => onSelect(variant.url)}
            title={variant.label || "切换头像"}
          >
            {busy ? (
              <span className="spinner spinner-dark" />
            ) : (
              <img src={assetUrl(variant.url)} alt={variant.label || "头像"} />
            )}
          </button>
        );
      })}
    </div>
  );
}

function VoiceVariantStrip({
  variants,
  currentUrl,
  busyUrl,
  onSelect,
  onPreview,
}: {
  variants?: VoiceVariant[] | null;
  currentUrl?: string | null;
  busyUrl?: string | null;
  onSelect: (url: string) => void;
  onPreview: (url: string) => void;
}) {
  const items = (variants ?? []).filter((v) => v.url);
  if (items.length <= 1) return null;
  return (
    <div className="voice-variant-strip">
      {items.map((variant, idx) => {
        const active = variant.url === currentUrl;
        const busy = variant.url === busyUrl;
        const label = variant.label || `语音${idx + 1}`;
        return (
          <div
            className={`voice-variant ${active ? "active" : ""}`}
            key={variant.url}
            title={variant.text || label}
          >
            <button
              type="button"
              className="voice-variant-select"
              disabled={active || busy}
              onClick={() => onSelect(variant.url)}
            >
              {busy ? <span className="spinner spinner-dark" /> : label}
            </button>
            <button
              type="button"
              className="voice-variant-play"
              onClick={() => onPreview(variant.url)}
              aria-label={`试听${label}`}
            >
              ▶
            </button>
          </div>
        );
      })}
    </div>
  );
}

export function CardPanel({
  roomId,
  myUserId,
  open,
  onClose,
  onNpcSpeak,
  onGodWhisper,
  onError,
  aiBusy = false,
  cards,
  onRefresh,
  onOpenProfile,
  onOpenCharacterSelect,
  currentScene,
}: Props) {
  const players = cards?.players ?? [];
  const npcs = cards?.npcs ?? [];
  const loaded = cards !== null;
  const currentSceneNpcs = npcs.filter(
    (n) => n.name !== "上帝" && (!n.scene || n.scene === (currentScene || ""))
  );

  const [editing, setEditing] = useState<EditTarget>(null);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genCount, setGenCount] = useState(4);
  const [genHint, setGenHint] = useState("");
  // Per-target avatar-generation in flight (key "me" or npc id), + active toggles.
  const [avatarBusy, setAvatarBusy] = useState<Set<string>>(new Set());
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [npcVoiceBusy, setNpcVoiceBusy] = useState<Set<number>>(new Set());
  const [activeBusy, setActiveBusy] = useState<Set<number>>(new Set());
  const [libraryCards, setLibraryCards] = useState<UserCharacterCard[]>([]);
  const [libraryBusy, setLibraryBusy] = useState(false);
  const [savingLibrary, setSavingLibrary] = useState(false);
  const [avatarSelectBusy, setAvatarSelectBusy] = useState<string | null>(null);
  const [voiceSelectBusy, setVoiceSelectBusy] = useState<string | null>(null);
  const [myCardOverride, setMyCardOverride] = useState<MemberCard | null>(null);
  const [godModalOpen, setGodModalOpen] = useState(false);
  const [godTargetNpc, setGodTargetNpc] = useState("");
  const [godAction, setGodAction] = useState("");
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const previewStopRef = useRef<number | null>(null);

  const fail = useCallback(
    (err: unknown, fallback: string) => {
      const msg = err instanceof ApiError ? err.message : fallback;
      onError?.(msg);
    },
    [onError],
  );

  const refresh = useCallback(async () => {
    await onRefresh();
  }, [onRefresh]);

  const refreshLibrary = useCallback(async () => {
    setLibraryBusy(true);
    try {
      setLibraryCards(await api.listMyCharacterCards());
    } catch (err) {
      fail(err, "读取账号角色库失败");
    } finally {
      setLibraryBusy(false);
    }
  }, [fail]);

  // Refresh when the panel opens to keep cards fresh.
  useEffect(() => {
    if (open) {
      void refresh();
      void refreshLibrary();
    }
  }, [open, refresh, refreshLibrary]);

  const myCardFromCards = players.find((p) => String(p.user_id) === String(myUserId));
  const myCard =
    myCardOverride && String(myCardOverride.user_id) === String(myUserId)
      ? myCardOverride
      : myCardFromCards;
  const otherPlayers = players.filter(
    (p) => String(p.user_id) !== String(myUserId),
  );

  useEffect(() => {
    setMyCardOverride(null);
  }, [
    roomId,
    myUserId,
    myCardFromCards?.character_name,
    myCardFromCards?.persona,
    myCardFromCards?.appearance,
  ]);

  function setBusy<T>(
    setter: React.Dispatch<React.SetStateAction<Set<T>>>,
    key: T,
    on: boolean,
  ) {
    setter((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  async function saveMe(draft: CardDraft) {
    setSaving(true);
    try {
      const updated = await api.updateMeCard(roomId, {
        character_name: draft.name,
        persona: draft.persona,
        appearance: draft.appearance || null,
        voice_id: draft.voice_id || null,
      });
      setMyCardOverride(updated);
      setEditing(null);
      await refresh();
    } catch (err) {
      fail(err, "保存我的角色卡失败");
    } finally {
      setSaving(false);
    }
  }

  function libraryBodyFromMember(card: MemberCard) {
    return {
      name: card.character_name,
      persona: card.persona ?? "",
      appearance: card.appearance ?? null,
      voice_id: card.voice_id ?? null,
      voice_ref_url: card.voice_ref_url ?? null,
      voice_ref_text: card.voice_ref_text ?? null,
      voice_variants: card.voice_variants ?? null,
      avatar_url: card.avatar_url ?? null,
      avatar_variants: card.avatar_variants ?? null,
    };
  }

  async function saveMyCardToLibrary() {
    if (!myCard) return;
    setSavingLibrary(true);
    try {
      const sameName = libraryCards.find((c) => c.name === myCard.character_name);
      const body = libraryBodyFromMember(myCard);
      if (
        sameName &&
        window.confirm(`账号角色库里已有「${sameName.name}」。要覆盖它吗？`)
      ) {
        await api.updateMyCharacterCard(sameName.id, body);
      } else {
        await api.createMyCharacterCard(body);
      }
      await refreshLibrary();
    } catch (err) {
      fail(err, "保存到账号角色库失败");
    } finally {
      setSavingLibrary(false);
    }
  }

  async function applyLibraryCard(card: UserCharacterCard) {
    setLibraryBusy(true);
    try {
      const updated = await api.updateMeCard(roomId, {
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
      setMyCardOverride(updated);
      await refresh();
    } catch (err) {
      fail(err, "读取账号角色失败");
    } finally {
      setLibraryBusy(false);
    }
  }

  async function deleteLibraryCard(card: UserCharacterCard) {
    if (!window.confirm(`从账号角色库删除「${card.name}」？`)) return;
    setLibraryBusy(true);
    try {
      await api.deleteMyCharacterCard(card.id);
      await refreshLibrary();
    } catch (err) {
      fail(err, "删除账号角色失败");
    } finally {
      setLibraryBusy(false);
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

  async function genMyAvatar() {
    setBusy<string>(setAvatarBusy, "me", true);
    try {
      const updated = await api.generateMyAvatar(roomId);
      setMyCardOverride(updated);
      await refresh();
    } catch (err) {
      fail(err, "生成头像失败");
    } finally {
      setBusy<string>(setAvatarBusy, "me", false);
    }
  }

  async function selectMyAvatar(url: string) {
    setAvatarSelectBusy(`me:${url}`);
    try {
      const updated = await api.selectMyAvatar(roomId, url);
      setMyCardOverride(updated);
      await refresh();
    } catch (err) {
      fail(err, "切换头像失败");
    } finally {
      setAvatarSelectBusy(null);
    }
  }

  async function genMyVoice() {
    setVoiceBusy(true);
    try {
      const updated = await api.generateMyVoice(roomId);
      setMyCardOverride(updated);
      await refresh();
    } catch (err) {
      fail(err, "设定我的角色语音失败");
    } finally {
      setVoiceBusy(false);
    }
  }

  async function selectMyVoice(url: string) {
    setVoiceSelectBusy(`me:${url}`);
    try {
      const updated = await api.selectMyVoice(roomId, url);
      setMyCardOverride(updated);
      await refresh();
    } catch (err) {
      fail(err, "切换角色语音失败");
    } finally {
      setVoiceSelectBusy(null);
    }
  }

  function previewVoice(url?: string | null) {
    if (!url) return;
    if (previewStopRef.current !== null) {
      window.clearTimeout(previewStopRef.current);
      previewStopRef.current = null;
    }
    previewAudioRef.current?.pause();

    const audio = new Audio(assetUrl(url));
    previewAudioRef.current = audio;
    const clipSeconds = 8;
    const playClip = () => {
      const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
      if (duration > clipSeconds + 1) {
        audio.currentTime = Math.random() * Math.max(0, duration - clipSeconds);
      }
      void audio
        .play()
        .then(() => {
          previewStopRef.current = window.setTimeout(() => {
            audio.pause();
            previewStopRef.current = null;
          }, clipSeconds * 1000);
        })
        .catch(() => {
          onError?.("试听角色语音失败");
        });
    };

    audio.addEventListener("loadedmetadata", playClip, { once: true });
    audio.addEventListener(
      "error",
      () => {
        onError?.("试听角色语音失败");
      },
      { once: true },
    );
  }

  async function genNpcAvatar(npc: NpcCard) {
    const key = String(npc.id);
    setBusy(setAvatarBusy, key, true);
    try {
      await api.generateNpcAvatar(roomId, npc.id);
      await refresh();
    } catch (err) {
      fail(err, "生成头像失败");
    } finally {
      setBusy(setAvatarBusy, key, false);
    }
  }

  async function selectNpcAvatar(npc: NpcCard, url: string) {
    setAvatarSelectBusy(`npc:${npc.id}:${url}`);
    try {
      await api.selectNpcAvatar(roomId, npc.id, url);
      await refresh();
    } catch (err) {
      fail(err, "切换头像失败");
    } finally {
      setAvatarSelectBusy(null);
    }
  }

  async function genNpcVoice(npc: NpcCard) {
    setBusy(setNpcVoiceBusy, npc.id, true);
    try {
      await api.generateNpcVoice(roomId, npc.id);
      await refresh();
    } catch (err) {
      fail(err, "设定角色语音失败");
    } finally {
      setBusy(setNpcVoiceBusy, npc.id, false);
    }
  }

  async function evolveNpc(npc: NpcCard) {
    try {
      await api.evolveNpc(roomId, npc.id);
      await refresh();
    } catch (err) {
      fail(err, "角色进化失败");
    }
  }

  async function evolveMyCard(personaAdd: string) {
    try {
      await api.evolveMyCard(roomId, personaAdd);
      await refresh();
    } catch (err) {
      fail(err, "角色进化失败");
    }
  }

  async function selectNpcVoice(npc: NpcCard, url: string) {
    setVoiceSelectBusy(`npc:${npc.id}:${url}`);
    try {
      await api.selectNpcVoice(roomId, npc.id, url);
      await refresh();
    } catch (err) {
      fail(err, "切换角色语音失败");
    } finally {
      setVoiceSelectBusy(null);
    }
  }

  async function toggleActive(npc: NpcCard) {
    setBusy(setActiveBusy, npc.id, true);
    try {
      await api.setNpcActive(roomId, npc.id, !npc.active);
      await refresh();
    } catch (err) {
      fail(err, "切换 NPC 状态失败");
    } finally {
      setBusy(setActiveBusy, npc.id, false);
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

  const myAvatarBusy = avatarBusy.has("me");

  function closePanel() {
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
    onClose();
  }

  return (
    <>
      <div
        className={`card-panel-backdrop ${open ? "open" : ""}`}
        onClick={closePanel}
        aria-hidden
      />
      <aside className={`card-panel ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="card-panel-head">
          <h3>🎭 角色与登场 NPC</h3>
          <button
            className="btn btn-ghost card-panel-close"
            onClick={closePanel}
            aria-label="关闭"
          >
            ✕
          </button>
        </div>

        <div className="card-panel-body">
          {!loaded && <div className="empty">加载角色卡中…</div>}

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
                {myCard.avatar_url && (
                  <AvatarThumb
                    url={myCard.avatar_url}
                    alt={myCard.character_name}
                    onClick={() =>
                      onOpenProfile?.({
                        kind: "player",
                        name: myCard.character_name,
                        avatarUrl: myCard.avatar_url,
                        appearance: myCard.appearance,
                        persona: myCard.persona,
                        stats: myCard.stats ?? null,
                      })
                    }
                  />
                )}
                <div className="card-row-main">
                  <div className="card-row-name">{myCard.character_name}</div>
                  <div className="card-row-sub muted">
                    {myCard.persona || "（还没有人设，点编辑补充）"}
                  </div>
                  <div className="card-row-actions">
                    {MEDIA_GENERATION_ENABLED && (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={genMyAvatar}
                        disabled={myAvatarBusy}
                        title="根据外貌描述生成头像（约 30–60 秒）"
                      >
                        {myAvatarBusy ? (
                          <>
                            <span className="spinner spinner-dark" />
                            生成头像中…
                          </>
                        ) : myCard.avatar_url ? (
                          "🎨 重新生成头像"
                        ) : (
                          "🎨 生成头像"
                        )}
                      </button>
                    )}
                    {(
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => {
                          const add = window.prompt(
                            `追加角色人设：\n当前：${(myCard.persona || "").slice(0, 100)}…`
                          );
                          if (add?.trim()) evolveMyCard(add.trim());
                        }}
                        title="追加人设→AI调外貌→重生头像"
                      >
                        🌱 进化
                      </button>
                    )}
                    {VOICE_GENERATION_ENABLED && (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={genMyVoice}
                        disabled={voiceBusy}
                        title="根据当前角色卡设定日漫风格角色语音"
                      >
                        {voiceBusy ? (
                          <>
                            <span className="spinner spinner-dark" />
                            设定语音中…
                          </>
                        ) : myCard.voice_id ? (
                          "🔁 重生语音"
                        ) : (
                          "🎙️ 设定角色语音"
                        )}
                      </button>
                    )}
                    {VOICE_GENERATION_ENABLED && myCard.voice_ref_url && (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => previewVoice(myCard.voice_ref_url)}
                        title="试听当前角色语音"
                      >
                        ▶ 试听语音
                      </button>
                    )}
                    {onOpenCharacterSelect && (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={onOpenCharacterSelect}
                        title="重新打开 AI 选角，生成并选择完整角色卡"
                      >
                        ✨ AI 选角
                      </button>
                    )}
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={saveMyCardToLibrary}
                      disabled={savingLibrary}
                      title="把当前角色卡永久保存到账号，可在其他房间读取"
                    >
                      {savingLibrary ? (
                        <>
                          <span className="spinner spinner-dark" />
                          保存中…
                        </>
                      ) : (
                        "保存到账号"
                      )}
                    </button>
                  </div>
                  <AvatarVariantStrip
                    variants={myCard.avatar_variants}
                    currentUrl={myCard.avatar_url}
                    busyUrl={
                      avatarSelectBusy?.startsWith("me:")
                        ? avatarSelectBusy.slice(3)
                        : null
                    }
                    onSelect={(url) => void selectMyAvatar(url)}
                  />
                  <VoiceVariantStrip
                    variants={myCard.voice_variants}
                    currentUrl={myCard.voice_ref_url}
                    busyUrl={
                      voiceSelectBusy?.startsWith("me:")
                        ? voiceSelectBusy.slice(3)
                        : null
                    }
                    onSelect={(url) => void selectMyVoice(url)}
                    onPreview={previewVoice}
                  />
                </div>
              </div>
            ) : (
              loaded && <div className="muted">未找到你的角色卡。</div>
            )}
          </section>

          <section className="card-section">
            <div className="card-section-head">
              <h4>账号角色库</h4>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => void refreshLibrary()}
                disabled={libraryBusy}
              >
                刷新
              </button>
            </div>
            {libraryBusy && libraryCards.length === 0 ? (
              <div className="empty">读取账号角色库中…</div>
            ) : libraryCards.length === 0 ? (
              <div className="muted">
                还没有保存的账号角色。把当前角色保存后，就能在其他房间读取。
              </div>
            ) : (
              <div className="player-list">
                {libraryCards.map((card) => (
                  <div className="card-row" key={card.id}>
                    {card.avatar_url && (
                      <AvatarThumb url={card.avatar_url} alt={card.name} />
                    )}
                    <div className="card-row-main">
                      <div className="card-row-name">
                        {card.name}
                        <span className="tag">账号卡</span>
                      </div>
                      <div className="card-row-sub muted">{card.persona}</div>
                      <div className="card-row-actions">
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => void applyLibraryCard(card)}
                          disabled={libraryBusy}
                        >
                          读取到本房间
                        </button>
                        <button
                          className="btn btn-ghost btn-sm btn-danger"
                          onClick={() => void deleteLibraryCard(card)}
                          disabled={libraryBusy}
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* ---- 其他玩家 ---- */}
          {otherPlayers.length > 0 && (
            <section className="card-section">
              <div className="card-section-head">
                <h4>其他玩家（{otherPlayers.length}）</h4>
              </div>
              <div className="player-list">
                {otherPlayers.map((player) => (
                  <div className="card-row" key={player.user_id}>
                    {player.avatar_url && (
                      <AvatarThumb
                        url={player.avatar_url}
                        alt={player.character_name}
                        onClick={() =>
                          onOpenProfile?.({
                            kind: "player",
                            name: player.character_name,
                            avatarUrl: player.avatar_url,
                            appearance: player.appearance,
                            persona: player.persona,
                            stats: player.stats ?? null,
                          })
                        }
                      />
                    )}
                    <div className="card-row-main">
                      <div className="card-row-name">
                        {player.character_name}
                        <span className="tag">玩家</span>
                      </div>
                      <div className="card-row-scene">
                        {player.display_name}
                      </div>
                      <div className="card-row-sub muted">
                        {player.persona || "（还没有人设）"}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

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
              {npcs.map((npc) => {
                const isGod = npc.id === 0 || npc.name === "上帝";
                const busyAvatar = avatarBusy.has(String(npc.id));
                const busyVoice = npcVoiceBusy.has(npc.id);
                const busyActive = activeBusy.has(npc.id);
                if (editing?.kind === "npc" && editing.npc.id === npc.id) {
                  return (
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
                  );
                }
                return (
                  <div
                    className={`card-row npc-row ${npc.active ? "" : "disabled"}`}
                    key={npc.id}
                  >
                    <div className="npc-row-top">
                      {npc.avatar_url && (
                        <AvatarThumb
                          url={npc.avatar_url}
                          alt={npc.name}
                          onClick={() =>
                            onOpenProfile?.({
                              kind: "npc",
                              id: npc.id,
                              name: npc.name,
                              avatarUrl: npc.avatar_url,
                              appearance: npc.appearance,
                              persona: npc.persona,
                              scene: npc.scene,
                              discovered: npc.discovered,
                            })
                          }
                        />
                      )}
                      <div className="card-row-main">
                        <div className="card-row-name">
                          {npc.name}
                          {npc.created_by_ai && (
                            <span className="tag npc-ai-tag">✨AI</span>
                          )}
                          {!npc.active && (
                            <span className="tag npc-off-tag">已关闭</span>
                          )}
                        </div>
                        <div className="card-row-sub muted">{npc.persona}</div>
                        {npc.scene && (
                          <div className="card-row-scene">📍 {npc.scene}</div>
                        )}
                        {npc.discovered && (
                          <div className="card-row-discovered">
                            <span className="discovered-label">📖 已了解</span>
                            {npc.discovered}
                          </div>
                        )}
                      </div>
                      <label
                        className="toggle npc-active-toggle"
                        title={
                          npc.active
                            ? "已启用：参与自动导演模拟。点击关闭。"
                            : "已关闭：不参与自动导演模拟。点击启用。"
                        }
                      >
                        <span
                          className={`switch ${npc.active ? "on" : ""} ${
                            busyActive ? "busy" : ""
                          }`}
                          onClick={() => !isGod && !busyActive && toggleActive(npc)}
                          role="switch"
                          aria-checked={npc.active}
                        />
                      </label>
                    </div>
                    <div className="npc-actions">
                      {isGod ? (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => setGodModalOpen(true)}
                          disabled={aiBusy}
                          title="私聊上帝，暗中强制影响当前场景 NPC 的行动"
                        >
                          私聊上帝
                        </button>
                      ) : (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => onNpcSpeak(npc.id)}
                          disabled={aiBusy || !npc.active}
                          title={
                            npc.active
                              ? "让这个 NPC 在时间线里接话"
                              : "已关闭的 NPC 不能接话"
                          }
                        >
                          让 TA 接话
                        </button>
                      )}
                      {MEDIA_GENERATION_ENABLED && !isGod && (
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => genNpcAvatar(npc)}
                          disabled={busyAvatar}
                          title="根据外貌描述生成头像（约 30–60 秒）"
                        >
                          {busyAvatar ? (
                            <>
                              <span className="spinner spinner-dark" />
                              头像生成中…
                            </>
                          ) : npc.avatar_url ? (
                            "🎨 重生头像"
                          ) : (
                            "🎨 头像"
                          )}
                        </button>
                      )}
                      {!isGod && (
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => evolveNpc(npc)}
                          title="根据当前人设自动调整外貌tag→重生头像"
                        >
                          🌱 进化
                        </button>
                      )}
                      {VOICE_GENERATION_ENABLED && !isGod && (
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => genNpcVoice(npc)}
                          disabled={busyVoice}
                          title="根据角色卡设定日漫风格角色语音"
                        >
                          {busyVoice ? (
                            <>
                              <span className="spinner spinner-dark" />
                              设定语音中…
                            </>
                          ) : npc.voice_ref_url ? (
                            "🔁 重生语音"
                          ) : (
                            "🎙️ 设定角色语音"
                          )}
                        </button>
                      )}
                      {VOICE_GENERATION_ENABLED && !isGod && npc.voice_ref_url && (
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => previewVoice(npc.voice_ref_url)}
                          title="试听当前角色语音"
                        >
                          ▶ 试听
                        </button>
                      )}
                      {!isGod && (
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => setEditing({ kind: "npc", npc })}
                        >
                          编辑
                        </button>
                      )}
                      {!isGod && (
                        <button
                          className="btn btn-ghost btn-sm btn-danger"
                          onClick={() => removeNpc(npc)}
                        >
                          删除
                        </button>
                      )}
                    </div>
                    <AvatarVariantStrip
                      variants={npc.avatar_variants}
                      currentUrl={npc.avatar_url}
                      busyUrl={
                        avatarSelectBusy?.startsWith(`npc:${npc.id}:`)
                          ? avatarSelectBusy.slice(`npc:${npc.id}:`.length)
                          : null
                      }
                      onSelect={(url) => void selectNpcAvatar(npc, url)}
                    />
                    <VoiceVariantStrip
                      variants={npc.voice_variants}
                      currentUrl={npc.voice_ref_url}
                      busyUrl={
                        voiceSelectBusy?.startsWith(`npc:${npc.id}:`)
                          ? voiceSelectBusy.slice(`npc:${npc.id}:`.length)
                          : null
                      }
                      onSelect={(url) => void selectNpcVoice(npc, url)}
                      onPreview={previewVoice}
                    />
                  </div>
                );
              })}
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

      {godModalOpen && (
        <div className="overlay-backdrop" onClick={() => setGodModalOpen(false)}>
          <div className="move-modal" onClick={(e) => e.stopPropagation()}>
            <h3>👁 上帝私聊</h3>
            <select
              className="input"
              value={godTargetNpc}
              onChange={(e) => setGodTargetNpc(e.target.value)}
            >
              <option value="">— 选择目标 NPC —</option>
              {currentSceneNpcs.map((n) => (
                <option key={n.id} value={n.name}>{n.name}</option>
              ))}
            </select>
            <label style={{ marginTop: 12 }}>让角色做什么</label>
            <input
              type="text"
              className="input"
              placeholder="如：干我、跟我走、命令他…"
              value={godAction}
              onChange={(e) => setGodAction(e.target.value)}
              autoFocus
            />
            <div className="move-actions">
              <button
                className="btn btn-primary btn-sm"
                disabled={aiBusy || !godTargetNpc || !godAction.trim()}
                onClick={() => {
                  onGodWhisper?.({
                    target_npc: godTargetNpc,
                    action: godAction.trim(),
                  });
                  setGodModalOpen(false);
                  setGodTargetNpc("");
                  setGodAction("");
                }}
              >
                确认
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => setGodModalOpen(false)}>
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
