# Anima + NTRMix 特色二次元人物 Prompt 教程

测试/修订日期：2026-06-17  
主模型：`anima_baseV10` / `anima-base-v1.0.safetensors`  
文本编码器：`qwen_3_06b_base`  
VAE：`qwen_image_vae`  
主风格 LoRA：`ntrmix_style_anima_b1_v1.safetensors`  
触发词：`@ntrmixstyle`

## 先纠正方向

这套教程的目标不是把所有图都画成夜景、烟花、爆炸、城市街道。那些只是场景，不是核心画风。

用户真正喜欢的是这类“脸好看”的二次元角色画风。下面这条是成功样例，不是以后所有角色卡都要照抄的固定模板：

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, white hair, long hair, braid, blue eyes, colored eyelashes, jitome,
witch hat, smile, blush, open mouth, sweat, spoken question mark,
medium breasts, wide sleeves, sleeves past wrists, white thighhighs,
cowboy shot, from side, looking at viewer, indoors, dungeon, brick wall
```

它好看的核心是：

- 脸部锚点很明确：`colored eyelashes + 眼神 + 表情 + blush + 嘴型`。
- 眼神不是普通微笑，而是半眯、俏皮、带一点困惑或挑逗感：`jitome + smile + blush` 是核心组合。
- 头发和脸框住得好：`white hair, long hair, braid, blue eyes, colored eyelashes` 让脸有清晰识别度。
- 服装具体但不抢脸：`witch hat, wide sleeves, sleeves past wrists, white thighhighs` 只是衬托角色，不是主角。
- 镜头偏近：`cowboy shot / upper body / close-up` 让主体占画面大；`from side`、`looking at viewer` 只是其中一种镜头味道。
- 场景简单但有气氛：`indoors, dungeon, brick wall`，不抢角色。

所以以后写各种角色时，要保留“漂亮脸骨架”，而不是固定某个场景、嘴型、镜头或题材。尤其不要把 `open mouth`、`from side`、`looking at viewer` 写成每张都必须出现的默认项，否则角色卡会变得像同一张脸的证件照变体。

## 漂亮脸骨架

这是最重要的部分。想要接近样图那种脸，prompt 里要有一段专门管脸：

```text
[hair color], [hair length], [hair style], [eye color], colored eyelashes,
[eye style], [expression], blush, [mouth detail], [small mood detail]
```

把它理解成“槽位”，不要理解成固定短语。最稳的脸部骨架是：

```text
colored eyelashes, [eye style], [expression], blush, [mouth detail]
```

嘴型必须单独选。默认不要用 `open mouth`，除非这张图真的需要说话、惊讶或大笑。

```text
closed mouth                 # 最稳，适合角色卡、立绘、冷淡/强势角色
parted lips                  # 微张嘴，保留灵气但不会每张都像在喊
small open mouth             # 轻微说话/惊讶，比 open mouth 克制
open mouth                   # 只给说话、唱歌、兴奋、吐槽表情
```

如果想更可爱：

```text
wide-eyed, bright smile, blush, parted lips, sparkling eyes
```

如果想更冷淡：

```text
jitome, expressionless, faint smile, blush, closed mouth, sleepy eyes
```

如果想更强势：

```text
sharp eyes, smug smile, blush, closed mouth, confident expression
```

如果想更天然：

```text
soft eyes, gentle smile, blush, parted lips, slightly embarrassed
```

如果想更俏皮吐槽：

```text
jitome, mischievous smile, blush, small open mouth, spoken question mark
```

最推荐的通用脸部组合：

```text
colored eyelashes, half-closed eyes, faint smile, blush, parted lips
```

这个组合比单纯写 `beautiful face`、`cute face` 更有效。`beautiful face` 太泛，模型不一定知道你要哪种脸；上面这组词会直接把脸导向样图那种“眼神、脸红、嘴型、细睫毛”的效果，但不会强制每张都张嘴。

如果模型还是总是张嘴，在 negative 里临时加：

```text
open mouth, wide open mouth, shouting, yelling
```

## 推荐参数

```text
Positive prefix: masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle
Negative: worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, lowres, censor
Steps: 30
CFG scale: 4
Sampler: ER SDE
Schedule type: Beta
Shift: 3
Width/Height: 832 x 1216 for single character
Hires upscale: 1.5
Hires steps: 20
Hires CFG: 4
Denoising strength: 0.3-0.35
```

当前本机已安装：

```text
ntrmix_style_anima_b1_v1.safetensors
```

本教程不依赖其他题材 LoRA。目标是单靠 `@ntrmixstyle` 写出好看的角色脸，再把脸部审美套到各种 OC 和二创角色上。

## Prompt 总公式

把 prompt 拆成 9 块：

```text
画质前缀,
人数,
角色身份,
头发和眼睛,
表情,
身体比例,
服装部件,
姿势和镜头,
场景
```

完整模板：

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo,
[character name \(series\) / original anime girl],
[hair color], [hair length], [hair style], [bangs/detail], [eye color], colored eyelashes,
[eye style], [expression], blush, [mouth detail], [mood detail],
[body scale],
[headwear], [top], [sleeves/gloves], [bottom], [legwear], [accessories],
[pose], [camera shot], [camera angle], [gaze direction],
[location], [background material], [lighting]
```

