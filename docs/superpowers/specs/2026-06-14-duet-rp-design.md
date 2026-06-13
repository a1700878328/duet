# Duet — 双人协作 AI 角色扮演社交软件 · 设计文档

> 码名 `duet`（可改）。日期 2026-06-14。
> 本文档 = 产品整体设计 + 首个垂直切片 **SP-1** 的实现级规格。

## 1. 愿景

两名真人从公网同时连入同一个"房间"，各演一个角色，AI 扮演 NPC，三方在**同一条共享时间线**上协作角色扮演。脱离 QQ 的死板触发与按钮限制，提供自定义 UI、导演式控场、生图、配音、记忆与世界设定。

脱胎于 Jetson 上现有的 `qq_agent`（NapCat/QQ 机器人）。其"脑"层（`chat/state/cards/memory/llm`）已与 QQ 解耦，本项目**复用脑层模式、替换前端**：自定义客户端 + 实时同步 + 真正的房间模型。

## 2. 已确认需求（来自需求对齐）

| 维度 | 决定 |
|------|------|
| 玩法 | 共享房间·群演：2 真人各演角色 + AI 演 NPC，单一共享时间线，AI 看得到全场 |
| AI 触发 | **手动推进为主**（"让 AI 接话"按钮）+ 可选自动模式 |
| 公网入口 | **Cloudflare Tunnel**（cloudflared 装 Windows，只暴露 App，不暴露内网端口/家庭 IP） |
| 身份 | 简单账号系统：注册登录、持久身份、房间列表、每人专属记忆 |
| v1 能力 | AI 生图（单/双人 NSFW）、长期记忆、语音 TTS、旁白/叙事者模式 |
| 客户端 | 一套 React 核心 → **手机 App（Capacitor）+ 电脑端（Tauri）+ 浏览器** |
| 后端 | **FastAPI**（async、httpx、pydantic v2），纯 API（REST + WebSocket） |
| 数据库 | **SQLite 起步**，数据层抽象（SQLAlchemy）以便换 Postgres |
| 门禁 | 仅 App 账号门禁（注册才可进） |
| 世界卡 | `ksim-local`《女骑士模拟器》文本 → 可检索 lore RAG 世界卡 |
| 测试 | RP 质量评测为一等公民，贯穿始终（见 §7） |

## 3. 架构

```
公网 · 两名玩家(手机App / 电脑端Tauri / 浏览器)
        │ HTTPS / WSS
   ☁️ Cloudflare Tunnel (cloudflared @ Windows) → app.<域名> → 127.0.0.1:<app>
        ▼
┌─ Windows 主机 .100 — 应用本体 ────────────────────────────────┐
│  FastAPI 后端 (async)                                          │
│   ├─ REST: 账号/房间/角色卡/世界卡/历史                          │
│   ├─ WebSocket Hub: 单房间共享时间线、广播、导演推进、在线状态     │
│   └─ 编排: 取 RAG+记忆 → 组装提示词 → 流式调脑 → 广播 → 异步记忆   │
│  本机服务:                                                      │
│   ├─ SQLite (用户/房间/消息/角色卡/世界卡)                        │
│   ├─ ChromaDB 内嵌 (lore RAG, 中文 embedder, ksim 世界卡)        │
│   ├─ mem0 OSS + qdrant 本地 (情景记忆, 按用户/房间隔离)           │
│   └─ ComfyUI 直连 127.0.0.1:52188 (单/双人 NSFW 生图)            │
└───────────────────────────────────────────────────────────────┘
        │ 局域网 192.168.1.x
☁️ 脑子 BRAIN = DeepSeek V4 Flash (云, OpenAI 兼容 /chat/completions, SSE 流式)
   接入路径待定: 复用 Hermes deepseek 配置 / 官方 API / OpenRouter
   后备: Jetson 本地 Qwen 192.168.1.102:8080 (无审查, DeepSeek 拒涩时兜底)

┌─ Jetson .102 — 语音 (+ 脑子后备) ─────────────────────────────┐
│  VoxCPM TTS  192.168.1.102:9233 (可达性待最终确认)               │
│  Qwen3.6-35B-Uncensored  192.168.1.102:8080 (后备脑)            │
└───────────────────────────────────────────────────────────────┘
```

**每回合数据流**：玩家发言 → WS → 后端追加进共享时间线并广播 →（点"推进"或自动判定）→ 查 Chroma lore + mem0 记忆 → 组装提示词（两人角色卡 + NPC 框架 + 可选旁白 + 检索上下文）→ 流式调 Qwen（`enable_thinking:false`）→ 逐 token 广播给房间双方 → 后台异步对该回合做 mem0 事实抽取（不挡主路）。生图/语音为房间动作，按需触发。

