# Duet — 多 NPC 自主活世界 · 设计文档

> 在已建成的 duet（SP-1~SP-5 + 记忆 + 评测台）之上的大型演进。
> 日期 2026-06-14。决策来源：用户构想 + "自主时间轴"选择。

## 1. 愿景

把现在"**一个 AI 分饰所有 NPC**"升级成"**多智能体活世界**"：
- 每个 NPC 由**独立 AI** 控制（各自角色卡 → 不同性格/口吻/声音/外貌）。
- NPC **随对话自主行动**（活世界：没人发言时 NPC 也会自己做事/反应）。
- NPC 名册由 **AI 根据世界卡生成预设** + 玩家用选项召唤/分配；玩家可叫 NPC 改设定。
- 语音 per-NPC（按角色卡）、生图 per-character（按场景+角色外貌）。
- 玩家也有自己的**角色卡**（预设或自定义）。

## 2. 架构核心转变

### 2.1 统一「角色卡」（玩家 + NPC 共用）
一张 character card：
```
{ id, room_id, kind: "player"|"npc", name,
  persona: 性格/说话风格/背景(文本),
  appearance: 外貌(生图用,英文tag或中文,沿用现 appearance),
  voice_id: VoxCPM 声音标识(语音用),
  owner_user_id: NPC 归属/创建者(可空), created_by_ai: bool }
```
- 玩家入座绑定一张 player 卡（沿用现 `room_members.character_name/appearance`，升级成完整卡）。
- NPC 卡进新表 `npc_cards`，可由 AI 生成 / 玩家创建 / 玩家编辑。

### 2.2 每 NPC 独立 AI
NPC 发言时，用**该 NPC 的卡**作系统提示词单独调脑（DeepSeek），而非一个全局 AI。发言人归属守卫(SP-2)继续保证 NPC 不冒充玩家、也不冒充别的 NPC。

### 2.3 导演层（每拍谁行动）
一个轻量"导演"脑调用：输入当前场面 + 在场 NPC 名册 + 玩家最近动作，输出 **本拍该行动的 NPC 列表(可空) + 顺序 + 简短动机**。空=安静（节拍门）。然后逐个 NPC 用自己的卡生成台词/动作。

### 2.4 自主时间轴（D）= **叙事跳跃时间**（非现实时钟，用户 2026-06-14 定）
不用后台定时器 tick（会持续烧算力+刷屏）。改成**剧情驱动的时间跳跃**：
- 时间只在**推进剧情**时前进，不按现实秒。导演每拍可判定"是否该跳时间"。
- 跳时间时：导演 narrate 一段流逝（"三天后…"），并**模拟这段时间里各 NPC 幕后做了什么、世界怎么变**（off-screen 行动/关系/局势演进），落成一条旁白 + 必要的记忆事实，再呈现新局面。
- 触发：玩家显式"⏩ 跳过/推进时间"动作，或导演在合适节点自动建议跳。
- 好处：**零持续算力、不刷屏、不需要 presence-gated/速率封顶那套护栏**，世界照样演进。activity 只在用户推进时发生 = 成本可控、可预测。

### 2.5 算力护栏（已大幅简化）
叙事跳跃时间天然避开持续算力问题。剩余护栏：导演单拍最多 N 个 NPC 行动；一拍未完不起下一拍（并发锁）；每次推进=有限次 DeepSeek 调用，成本与用户操作次数挂钩、不随挂机时长增长。

### 2.6 声画跟卡走
- **语音**：每 NPC 卡 `voice_id` → VoxCPM(.102:9233) 合成该 NPC 台词音频，房间下发。
- **生图**：沿用现 raw 生成 + scene_prompt，但角色外貌来自对应**角色卡**（玩家卡 or NPC 卡），场景来自最近剧情。

## 3. 分阶段（建造顺序）