角色卡的核心变量是 `mouth detail`、`camera angle`、`gaze direction`。这三个槽位每张至少换一个，否则很容易变成“同一个正面表情换皮肤”。

## 写好看角色的关键词库

### 发型

```text
long hair, very long hair, braid, side braid, twin braids, low twintails, side ponytail, high ponytail, hime cut, blunt bangs, sidelocks, long bangs, hair between eyes, ahoge, hair intakes
```

### 眼睛和脸

```text
blue eyes, red eyes, purple eyes, golden eyes, heterochromia, colored eyelashes, jitome, half-closed eyes, wide-eyed, heart-shaped pupils, sharp eyes, sleepy eyes
```

脸部优先级建议：

```text
colored eyelashes > eye style > expression > mouth detail > blush
```

举例：

```text
colored eyelashes, half-closed eyes, faint smile, blush, parted lips
colored eyelashes, sleepy eyes, faint smile, blush, parted lips
colored eyelashes, sharp eyes, smug smile, blush, closed mouth
colored eyelashes, wide-eyed, bright smile, blush, small open mouth
```

### 表情

```text
smile, faint smile, smug smile, confident smile, mischievous smile, gentle smile, expressionless, serious, calm, blush, sweat, spoken question mark
```

### 嘴型

```text
closed mouth, parted lips, small open mouth, open mouth, slight smile, neutral mouth, pout
```

嘴型建议：

```text
角色卡默认：closed mouth / parted lips
俏皮吐槽：small open mouth + spoken question mark
唱歌说话：open mouth
冷淡强势：closed mouth + sharp eyes / expressionless
```

### 服装部件

```text
witch hat, wide sleeves, sleeves past wrists, white thighhighs, black pantyhose, elbow gloves, black gloves, choker, ribbon, necktie, capelet, jacket on shoulders, open jacket, fur-trimmed jacket, high-waist skirt
```

### 镜头

```text
cowboy shot, upper body, close-up, full body, three-quarter view, profile, from side, from behind, over shoulder, from below, from above, dutch angle, dynamic pose
```

### 视线

```text
looking at viewer, looking away, looking to the side, looking back, looking down, looking up, looking over shoulder, eyes toward viewer
```

注意：`cowboy shot + from side + looking at viewer` 是用户样图里一种很重要的镜头味道，但不能每张都用。角色卡建议轮换下面几类：

