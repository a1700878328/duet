import { useState } from "react";

export interface CardDraft {
  name: string;
  persona: string;
  appearance: string;
  voice_id: string;
}

interface Props {
  title: string;
  initial: CardDraft;
  // Label for the primary name field (e.g. "角色名" for member, "名字" for NPC).
  nameLabel?: string;
  submitLabel?: string;
  saving?: boolean;
  onSubmit: (draft: CardDraft) => void;
  onCancel?: () => void;
}

/**
 * Inline form for editing a character card (member or NPC). Field shapes match
 * both: name/persona/appearance/voice_id. Trims and emits the raw draft.
 */
export function CardEditor({
  title,
  initial,
  nameLabel = "名字",
  submitLabel = "保存",
  saving = false,
  onSubmit,
  onCancel,
}: Props) {
  const [draft, setDraft] = useState<CardDraft>(initial);

  function patch(key: keyof CardDraft, value: string) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  function submit() {
    if (saving) return;
    if (!draft.name.trim() || !draft.persona.trim()) return;
    onSubmit({
      name: draft.name.trim(),
      persona: draft.persona.trim(),
      appearance: draft.appearance.trim(),
      voice_id: draft.voice_id.trim(),
    });
  }

  const canSave = draft.name.trim() !== "" && draft.persona.trim() !== "";

  return (
    <div className="card-editor">
      <h4 className="card-editor-title">{title}</h4>
      <div className="field">
        <label>{nameLabel}</label>
        <input
          className="input"
          value={draft.name}
          onChange={(e) => patch("name", e.target.value)}
          placeholder={nameLabel}
        />
      </div>
      <div className="field">
        <label>人设 persona</label>
        <textarea
          className="input card-textarea"
          value={draft.persona}
          onChange={(e) => patch("persona", e.target.value)}
          placeholder="性格、背景、说话方式…"
          rows={4}
        />
      </div>
      <div className="field">
        <label>外貌 appearance（可选）</label>
        <textarea
          className="input card-textarea"
          value={draft.appearance}
          onChange={(e) => patch("appearance", e.target.value)}
          placeholder="用于生成立绘 / 场景图的外貌描述"
          rows={2}
        />
      </div>
      <div className="field">
        <label>音色 voice_id（可选）</label>
        <input
          className="input"
          value={draft.voice_id}
          onChange={(e) => patch("voice_id", e.target.value)}
          placeholder="voice id"
        />
      </div>
      <div className="card-editor-actions">
        {onCancel && (
          <button className="btn btn-ghost" onClick={onCancel} disabled={saving}>
            取消
          </button>
        )}
        <button
          className="btn btn-primary"
          onClick={submit}
          disabled={!canSave || saving}
        >
          {saving ? (
            <>
              <span className="spinner" />
              保存中…
            </>
          ) : (
            submitLabel
          )}
        </button>
      </div>
    </div>
  );
}
