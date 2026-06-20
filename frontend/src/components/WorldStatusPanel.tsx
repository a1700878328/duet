import type {
  CharStats,
  NpcCard,
  RoomCards,
  SceneLogEntry,
  SceneLogResponse,
} from "../lib/types";
import { useI18n } from "../lib/i18n";

interface Props {
  open: boolean;
  onClose: () => void;
  cards: RoomCards | null;
  sceneLog: SceneLogResponse | null;
  currentScene: string;
  timeLabel: string;
  myStats: CharStats | null;
  characterName?: string;
  onRefresh: () => void;
  loading?: boolean;
}

const WATCH_KINDS = new Set([
  "offscreen",
  "scene_unlock",
  "npc_introduced",
  "npc_move",
  "god",
  "payment",
]);

function asNumber(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function statusTexts(stats: CharStats | null): string[] {
  const raw = Array.isArray(stats?.状态) ? stats!.状态 : [];
  return raw
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "name" in item) {
        return String(item.name);
      }
      return "";
    })
    .filter(Boolean);
}

function riskSignals(stats: CharStats | null): string[] {
  if (!stats) return [];
  const states = statusTexts(stats);
  const hasState = (text: string) => states.some((s) => s.includes(text));
  const lewd = asNumber(stats.淫乱);
  const will = asNumber(stats.意志);
  const debt = asNumber(stats.负债);
  const money = asNumber(stats.金钱);
  const signals: string[] = [];
  if (states.some((s) => s.startsWith("监禁:"))) signals.push("监禁推进");
  if (hasState("怀孕")) signals.push("怀孕线");
  if (hasState("公共厕所") || hasState("契约:娼妇")) signals.push("堕落契约");
  if (debt >= 300 || (hasState("负债") && debt >= 150) || money < 0) {
    signals.push("债务危机");
  }
  if (lewd >= 50) signals.push("高淫乱");
  if (will <= 5) signals.push("低意志");
  return signals.slice(0, 5);
}

function statDisplay(value: unknown): string {
  if (typeof value === "number" || typeof value === "string") return String(value);
  if (value === null || value === undefined) return "—";
  return "—";
}

function groupNpcsByScene(npcs: NpcCard[], currentScene: string, fallbackScene: string) {
  const groups = new Map<string, NpcCard[]>();
  for (const npc of npcs) {
    if (npc.name === "上帝") continue;
    const scene = npc.scene || currentScene || fallbackScene;
    const group = groups.get(scene) ?? [];
    group.push(npc);
    groups.set(scene, group);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b, "zh-Hans-CN"));
}

function recentWorldEntries(sceneLog: SceneLogResponse | null): SceneLogEntry[] {
  const entries = Object.values(sceneLog?.logs ?? {})
    .flat()
    .filter((entry) => WATCH_KINDS.has(entry.kind));
  return entries.slice(-10).reverse();
}

function sceneActivity(sceneLog: SceneLogResponse | null, scene: string): number {
  return sceneLog?.logs[scene]?.length ?? 0;
}