```text
three-quarter view, upper body, eyes toward viewer
profile, close-up, looking to the side
over shoulder, looking back, cowboy shot
from above, upper body, looking up
from below, cowboy shot, looking down at viewer
full body, standing, simple background
```

如果画面总是正面证件照，在 positive 加 `three-quarter view`、`profile`、`over shoulder`、`looking to the side`，同时在 negative 临时加：

```text
front view, symmetrical composition, passport photo, id photo, straight-on
```

### 角色卡风格包

角色卡不要只有一种“媚脸 NTRMix”。按用途选风格包，每次只选一包：

```text
clean anime character sheet, simple background, soft cel shading, clear silhouette
anime key visual, dramatic lighting, detailed costume, cinematic composition
game character portrait, polished illustration, rim light, sharp face detail
slice of life anime still, natural lighting, relaxed pose, soft background
fashion catalog portrait, clean outfit details, elegant pose, studio lighting
dark fantasy portrait, ornate costume, low warm light, stone background
cyber idol portrait, glossy fabric, neon rim light, stage lights
```

如果风格和原作不符，先弱化 NTRMix 味道：减少 `jitome/open mouth/sweat/spoken question mark`，把嘴型改成 `closed mouth` 或 `parted lips`，并把风格包换成 `clean anime character sheet` 或 `slice of life anime still`。

## 角色卡生成过程修正版

角色卡不是只出“正面半身 + 张嘴微笑”。推荐一次做 4 张小批量，每张固定身份和服装，只轮换嘴型、镜头、风格包。

### A. 标准立绘卡

用于确认角色设计、服装和整体轮廓：

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, [character identity],
[hair], [eyes], colored eyelashes,
calm expression, closed mouth, slight blush,
[body scale],
[signature outfit parts],
standing, full body, three-quarter view, eyes toward viewer,
clean anime character sheet, simple background, soft cel shading, clear silhouette
```

### B. 半身头像卡

用于头像、对话立绘、角色介绍页：

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, [character identity],
[hair], [eyes], colored eyelashes,
half-closed eyes, faint smile, parted lips, blush,
[signature outfit upper body parts],
upper body, three-quarter view, looking to the side,
game character portrait, polished illustration, rim light, sharp face detail
```

### C. 侧脸情绪卡

用于打破正面脸和同质化表情：

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, [character identity],
[hair], [eyes], colored eyelashes,
serious, closed mouth, soft blush,
[signature outfit parts],
profile, close-up, looking to the side,
slice of life anime still, natural lighting, soft background
```

### D. 回头动态卡

用于更有画面感的角色展示：

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, [character identity],
[hair], [eyes], colored eyelashes,
mischievous smile, small open mouth, blush,
[signature outfit parts],
over shoulder, looking back, cowboy shot, dynamic pose,
anime key visual, cinematic composition, detailed costume, dramatic lighting
```

### 批量轮换规则

一次小批量建议这样换：

```text
图1：closed mouth + three-quarter view + clean anime character sheet
图2：parted lips + upper body + game character portrait
图3：closed mouth + profile + slice of life anime still
图4：small open mouth + over shoulder + anime key visual
```

不要在角色卡阶段连续使用：

```text
open mouth, looking at viewer, front view, cowboy shot
```

这几个词单独都能用，但连续使用会让生成过程回到“正面张嘴同脸”。

## 自定义角色模板

### 1. 白发魔女

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, original anime witch girl,
white hair, long hair, braid, long bangs, blue eyes, colored eyelashes,
half-closed eyes, faint smile, blush, parted lips, light sweat,
medium breasts,
witch hat, wide sleeves, sleeves past wrists, black ribbon, white thighhighs,
sitting, cowboy shot, three-quarter view, eyes toward viewer,
indoors, dungeon, brick wall, dim warm light
```

这条保留了用户样图的脸部审美，但把嘴型降到 `parted lips`，镜头改成 `three-quarter view`。换别的角色时优先保留“细睫毛 + 眼神 + 表情 + 嘴型槽位”，不要强行保留 `open mouth`。

### 2. 黑发军服少女

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, original anime officer girl,
black hair, long hair, hime cut, blunt bangs, red eyes, colored eyelashes,
smug smile, blush, closed mouth, sharp eyes,
medium breasts,
military cap, black uniform jacket, gold trim, red necktie, black gloves, black pantyhose,
standing, hand on hip, cowboy shot, from below, looking at viewer,
indoors, command room, dark metal wall, dramatic rim light
```

