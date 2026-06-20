import type { CharStats, InventoryItem, StatusEffect } from "../lib/types";
import { useI18n } from "../lib/i18n";

interface Props {
  open: boolean;
  onClose: () => void;
  stats: CharStats | null;
  characterName?: string;
}

// 基础栏目：固定顺序，标签 + 值行（《女骑士模拟器》左侧状态列风格）。
const BASE_FIELDS: { key: string; labelKey: string }[] = [
  { key: "职业", labelKey: "job" },
  { key: "冒险者等级", labelKey: "adventurerRank" },
  { key: "等级", labelKey: "level" },
  { key: "经验", labelKey: "experience" },
  { key: "力量", labelKey: "strength" },
  { key: "敏捷", labelKey: "agility" },
  { key: "智力", labelKey: "intelligence" },
  { key: "意志", labelKey: "will" },
  { key: "金钱", labelKey: "money" },
];

// 经验·开发：淫乱向数值，固定顺序展示（含 0，整列可读）。
const LEWD_FIELDS: string[] = [
  "淫乱",
  "欲望",
  "阴道开发",
  "阴道经验",
  "口腔开发",
  "口腔经验",
  "胸部开发",
  "胸部经验",
  "菊穴开发",
  "菊穴经验",
  "高潮经验",
  "露出癖",
  "露出经验",
  "受虐狂",
  "受虐经验",
  "精液中毒",
  "精液经验",
  "百合经验",
  "自慰经验",
];

const STAT_LABEL_KEYS: Record<string, string> = {
  淫乱: "lust",
  欲望: "desire",
  阴道开发: "statVaginalDevelopment",
  阴道经验: "statVaginalExperience",
  口腔开发: "statOralDevelopment",
  口腔经验: "statOralExperience",
  胸部开发: "statBreastDevelopment",
  胸部经验: "statBreastExperience",
  菊穴开发: "statAnalDevelopment",
  菊穴经验: "statAnalExperience",
  高潮经验: "statOrgasmExperience",
  露出癖: "statExposure",
  露出经验: "statExposureExperience",
  受虐狂: "statMasochism",
  受虐经验: "statMasochismExperience",
  精液中毒: "statSemenAddiction",
  精液经验: "statSemenExperience",
  百合经验: "statYuriExperience",
  自慰经验: "statMasturbationExperience",
};

function asNumber(v: unknown): number {
  return typeof v === "number" ? v : 0;
}

function fmt(v: unknown, translate?: (key: string) => string): string {
  if (v === undefined || v === null || v === "") return "—";
  if (typeof v === "number") return String(v);
  if (translate && v === "冒险者") return translate("jobAdventurer");
  return String(v);
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-row">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  );
}