**端口**：脑 `192.168.1.102:8080`；TTS `192.168.1.102:9233`；ComfyUI `127.0.0.1:52188`（+manager `52189`）；App 经 Cloudflare Tunnel。内网端口**绝不**经隧道暴露，只暴露 App。

## 4. 关键技术决策（已被调研实测校正）

- **脑子 = DeepSeek V4 Flash**（用户指定，2026-06-14 覆盖原 Qwen 方案），RP 与辅助任务都用它。
  - 接入 = **DeepSeek 官方 API**（已确认 Hermes 走此路）：base_url `https://api.deepseek.com`、model `deepseek-v4-flash`（官方一线 id，**1M 上下文**）、auth `DEEPSEEK_API_KEY`、OpenAI 兼容 `/chat/completions`、**SSE 流式**。key 由 App 自身 `.env`/密钥库读取（用户放入与 Hermes 同一个 key，文件 0600，不贴明文）。
  - 非 thinking 模型，无 `enable_thinking` 陷阱；云端延迟通常优于本地 Qwen。
  - ⚠️ **核心风险待实测**：调研标注 DeepSeek API 对显式 NSFW 可能审查拒答；但实际被广泛用于 NSFW RP，多半可用。**锁定前对目标端点跑一次 NSFW 探针确认不拒。**
  - ❌ Hermes 网关：`:8642` 不存在、`:5140` 只是 webhook → 不作脑入口（但其 deepseek 配置可借）。
  - 🅑 后备：Jetson 本地 Qwen `:8080`（无审查），DeepSeek 万一拒涩时的兜底。
- **生图 = 本机 ComfyUI 直连**（Option A）：POST `127.0.0.1:52188/prompt` → 轮询 `/history/{id}` → `/view` 取图。
  - **必须整体移植** rp_system 三件套：`char_resolve.py`（提示词构建/fail-closed）+ `assert_no_poisoned_colors`（防错色守卫）+ 单/双人 `build_*_workflow` 模板 + `character_facts.json` + `CHARACTER_LORAS` 映射。否则重现"银发蓝眼"幻觉 bug。
  - HTTP 改 **httpx.AsyncClient**（原版用同步 `requests`）；`/tmp` 路径改 Windows 输出目录 `C:\Users\a1700\Documents\ComfyUI\output`。
  - 单人 832×1216 LoRA@0.85；双人 43 节点 AttentionCouple 1216×832 双 LoRA@0.70。
- **RAG + 记忆 = 两套全新隔离的库**，复用模式不碰现有数据（维度/语料不兼容）。
  - 静态 lore → **ChromaDB**（内嵌 PersistentClient，元数据过滤）。复用 `epub-rag-indexer` 切块套路（TOC 分卷、2000/200、角色标签），但用**中文 embedder（bge-m3 / multilingual-e5）**起全新 collection。
  - 动态情景 → **mem0 OSS**（自起 qdrant 路径/collection），按用户 + 房间作用域（照搬 `qqagent/memory.py` 模式），**事实抽取走后台异步**避开热路径。
- **`ksim-local` → 世界卡管线**：正则抽单引号 CJK 串 `/'((?:[^'\\]|\\.)*)'/`（已验证净收 1064 条/2 万字）→ 按模块文件名(goblin/orc/finalboss/town…)分组打标 → 短串合并成 200–500 字段落 → 灌中文 embedder Chroma collection；另从 `main.*.js` 的 `name{}` + `class_list` 建术语表。Glob `*.js`（hash 文件名会变）。入库时套内容策略。
- **TTS = VoxCPM**（`.102:9233`），复用现有服务，瘦客户端本地化（`hermes_fetch.py` 已有 voices/clone/speak 样板）。SP-6 落地前先确认端口可达性。

## 5. 产品拆解与搭建顺序

| # | 子模块 | 内容 | 依赖 |
|---|--------|------|------|
| **SP-1 ★** | **实时房间核心**（先做，垂直切片） | 账号登录 → 建/进单一共享房间 → 双人共享时间线发言 → "推进"按钮 → Qwen 流式回复双方可见 → 公网可连。最小账号 + WS Hub + SQLite。**打通即验证整个核心风险。** | 仅需 Qwen 端点 + Cloudflare Tunnel |
| SP-2 | 脑适配器 & 提示词编排 | async httpx Qwen 客户端（流式/thinking-off/重试）；系统提示词组装（两角色卡 + NPC 框架 + 旁白模式）；自动模式逻辑 | SP-1 |
| SP-3 | Lore RAG 世界卡 | ksim 抽取/去混淆管线 → 新 Chroma collection → 检索接入 SP-2 提示词 | SP-2 接线（管线本身可并行） |
| SP-4 | 长期记忆 | 新 mem0 实例，按用户/房间作用域，后台异步抽取，召回注入 SP-2 | SP-2 |
| SP-5 | 生图服务 | 移植 char_resolve + 防错色守卫 + 单/双模板；httpx 异步 ComfyUI 客户端（Windows 路径、CUDA 重试）；房间动作 | SP-1（房间动作面） |
| SP-6 | 语音 TTS | VoxCPM 客户端，按 NPC/角色配音映射，音频下发 | SP-1 |
| SP-7 | 账号/记忆打磨 & 加固 | 每人记忆 UI、房间列表管理、Cloudflare 门禁加固、内容策略/年龄门 | SP-1/4 |
| SP-C | 客户端封装 | React 核心 → Capacitor 手机 App + Tauri 电脑端打包配置 | SP-1 起的 React 核心 |
| EVAL | RP 质量评测台（见 §7，横切） | 与 SP-1 同步起，回归跑 | 跟随各 SP |