### 3. 蓝发赛博偶像

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, original cyber idol girl,
blue hair, long hair, side ponytail, hair between eyes, cyan eyes, colored eyelashes,
wide-eyed, bright smile, blush, small open mouth,
medium breasts,
glowing hair ornament, cropped jacket, white shirt, black shorts, mismatched gloves, thigh strap,
leaning forward, v over mouth, upper body, dutch angle, looking at viewer,
indoors, neon stage, hologram lights, glossy floor
```

### 4. 和风鬼族少女

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, original oni girl,
white hair, red hair streaks, long hair, ponytail, red horns, golden eyes, colored eyelashes,
confident smile, blush, parted lips,
medium breasts,
red kimono, wide sleeves, black sash, bead bracelet, thighhighs,
sitting, holding fan, profile, looking to the side,
indoors, tatami room, round window, warm sunlight
```

### 5. 哥特修女

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, original gothic nun girl,
silver hair, very long hair, low twintails, long bangs, purple eyes, colored eyelashes,
expressionless, blush, parted lips, sleepy eyes,
medium breasts,
black veil, white collar, black dress, detached sleeves, cross necklace, black pantyhose,
kneeling, upper body, from above, looking at viewer,
indoors, old chapel, stone wall, candlelight
```

## 二创角色写法

二创角色要先写官方身份，再补“可识别特征”。不要只写名字。

公式：

```text
1girl, solo, [角色名 \(作品名\)], [作品名],
[官方发色/眼色/头饰/标志物],
[你要的表情],
[换装或原服装],
[镜头],
[场景]
```

二创角色如果要套样图脸，不要只靠官方角色名。角色名后面仍然要补脸部锚点：

```text
colored eyelashes, [eye style], [expression], blush, [mouth detail]
```

### Hatsune Miku 魔女换装

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, hatsune miku, vocaloid,
blue hair, very long hair, twintails, blue eyes, colored eyelashes,
bright eyes, cheerful smile, blush, small open mouth, spoken question mark,
medium breasts,
witch hat, wide sleeves, sleeves past wrists, black ribbon, white thighhighs,
sitting, cowboy shot, three-quarter view, looking at viewer,
indoors, dungeon, brick wall, dim warm light
```

### Raiden Shogun 黑色礼服换装

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, raiden shogun \(genshin impact\), genshin impact,
purple hair, long hair, braid, purple eyes, colored eyelashes,
calm smile, blush, closed mouth, sharp eyes,
medium breasts,
black dress, detached sleeves, purple ribbon, black thighhighs,
standing, cowboy shot, from below, looking at viewer,
indoors, palace room, wooden wall, soft lantern light
```

### 2B 风格机械少女

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, 2b \(nier automata\), nier automata,
white hair, short hair, black blindfold, pale skin,
faint smile, blush, closed mouth,
medium breasts,
black gothic dress, puffy sleeves, black gloves, thighhighs, thigh strap,
standing, hand on hip, three-quarter view, upper body, looking to the side,
indoors, ruined factory, concrete wall, cool rim light
```

