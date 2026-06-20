# Anima + NTRMix 特色二次元人物 Prompt 教程

测试/修订日期：2026-06-17  
主模型：`anima_baseV10` / `anima-base-v1.0.safetensors`  
文本编码器：`qwen_3_06b_base`  
VAE：`qwen_image_vae`  
主风格 LoRA：`ntrmix_style_anima_b1_v1.safetensors`  
触发词：`@ntrmixstyle`

## 先纠正方向
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