**推荐顺序**：SP-1 →（SP-2 ∥ SP-5）→（SP-3 ∥ SP-4 ∥ SP-6）→ SP-7 → SP-C。**SP-1 是强制的第一份实现规格。**

## 6. SP-1 实现级规格（首切片）

### 6.1 目标与验收
两名真人从公网各自客户端登录 → 进同一房间 → 在共享时间线发言（彼此实时可见）→ 任一方点"推进" → 后端流式调 Qwen → AI 以 NPC 身份回复，双方实时看到逐字流出。**验收**：两台不同设备经 Cloudflare 公网地址登录同一房间，A 发言 B 立即看到；点推进后 AI 回复在两端同步流式呈现；刷新后历史不丢；AI 回复非空（thinking-off 生效）且不串台（自报为 NPC，不冒充真人）。

### 6.2 数据模型（SQLite / SQLAlchemy async）
- `users`: id, username(uniq), password_hash(argon2), display_name, created_at
- `rooms`: id, name, owner_id, world_card_id?(SP-3 预留 null), ai_mode(`manual`|`auto` 默认 manual), created_at
- `room_members`: room_id, user_id, character_name, character_card_id?(SP-2 预留), joined_at（复合主键 room_id+user_id）
- `messages`: id, room_id, seq(房间内单调递增), author_type(`user`|`ai`|`system`), author_user_id?, speaker_label, content(text), created_at；索引 (room_id, seq)
- 角色卡/世界卡正式建模留给 SP-2/3；SP-1 用 `room_members.character_name` 字符串够跑通。

### 6.3 REST API（FastAPI，全 async，pydantic v2 schema）
- `POST /api/auth/register` {username,password,display_name} → {token}
- `POST /api/auth/login` → {token}（JWT，HttpOnly cookie + Bearer 双发以兼容原生壳）
- `GET  /api/rooms` → 我参与/创建的房间列表
- `POST /api/rooms` {name} → 房间（建者自动入成员）
- `POST /api/rooms/{id}/join` {character_name} → 成员
- `GET  /api/rooms/{id}/messages?after_seq=` → 历史分页（重连补齐）
- `GET  /api/health`

### 6.4 WebSocket `/ws/rooms/{id}`（鉴权同 token）
客户端 → 服务端：
- `say` {content} —— 追加一条 user 消息，分配 seq，广播
- `advance` {} —— 触发 AI 接话（手动推进）
- `typing` {is_typing} —— 可选输入态
服务端 → 客户端（广播）：
- `message` {完整消息对象} —— 新增 user/system 消息
- `ai_delta` {turn_id, seq, delta} —— AI 流式分片
- `ai_done` {turn_id, seq, content, finish_reason}
- `presence` {user_id, online}
- `error` {code, detail}
并发：每房间一个 asyncio 协调器，串行化 seq 分配与 advance（同一时刻一个 AI 回合，advance 重入直接忽略并回 `error: ai_busy`）。

### 6.5 脑调用（SP-1 内联最小版，SP-2 抽出硬化）
- httpx.AsyncClient POST DeepSeek V4 Flash 的 OpenAI 兼容 `/chat/completions`（base_url + model + key 见 §4/§8），`stream:true`，`temperature:0.9`，`max_tokens:420`。脑入口封装成**可配置 provider**（base_url/model/key/headers），便于在 DeepSeek 与 Qwen 后备间一行切换。
- system 提示词（SP-1 最小版）：声明这是双人共享房间群演；列出两名真人各自 `character_name`；AI 只演 NPC/旁白，不冒充真人、不替真人发言；直接出对白不带思考过程/英文 reasoning（沿用 qq_agent prompts 的硬约束）。
- 历史：取该房间最近 N 条 messages 转 OpenAI messages（user 消息带 `[speaker_label]:` 前缀以区分双人 + NPC）。
- 流式分片经 WS 广播；完成落库为一条 author_type=ai 消息。