### Frieren 魔女风

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, frieren \(sousou no frieren\), sousou no frieren,
white hair, long hair, twintails, green eyes, elf ears, colored eyelashes,
sleepy eyes, faint smile, blush, closed mouth,
small breasts,
witch hat, white cloak, long sleeves, black pantyhose,
standing, upper body, looking at viewer,
indoors, stone library, brick wall, candlelight
```

## 双人一致性写法

NTRMix/Anima 可以画好看的双人，但它不是区域控制。它能做到“两个角色明显不同”，不保证 `left side` 一定严格执行。

双人模板：

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
2girls, exactly two girls, duo, no boys, no other people,
left girl, [A hair], [A eyes], [A outfit], [A expression],
right girl, [B hair], [B eyes], [B outfit], [B expression],
different hairstyles, different hair colors, different outfits, separate faces, separate bodies,
[simple interaction], [camera shot], [gaze direction],
[location], [lighting]
```

推荐双人例子：

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
2girls, exactly two girls, duo, no boys, no other people,
left girl, black hair, long hair, hime cut, red eyes, black military uniform, smug smile,
right girl, white hair, long hair, braid, blue eyes, witch hat, wide sleeves, gentle smile,
different hairstyles, different hair colors, different outfits, separate faces, separate bodies,
standing close together, upper body, three-quarter view, eyes toward viewer,
indoors, dungeon, brick wall, dim warm light
```

双人避坑：

- 不要让两个人发色、服装、表情都接近。
- 不要写太复杂的肢体互动，先用 `standing close together`、`sitting side by side`。
- 加 `exactly two girls, no other people`。
- 反向加 `duplicate character, extra person, third person, merged faces, fused bodies, same face, identical twins`。
- 如果要严格左右位置和身份，不要靠纯 prompt，改用区域控制/Attention Couple。

## 成人向/特殊题材写法

不要让任何题材词吞掉脸。无论是魔女、军服、偶像、教室、神社、战斗、日常，都按这个顺序：

```text
角色身份 -> 发型眼睛 -> 脸部锚点 -> 服装部件 -> 姿势镜头 -> 场景/题材
```

题材词不要放在角色脸前面。用户给的例子脸好看，正是因为它先写完：

```text
white hair, long hair, braid, blue eyes, colored eyelashes, jitome,
witch hat, smile, blush, open mouth, sweat, spoken question mark,
medium breasts, wide sleeves, sleeves past wrists, white thighhighs
```

然后才进入姿势、镜头和场景。

但这条里的 `open mouth, sweat, spoken question mark` 属于“吐槽/说话表情”，不是成人向或角色卡的通用脸。做角色卡时优先改成：

```text
colored eyelashes, half-closed eyes, faint smile, blush, parted lips
colored eyelashes, sharp eyes, smug smile, blush, closed mouth
colored eyelashes, sleepy eyes, expressionless, slight blush, closed mouth
```

## 最实用的改图方法

保持不变：

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle
steps 30, cfg 4, ER SDE, Beta, 832x1216
```

每次只改这三块：

```text
脸部块：发色、发型、眼睛、colored eyelashes、眼神、表情、嘴型
服装块：帽子、袖子、袜子、外套、饰品
镜头块：正面/三分之二/侧脸/回头、视线、远近
场景块：地牢、教室、舞台、神社、工厂、宫殿、图书馆
```

不要每张都加烟花、爆炸、夜街。那些只是可选场景，不是这套画风的本体。

最稳的做法是先固定角色身份和脸部槽位：

```text
[hair], [eyes], colored eyelashes, [eye style], [expression], blush, [mouth detail]
```

然后轮换嘴型、镜头和风格包。这样不同题材不会跑成完全不同的脸，也不会全变成同一个正面张嘴表情。

## 2026-06-15 完整实测结论

2026-06-17 修订：下面这组旧测试证明了 `@ntrmixstyle` 能稳定产出好看的脸，但旧测试过度依赖 `open mouth`、`from side`、`looking at viewer`。这些词现在只作为“样图复刻/吐槽表情”的可选项，不再作为角色卡默认流程。

按旧版“固定漂亮脸锚点，只换角色类型”的方法，实际跑了 9 张：

