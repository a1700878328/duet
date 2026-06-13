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

### 2.4 自主时间轴（D）= 定时器驱动导演
每房间一个后台 tick 协程：
- **presence-gated**：房间无人连 → 不 tick。
- 每 ~20–30s（可调档）一拍 → 调导演 → 导演多半返回"无事"（安静）→ 偶尔让 1–2 个 NPC 自主行动。
- 玩家发言立即喂入、可触发即时一拍（不等定时器）。
- 每房间 `sim_mode`（off/manual/auto）+ 节奏档；默认 manual（沿用现"让 AI 接话"）。auto 才开活世界。
- 空闲（玩家 N 分钟无动作）自动降级/暂停，省算力。

### 2.5 算力/刷屏护栏（硬要求）
- 在线才跑；节拍门默认"少事发生"；auto 才开；空闲暂停；tick 速率封顶；导演单次最多 N 个 NPC 行动；并发锁（一拍未完不起下一拍）。
- 所有自主 tick 走 DeepSeek，成本随 auto 时长线性增长——UI 显式提示 + 可一键停。

### 2.6 声画跟卡走
- **语音**：每 NPC 卡 `voice_id` → VoxCPM(.102:9233) 合成该 NPC 台词音频，房间下发。
- **生图**：沿用现 raw 生成 + scene_prompt，但角色外貌来自对应**角色卡**（玩家卡 or NPC 卡），场景来自最近剧情。

## 3. 分阶段（建造顺序）

| 阶段 | 内容 | 验证点 |
|---|---|---|
| **A 角色卡系统** ★先做 | 统一 character card 模型(玩家卡升级+npc_cards表)；玩家可设自己的卡(persona/appearance/voice)；REST CRUD；前端编辑 UI | 玩家能建/改自己的卡，落库、进提示词 |
| **B named NPC + 每 NPC 独立 AI** | 从世界卡 AI 生成 NPC 名册 + 玩家手动召唤；NPC 发言用自己的卡单独调脑；守卫扩到多 NPC 不串台 | 房里有 2+ named NPC，各自口吻不同，不串台 |
| **C 导演调度** | 导演脑调用决定每拍哪些 NPC 行动+顺序+节拍门；多 NPC 同拍 | 一次推进可触发多个 NPC 有序反应，安静时段安静 |
| **D 自主时间轴** | 后台 tick 协程(presence-gated/节奏档/空闲暂停)驱动导演；sim_mode 开关 | 开 auto 后无人发言 NPC 也自主行动；关了即停；空房不耗算力 |
| **E per-NPC 声画** | 语音按卡 voice_id(VoxCPM)；生图按角色卡外貌 | NPC 各自声音；生图用对应角色外貌 |

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