### 6.6 部署（Cloudflare Tunnel）
- cloudflared 装 Windows，`config.yml` 将 `app.<域名>` 指向 `127.0.0.1:<app_port>`。
- 仅暴露 App 端口；`:8080/:52188/qdrant` 绝不进隧道。
- 前端构建产物由 FastAPI 静态托管（浏览器可直接用；原生壳指向同一公网地址）。

### 6.7 前端（React + Vite，响应式，为壳预留）
- 路由：登录/注册、房间列表、房间页。
- 房间页：共享时间线（区分 A/B/AI/系统）、输入框、**"让 AI 接话"主按钮**、自动模式开关（占位，逻辑 SP-2）、在线状态、AI 流式逐字渲染、断线重连 + `after_seq` 补齐。
- 状态：WS 客户端封装；token 存储兼顾浏览器(cookie)与原生壳(secure storage)。
- 不在 SP-1 引入 Capacitor/Tauri（SP-C 再加壳），但组件/网络层避免任何浏览器独有假设。

## 7. 横切：RP 质量评测台（EVAL，与 SP-1 同步起）

复用 Hermes 质量探针方法论，落成可回归跑、落 ledger 的两层测试：

**A. LLM 输出质量探针**（自动化）
| 维度 | 探针 |
|------|------|
| 一致性 | persona/角色一致性：多轮后性格·口吻·设定不漂移；世界观不自相矛盾 |
| 幻觉 | 只用角色卡/世界卡/lore RAG/记忆里的事实，编造判负；lore 查不到则"不瞎编"（沿用 char_resolve fail-closed 思路） |
| 混乱 | speaker-attribution：双人 + 多 NPC 同场不串台、不代替真人说话、不混淆谁是谁 |
| 上下文 | 长剧情后不忘前文、history 截断不丢关键信息、近因偏差（Hermes 修过的 memory_confusion） |
| 角色卡读取 | 卡加载校验：选定卡真的进 system prompt 且字段被应用（注入"卡内暗记"验证） |
| 人物读取 | 身份归属：每个真人 ↔ 各自角色映射正确，账号身份与 RP 角色不串 |
| 瞎说话 | OOC/越界：不破戏、不输出思考过程/英文 reasoning、不拒答、不冒系统腔 |

**B. 双人实时集成测试**：模拟两个客户端连进同一房间，验证 WS 同步、手动推进触发、消息归属、`advance` 串行化、断线重连补齐、并发不乱序。

评测随 SP 推进扩面（SP-3 后加 lore 接地探针、SP-4 后加跨场记忆探针）。

## 8. 风险与待办

- **脑子接入已定**：DeepSeek 官方 `https://api.deepseek.com` · `deepseek-v4-flash` · `DEEPSEEK_API_KEY`。key 由用户放入 App 密钥库（与 Hermes 同一个 key）；NSFW 探针在 key 就位后跑。
- **DeepSeek NSFW 拒答风险**：本应用是 NSFW RP，云端审查可能拒显式内容。锁定前对目标端点跑 NSFW 探针；若拒 → 启用 Qwen 后备 / 调提示词 / 选更宽松的 deepseek 变体。
- **隐私/出网**：DeepSeek 是云端，RP 内容会发给第三方（不再全程留局域网）。用户已接受。
- **语音单点**：VoxCPM 在 .102，宕机则无配音（不影响文字 RP）。
- **4 并发槽**：双人 + 后台抽取足够，但峰值可能争用；mem0 抽取走后台。
- **ComfyUI 移植保真**：防错色守卫 + 角色注册表必须**整体**移植，否则重现银发蓝眼幻觉。需逐一确认 `CHARACTER_LORAS` 每个 `.safetensors` 在位（仅抽样确认 + 总数 37）；`xinsir_openpose_sdxl.safetensors` ControlNet 模型未确认；双人 hires 1824×1248 对 16GB 显存偏重，需复刻 CUDA-sticky 重启重试。
- **Windows 路径**：rp_system `/tmp/{fn}` 是 POSIX，改 Windows 输出目录或直读 output 目录。
- **标准漂移**：可复用代码全用同步 `requests`，移植时重写为 `httpx.AsyncClient`（async-first）。
- **TTS 位置**：综合简报把 VoxCPM 记在 `.102:9233`，与早期"在 .100"的记忆有出入，SP-6 前实测确认。
- **stale 文档**：`mem0_helper.py` 已删（技能文档部分过时）；无独立 Chroma 构建脚本——按 `epub-rag-indexer` SKILL.md 重实现。
- **内网无鉴权**：Qwen/ComfyUI/qdrant 局域网无认证，家用可接受，但公网隧道只暴露 App。
- **NSFW 合规**：注册门 + 年龄声明 + 入库/输出内容策略（SP-7）。
