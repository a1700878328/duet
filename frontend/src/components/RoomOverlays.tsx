import { useState, type FormEvent } from "react";
import { assetUrl } from "../lib/api";
import type { CharStats } from "../lib/types";

// A resolved profile for the avatar popover — player (with stats) or NPC.
export interface ProfileView {
  kind: "player" | "npc";
  id?: number;
  name: string;
  avatarUrl?: string | null;
  appearance?: string | null;
  persona?: string | null;
  scene?: string | null; // npc only
  discovered?: string | null; // npc: 玩家逐渐了解到的信息
  stats?: CharStats | null; // player only
}

// Fixed order for the compact stat readout in a player's profile card.
const KEY_STATS: string[] = [
  "职业",
  "冒险者等级",
  "等级",
  "经验",
  "金钱",
  "力量",
  "敏捷",
  "智力",
  "意志",
  "淫乱",
  "欲望",
];

function StatRow({ k, v }: { k: string; v: unknown }) {
  return (
    <div className="pf-stat">
      <span className="pf-stat-k">{k}</span>
      <span className="pf-stat-v">{String(v)}</span>
    </div>
  );
}

// Click-outside backdrop wrapper shared by both overlays.
function Backdrop({
  onClose,
  children,
  className,
}: {
  onClose: () => void;
  children: React.ReactNode;
  className: string;
}) {
  return (
    <div className={`overlay-backdrop ${className}`} onClick={onClose}>
      <div className="overlay-inner" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

export function ProfileModal({
  profile,
  onClose,
  onPayNpc,
  currentMoney,
  paymentBusy,
}: {
  profile: ProfileView;
  onClose: () => void;
  onPayNpc?: (npcId: number, amount: number) => void;
  currentMoney?: number | null;
  paymentBusy?: boolean;
}) {
  const [payAmount, setPayAmount] = useState("");
  const stats = profile.stats ?? null;
  const rawStates = Array.isArray(stats?.["状态"]) ? stats!["状态"] : [];
  const states: string[] = rawStates.length > 0
    ? rawStates.map((s: any) => (typeof s === "object" ? s.name || s.id : String(s)))
    : [];
  const items: string[] = Array.isArray(stats?.["物品"])
    ? (stats!["物品"] as string[])
    : [];
  const fav =
    stats && typeof stats["好感度"] === "object" && stats["好感度"]
      ? (stats["好感度"] as Record<string, number>)
      : {};
  const amount = Number.parseInt(payAmount, 10);
  const validAmount = Number.isFinite(amount) && amount > 0 ? amount : 0;
  const lacksMoney =
    profile.kind === "npc" &&
    currentMoney !== null &&
    currentMoney !== undefined &&
    validAmount > currentMoney;
  const canPay =
    profile.kind === "npc" &&
    profile.id !== undefined &&
    Boolean(onPayNpc) &&
    validAmount > 0 &&
    !lacksMoney &&
    !paymentBusy;
  function submitPayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canPay || profile.id === undefined) return;
    onPayNpc?.(profile.id, validAmount);
    setPayAmount("");
  }

  return (
    <Backdrop onClose={onClose} className="profile">
      <div className="pf-card">
        <button className="pf-close" onClick={onClose} aria-label="关闭">
          ✕
        </button>
        <div className="pf-portrait">
          {profile.avatarUrl ? (
            <img src={assetUrl(profile.avatarUrl)} alt={profile.name} />
          ) : (
            <div className="pf-portrait-fallback">
              {profile.name.charAt(0) || "?"}
            </div>
          )}
        </div>
        <div className="pf-name">
          {profile.name}
          <span className="pf-kind">
            {profile.kind === "player" ? "玩家" : "NPC"}
            {profile.scene ? ` · 📍${profile.scene}` : ""}
          </span>
        </div>

        {profile.appearance && (
          <div className="pf-section">
            <div className="pf-label">外貌</div>
            <div className="pf-text">{profile.appearance}</div>
          </div>
        )}
        {profile.persona && (
          <div className="pf-section">
            <div className="pf-label">设定</div>
            <div className="pf-text">{profile.persona}</div>
          </div>
        )}
        {profile.discovered && (
          <div className="pf-section">
            <div className="pf-label">已了解到（随剧情更新）</div>
            <div className="pf-text">{profile.discovered}</div>
          </div>
        )}

        {profile.kind === "npc" && profile.id !== undefined && onPayNpc && (
          <form className="pf-pay" onSubmit={submitPayment}>
            <div className="pf-label">支付</div>
            <div className="pf-pay-row">
              <input
                type="number"
                min="1"
                step="1"
                inputMode="numeric"
                value={payAmount}
                onChange={(e) => setPayAmount(e.target.value)}
                placeholder="金额"
                disabled={paymentBusy}
              />
              <button className="btn btn-sm" type="submit" disabled={!canPay}>
                支付
              </button>
            </div>
            <div className={`pf-pay-hint ${lacksMoney ? "warn" : ""}`}>
              当前金钱：{currentMoney ?? "?"}
              {lacksMoney ? `，不足支付 ${validAmount}` : ""}
            </div>
          </form>
        )}

        {profile.kind === "player" && stats && (
          <div className="pf-section">
            <div className="pf-label">状态属性</div>
            <div className="pf-stats">
              {KEY_STATS.filter((k) => stats[k] !== undefined).map((k) => (
                <StatRow key={k} k={k} v={stats[k]} />
              ))}
            </div>
            {states.length > 0 && (
              <div className="pf-tags">
                {states.map((s) => (
                  <span key={s} className="pf-tag">
                    ⛓ {s}
                  </span>
                ))}
              </div>
            )}
            {items.length > 0 && (
              <div className="pf-tags">
                {items.map((item, idx) => (
                  <span key={`${item}-${idx}`} className="pf-tag item">
                    {item}
                  </span>
                ))}
              </div>
            )}
            {Object.keys(fav).length > 0 && (
              <div className="pf-tags">
                {Object.entries(fav).map(([npc, val]) => (
                  <span key={npc} className="pf-tag fav">
                    ♥ {npc} {val}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Backdrop>
  );
}

export function ImageLightbox({
  url,
  onClose,
}: {
  url: string;
  onClose: () => void;
}) {
  return (
    <Backdrop onClose={onClose} className="lightbox">
      <img className="lightbox-img" src={assetUrl(url)} alt="场景图" />
    </Backdrop>
  );
}