```text
C:\Users\a1700\Desktop\comfyui调查\test_outputs\NTRMIX_FACE_OC_WHITE_WITCH_FACE_2606155201_REFINED_00001_.png
C:\Users\a1700\Desktop\comfyui调查\test_outputs\NTRMIX_FACE_OC_BLACK_OFFICER_FACE_2606155202_REFINED_00001_.png
C:\Users\a1700\Desktop\comfyui调查\test_outputs\NTRMIX_FACE_OC_CYBER_IDOL_FACE_2606155203_REFINED_00001_.png
C:\Users\a1700\Desktop\comfyui调查\test_outputs\NTRMIX_FACE_OC_ONI_KIMONO_FACE_2606155204_REFINED_00001_.png
C:\Users\a1700\Desktop\comfyui调查\test_outputs\NTRMIX_FACE_OC_GOTHIC_NUN_FACE_2606155205_REFINED_00001_.png
C:\Users\a1700\Desktop\comfyui调查\test_outputs\NTRMIX_FACE_FAN_MIKU_WITCH_FACE_2606155206_REFINED_00001_.png
C:\Users\a1700\Desktop\comfyui调查\test_outputs\NTRMIX_FACE_FAN_RAIDEN_DRESS_FACE_2606155207_REFINED_00001_.png
C:\Users\a1700\Desktop\comfyui调查\test_outputs\NTRMIX_FACE_FAN_FRIEREN_WITCH_FACE_2606155208_REFINED_00001_.png
C:\Users\a1700\Desktop\comfyui调查\test_outputs\NTRMIX_FACE_FAN_2B_GOTHIC_FACE_2606155209_REFINED_00001_.png
```

测试脚本：

```text
C:\Users\a1700\Desktop\comfyui调查\work\run_ntrmix_face_style_full_tests.ps1
```

已导出的 ComfyUI API prompt：

```text
C:\Users\a1700\Desktop\comfyui调查\work\FINAL_Anima_NTRMix_FaceStyle_Single_UltraTile1824.api-prompt.txt
C:\Users\a1700\Documents\ComfyUI\user\default\workflows\Active_Strong\FINAL_Anima_NTRMix_FaceStyle_Single_UltraTile1824.api-prompt.txt
```

POST 请求示例：

```text
C:\Users\a1700\Desktop\comfyui调查\work\FINAL_Anima_NTRMix_FaceStyle_Single_UltraTile1824.request-example.json
```

API prompt 默认是白发魔女漂亮脸样例。换角色时主要改：

```text
54.inputs.text          正向角色/服装/场景 prompt
57.inputs.seed          第一遍生成 seed
134.inputs.seed         tiled refine seed，建议设为第一遍 seed + 1000000
180.inputs.filename_prefix  UltraSharp 预览图文件名前缀
169.inputs.filename_prefix  最终 tiled refine 图文件名前缀
```

这个 API prompt 已验证 JSON 可解析，且 ComfyUI `/object_info` 识别全部节点类型。

导出后实际提交 `/prompt` 验证成功，输出：

```text
C:\Users\a1700\Documents\ComfyUI\output\NTRMIX_FACE_STYLE_API_ULTRASHARP_PRE_00001_.png
C:\Users\a1700\Documents\ComfyUI\output\NTRMIX_FACE_STYLE_API_REFINED_00001_.png
```

### 最有效的结论

OC 最适合这套写法。白发魔女、黑发军服、蓝发赛博偶像、和风鬼族、哥特修女都能保持同一种好看的脸，同时角色题材有明显差异。

最稳定的脸部锚点改成：

```text
colored eyelashes, [eye style], [expression], blush, [mouth detail]
```

角色卡默认推荐：

```text
colored eyelashes, half-closed eyes, faint smile, blush, parted lips
colored eyelashes, sharp eyes, smug smile, blush, closed mouth
```

如果要更接近用户给的那张样图，可以临时配：

```text
small open mouth, light sweat, spoken question mark,
cowboy shot, from side, looking at viewer
```

