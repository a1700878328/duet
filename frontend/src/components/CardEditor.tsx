import { useState } from "react";
import { useI18n } from "../lib/i18n";

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
  const { t } = useI18n();
  const [draft, setDraft] = useState<CardDraft>(initial);
  const resolvedNameLabel = nameLabel === "名字" ? t("name") : nameLabel;

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
        <label>{resolvedNameLabel}</label>
        <input
          className="input"
          value={draft.name}
          onChange={(e) => patch("name", e.target.value)}
          placeholder={resolvedNameLabel}
        />
      </div>
      <div className="field">
        <label>{t("persona")}</label>
        <textarea
          className="input card-textarea"
          value={draft.persona}
          onChange={(e) => patch("persona", e.target.value)}
          placeholder={t("personaPlaceholder")}
          rows={4}
        />
      </div>
      <div className="field">
        <label>{t("appearanceDescription")}</label>
        <textarea
          className="input card-textarea"
          value={draft.appearance}
          onChange={(e) => patch("appearance", e.target.value)}
          placeholder={t("appearancePlaceholder")}
          rows={2}
        />
      </div>
      <div className="field">
        <label>{t("characterVoice")}</label>
        <input
          className="input"
          value={draft.voice_id}
          onChange={(e) => patch("voice_id", e.target.value)}
          placeholder={t("voicePlaceholder")}
        />
      </div>
      <div className="card-editor-actions">
        {onCancel && (
          <button className="btn btn-ghost" onClick={onCancel} disabled={saving}>
            {t("cancel")}
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
              {t("saving")}
            </>
          ) : (
            submitLabel === "保存" ? t("save") : submitLabel
          )}
        </button>
      </div>
    </div>
  );
}