| 阶段 | 内容 | 验证点 |
|---|---|---|
| **A 角色卡系统** ★先做 | 统一 character card 模型(玩家卡升级+npc_cards表)；玩家可设自己的卡(persona/appearance/voice)；REST CRUD；前端编辑 UI | 玩家能建/改自己的卡，落库、进提示词 |
| **B named NPC + 每 NPC 独立 AI** | 从世界卡 AI 生成 NPC 名册 + 玩家手动召唤；NPC 发言用自己的卡单独调脑；守卫扩到多 NPC 不串台 | 房里有 2+ named NPC，各自口吻不同，不串台 |
| **C 导演调度** | 导演脑调用决定每拍哪些 NPC 行动+顺序+节拍门；多 NPC 同拍 | 一次推进可触发多个 NPC 有序反应，安静时段安静 |
| **D 叙事跳跃时间** | 导演支持"跳时间"：narrate 流逝 + 模拟各 NPC 幕后行动 + 世界演进 + 落记忆；玩家"⏩ 推进时间"动作 | 点推进 → 时间跳跃旁白(NPC各自做了啥+新局面)；无后台 tick |
| **E per-NPC 声画 + 头像** | 语音按卡 voice_id(VoxCPM)；生图按卡外貌；**每张卡生成头像(小肖像)，气泡左侧显示** | NPC/玩家各自声音；生图用对应卡外貌；气泡带角色头像 |

**先做 A**：地基，低风险，独立可验。再 B→C→D→E。每阶段保持可玩、可回归(评测台扩"多NPC不串台/导演选人合理"探针)。

## 4. Phase A 实现级规格（先做）

### 4.1 数据模型
- 升级 player 卡：`room_members` 已有 character_name/appearance；加 `persona`(Text,null)、`voice_id`(String,null)。非破坏增量迁移(沿用 `_ADDITIVE_COLUMNS`)。
- 新表 `npc_cards`：id, room_id(fk,index), name, persona(Text), appearance(String512,null), voice_id(String,null), created_by(user_id,null), created_by_ai(bool,default F), created_at。
- （B 阶段才用 npc_cards 发言；A 阶段先把表和 CRUD 建好 + 玩家卡升级。）

### 4.2 REST
- `GET /api/rooms/{id}/cards` → {players:[...], npcs:[...]}（房间全部角色卡）
- `PUT /api/rooms/{id}/me-card` {character_name?, persona?, appearance?, voice_id?} → 更新我的玩家卡
- `POST /api/rooms/{id}/npcs` {name, persona, appearance?, voice_id?} → 手动建 NPC 卡
- `PUT /api/rooms/{id}/npcs/{npc_id}` → 改 NPC 卡（玩家可叫 NPC 改=编辑卡）
- `DELETE /api/rooms/{id}/npcs/{npc_id}`

### 4.3 提示词接入
`build_system_prompt` 把当前玩家卡的 persona 也带上（"你对面的真人玩家扮演 X，设定：…"）；NPC 卡在 B 阶段用于各 NPC 的独立系统提示词。

### 4.4 前端
房间内"角色卡"面板：看/改自己的卡（性格/外貌/声音）、看/建/改 NPC 卡。最小可用即可，B 阶段再接 NPC 发言。

### 4.5 验收
玩家能在房间里设定自己的角色卡(性格+外貌+声音)并落库；能手动建一个 NPC 卡；卡进了 AI 提示词（自己的 persona 体现在 AI 对玩家的称呼/认知上）。评测台加"卡读取"探针覆盖 persona。

## 5. 风险/护栏
- **算力**：自主 tick 是持续成本，护栏见 §2.5；auto 默认关。
- **刷屏/节奏**：节拍门 + 速率封顶 + 导演最多 N NPC/拍。
- **串台升级**：多 NPC 后守卫要扩到"NPC 不冒充别的 NPC/玩家"，发言人白名单=当前应发言的那个 NPC。
- **声画成本/延迟**：语音/生图按需触发，不进自主 tick 默认链。
- **DeepSeek 单脑**：导演 + 各 NPC + 记忆抽取都打同一个 key，auto 高频时注意并发/限速。
- 内嵌 qdrant/chroma 单进程（已知）；多房间自主 tick 同进程内共享。