这些词会让脸占画面更大，眼睛、脸红、嘴型更接近样图。但它们只适合“样图复刻/吐槽表情”，不适合作为角色卡默认值。

### OC 推荐优先级

最推荐：

```text
white hair / black hair / silver hair
long hair / braid / hime cut / ponytail
blue eyes / red eyes / purple eyes / golden eyes
colored eyelashes, half-closed eyes / sharp eyes / sleepy eyes
faint smile / smug smile / expressionless
closed mouth / parted lips
three-quarter view / profile / over shoulder
```

次推荐：

```text
wide-eyed, bright smile
faint smile, sleepy eyes
sharp eyes, smug smile
```

这些也能出好脸，但会偏离用户样图的“半眯、俏皮、微脸红”味道。

### 二创角色结论

二创可以用，但要分两种目标：

如果目标是“这个角色被 NTRMix 画得很好看”，可以把脸部锚点写强：

```text
[character], [series], [official hair], [official eyes],
colored eyelashes, half-closed eyes, faint smile, blush, parted lips,
[new outfit], three-quarter view, upper body, eyes toward viewer
```

如果目标是“官方识别度很强”，脸部锚点不能压过角色标志物。二创必须加强官方特征：

```text
[character], [series],
[signature hair], [signature accessory], [signature outfit], [signature prop],
colored eyelashes, [milder expression], blush,
closed mouth, three-quarter view, eyes toward viewer
```

实测观察：

- Miku：保留了蓝绿色双马尾和魔女换装，适合“初音二创换装”；脸好看。
- Raiden：紫发长辫和气质保留较好，但会被 NTRMix 统一成更媚的脸。
- Frieren：白发、精灵耳、魔女感能保留，但官方感会变弱。
- 2B：脸好看，但 `black blindfold` 没稳定执行，二创识别度不足。要画 2B 时应加强 `black blindfold, covered eyes, short white bob hair, black gothic dress, mole under mouth`，并减少会改变脸的表情词。

### 二创修正版模板

适合“好看优先”的二创：

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, [character \(series\)], [series],
[official hair color], [official hairstyle], [official eye color], [signature accessory],
colored eyelashes, half-closed eyes, faint smile, blush, parted lips,
[outfit or alternate costume],
upper body, three-quarter view, eyes toward viewer,
[simple scene], [simple lighting]
```

适合“识别度优先”的二创：

```text
masterpiece, best quality, score_9, score_8, score_7, @ntrmixstyle,
1girl, solo, [character \(series\)], [series],
[signature hair], [signature accessory], [signature outfit], [signature prop],
colored eyelashes, faint smile, blush, closed mouth,
three-quarter view, eyes toward viewer,
[simple scene], [simple lighting]
```

识别度优先时，少用 `jitome, open mouth, sweat, spoken question mark`，因为它们会把角色统一拉向 NTRMix 样图脸。好看优先时也不要每张都用，建议只给 4 张角色卡中的 1 张。

### 最终推荐工作流

1. 先写角色身份和头发眼睛。
2. 加脸部槽位：`colored eyelashes, [eye style], [expression], blush, [mouth detail]`。
3. 加具体服装部件，不要只写 `dress`。
4. 加镜头，但每张轮换：`three-quarter view`、`profile`、`over shoulder`、`from above`、`from below`。
5. 场景保持简单，不要让场景抢脸。
6. 嘴型默认 `closed mouth` 或 `parted lips`；只有说话/惊讶/唱歌才用 `open mouth`。
7. 二创角色先测一张；如果不像角色，减少脸部锚点强度，增加官方标志物。

一句话版：

```text
角色像不像靠身份和标志物，脸好不好看靠 colored eyelashes + 眼神 + 表情 + 嘴型，画面是否多样靠镜头/视线轮换；open mouth 和 looking at viewer 只是可选项，不是默认项。
```