export function WorldStatusPanel({
  open,
  onClose,
  cards,
  sceneLog,
  currentScene,
  timeLabel,
  myStats,
  characterName,
  onRefresh,
  loading,
}: Props) {
  const { t } = useI18n();
  const npcs = cards?.npcs ?? [];
  const players = cards?.players ?? [];
  const scenes = sceneLog?.scenes?.length
    ? sceneLog.scenes
    : currentScene
      ? [currentScene]
      : [];
  const npcGroups = groupNpcsByScene(npcs, currentScene, t("followerScene"));
  const recent = recentWorldEntries(sceneLog);
  const risks = riskSignals(myStats);
  const states = statusTexts(myStats);
  const displayScene = (value: string) =>
    !value || value === "自由场景" ? t("freeScene") : value;

  return (
    <>
      <div
        className={`card-panel-backdrop ${open ? "open" : ""}`}
        onClick={onClose}
        aria-hidden
      />
      <aside
        className={`card-panel world-panel ${open ? "open" : ""}`}
        aria-hidden={!open}
      >
        <div className="card-panel-head">
          <h3>{t("worldStatus")}</h3>
          <div className="world-head-actions">
            <button className="btn btn-sm" onClick={onRefresh} disabled={loading}>
              {t("refresh")}
            </button>
            <button
              className="btn btn-ghost card-panel-close"
              onClick={onClose}
              aria-label={t("close")}
            >
              ✕
            </button>
          </div>
        </div>

        <div className="card-panel-body world-body">
          <section className="world-overview">
            <div className="world-metric">
              <span>{t("time")}</span>
              <strong>{timeLabel}</strong>
            </div>
            <div className="world-metric">
              <span>{t("currentLocation")}</span>
              <strong>{currentScene || t("freeScene")}</strong>
            </div>
            <div className="world-metric">
              <span>{t("people")}</span>
              <strong>{t("playersCount", { players: players.length, npcs: npcs.filter((n) => n.name !== "上帝").length })}</strong>
            </div>
          </section>

          <section className="world-section">
            <div className="world-section-head">
              <h4>{t("locationAndNpcs")}</h4>
              {loading && <span>{t("syncing")}</span>}
            </div>
            <div className="world-scene-list">
              {scenes.map((scene) => {
                const sceneNpcs =
                  npcGroups.find(([name]) => name === scene)?.[1] ?? [];
                return (
                  <div
                    className={`world-scene ${scene === currentScene ? "active" : ""}`}
                    key={scene}
                  >
                    <div className="world-scene-row">
                      <strong>{displayScene(scene)}</strong>
                      <span>{t("recordsCount", { count: sceneActivity(sceneLog, scene) })}</span>
                    </div>
                    <div className="world-npc-pills">
                      {sceneNpcs.length ? (
                        sceneNpcs.map((npc) => (
                          <span className="world-npc-pill" key={npc.id}>
                            {npc.name}
                          </span>
                        ))
                      ) : (
                        <em>{t("noVisibleNpc")}</em>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="world-section">
            <div className="world-section-head">
              <h4>{t("backgroundMoves")}</h4>
            </div>
            <div className="world-feed">
              {recent.length ? (
                recent.map((entry, index) => (
                  <div className={`world-feed-item kind-${entry.kind}`} key={`${entry.scene}-${entry.time_label}-${index}`}>
                    <div className="world-feed-meta">
                      <span>{entry.scene}</span>
                      <b>{entry.speaker_label}</b>
                      <small>{entry.time_label}</small>
                    </div>
                    <p>{entry.content}</p>
                  </div>
                ))
              ) : (
                <div className="world-empty">{t("noBackgroundMoves")}</div>
              )}
            </div>
          </section>

          <section className="world-section">
            <div className="world-section-head">
              <h4>{characterName ? t("characterDirectionNamed", { name: characterName }) : t("characterDirection")}</h4>
            </div>
            <div className="world-risk-grid">
              <div className="world-risk-card">
                <span>{t("money")}</span>
                <strong>{statDisplay(myStats?.金钱)}</strong>
              </div>
              <div className="world-risk-card">
                <span>{t("will")}</span>
                <strong>{statDisplay(myStats?.意志)}</strong>
              </div>
              <div className="world-risk-card">
                <span>{t("lust")}</span>
                <strong>{statDisplay(myStats?.淫乱)}</strong>
              </div>
              <div className="world-risk-card">
                <span>{t("debt")}</span>
                <strong>{statDisplay(myStats?.负债 ?? 0)}</strong>
              </div>
            </div>
            <div className="world-tags">
              {risks.length ? (
                risks.map((risk) => <span key={risk}>{risk}</span>)
              ) : (
                <em>{t("noEndingRisk")}</em>
              )}
            </div>
            {states.length > 0 && (
              <div className="world-state-lines">
                {states.slice(0, 5).map((state) => (
                  <span key={state}>{state}</span>
                ))}
              </div>
            )}
          </section>
        </div>
      </aside>
    </>
  );
}