export function StatsPanel({ open, onClose, stats, characterName }: Props) {
  const { t } = useI18n();
  // 状态：优先结构化格式，降级到旧版字符串列表
  const structuredStatus = Array.isArray(stats?.状态)
    ? (stats!.状态 as (StatusEffect | string)[])
    : [];
  const hasStructuredStatus =
    structuredStatus.length > 0 &&
    typeof structuredStatus[0] === "object" &&
    structuredStatus[0] !== null;

  // 物品栏：优先结构化格式，降级到旧版字符串列表
  const structuredItems = Array.isArray(stats?.物品栏)
    ? (stats!.物品栏 as InventoryItem[])
    : [];
  const legacyItems = Array.isArray(stats?.物品)
    ? (stats!.物品 as string[])
    : [];
  const hasStructuredItems = structuredItems.length > 0;

  const favor =
    stats?.好感度 && typeof stats.好感度 === "object" && !Array.isArray(stats.好感度)
      ? (stats.好感度 as Record<string, number>)
      : {};
  const favorEntries = Object.entries(favor);

  return (
    <>
      <div
        className={`card-panel-backdrop ${open ? "open" : ""}`}
        onClick={onClose}
        aria-hidden
      />
      <aside
        className={`card-panel stats-panel ${open ? "open" : ""}`}
        aria-hidden={!open}
      >
        <div className="card-panel-head">
          <h3>📊 {characterName ? `${characterName} · ${t("status")}` : t("myStatusTitle")}</h3>
          <button
            className="btn btn-ghost card-panel-close"
            onClick={onClose}
            aria-label={t("close")}
          >
            ✕
          </button>
        </div>

        <div className="card-panel-body stats-body">
          {!stats && <div className="empty">{t("noStatusData")}</div>}

          {stats && (
            <>
              {/* ---- 基础 ---- */}
              <section className="stat-group">
                <div className="stat-group-head">{t("basics")}</div>
                <div className="stat-grid">
                  {BASE_FIELDS.map((f) => (
                    <StatRow key={f.key} label={t(f.labelKey)} value={fmt(stats[f.key], t)} />
                  ))}
                </div>
              </section>

              {/* ---- 经验·开发 ---- */}
              <section className="stat-group">
                <div className="stat-group-head">{t("development")}</div>
                <div className="stat-grid">
                  {LEWD_FIELDS.map((k) => {
                    const n = asNumber(stats[k]);
                    return (
                      <div
                        className={`stat-row ${n > 0 ? "hot" : "zero"}`}
                        key={k}
                      >
                        <span className="stat-label">{t(STAT_LABEL_KEYS[k] ?? k)}</span>
                        <span className="stat-value">{n}</span>
                      </div>
                    );
                  })}
                </div>
              </section>

              {/* ---- 状态 ---- */}
              <section className="stat-group">
                <div className="stat-group-head">{t("status")}</div>
                {hasStructuredStatus ? (
                  <div className="stat-tags">
                    {(structuredStatus as StatusEffect[]).map((eff, i) => (
                      <span
                        className="stat-tag"
                        key={`${eff.id}-${i}`}
                        title={`${eff.description}（${eff.group}·第${eff.days}天）`}
                      >
                        ⛓ {eff.name}
                        {eff.days > 0 && <small> +{eff.days}</small>}
                      </span>
                    ))}
                  </div>
                ) : structuredStatus.length > 0 ? (
                  <div className="stat-tags">
                    {(structuredStatus as string[]).map((s, i) => (
                      <span className="stat-tag" key={`${s}-${i}`}>
                        ⛓ {s}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="muted stat-empty">{t("noAbnormalStatus")}</div>
                )}
              </section>

              {/* ---- 物品栏 ---- */}
              <section className="stat-group">
                <div className="stat-group-head">{t("inventory")}</div>
                {hasStructuredItems ? (
                  <div className="inventory-grid">
                    {(structuredItems as InventoryItem[]).map((item, i) => (
                      <div className="inventory-item" key={`${item.id}-${i}`}>
                        <span className="inventory-item-icon">{item.icon || "📦"}</span>
                        <div className="inventory-item-body">
                          <span className="inventory-item-name">
                            {item.name}
                            {item.quantity > 1 && (
                              <span className="inventory-item-qty">×{item.quantity}</span>
                            )}
                          </span>
                          <span className="inventory-item-type muted">{item.type}</span>
                          {item.description && (
                            <span className="inventory-item-desc muted">{item.description}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : legacyItems.length > 0 ? (
                  <div className="stat-tags inventory-tags">
                    {legacyItems.map((item, i) => (
                      <span className="stat-tag item" key={`${item}-${i}`}>
                        {item}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="muted stat-empty">{t("noItems")}</div>
                )}
              </section>

              {/* ---- 好感度 ---- */}
              <section className="stat-group">
                <div className="stat-group-head">{t("favorability")}</div>
                {favorEntries.length ? (
                  <div className="stat-grid">
                    {favorEntries.map(([npc, val]) => (
                      <StatRow key={npc} label={npc} value={fmt(val)} />
                    ))}
                  </div>
                ) : (
                  <div className="muted stat-empty">{t("noFavor")}</div>
                )}
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
