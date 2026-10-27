# Instruct / SSML / LaTeX 高级特性参考

> 官方最新文档：[SSML 与 LaTeX 使用指南](https://help.aliyun.com/zh/model-studio/ssml-latex-user-guide)
> 各模型与音色对 SSML / Instruct 的支持情况以 `python3 scripts/fetch_voices.py --models` 和 `--recommend` 的实时输出为准。

## 1. Instruct（指令控制：语气、情绪、场景）

仅当 `fetch_voices.py --models` 中目标模型的 `指令控制 = ✅` 时可用（否则 `generate_tts.py` 会直接报错拦截）。

- **自然语言指令**（如 Qwen-Audio-TTS / 支持自由指令的模型）：
  ```bash
  --instructions "语速较快，带有明显的上扬语调，充满热情，适合新品发布直播。"
  ```
- **CosyVoice 固定模板指令**：
  - 仅情感：`"你说话的情感是<情感值>。"`
    可选情感值：`neutral`、`happy`、`sad`、`angry`、`fearful`、`surprised`、`disgusted`
  - 场景 + 情感：`"你正在进行<场景>，你说话的情感是<情感值>。"`
    可选场景：`闲聊互动`、`新闻播报`、`广告促销`、`比赛解说`、`一些儿童内容解说`

## 2. SSML（语音合成标记语言）

需选择 `SSML = ✅` 的音色，外层必须包裹 `<speak>...</speak>`：

- 停顿：`<break time="500ms"/>` 或 `<break time="1s"/>`
- 多音字纠偏：`<phoneme alphabet="py" ph="chong2 qing4">重庆</phoneme>`（1–5 声调，5 为轻声）
- 别名替换：`<sub alias="世界卫生组织">WHO</sub>`
- 数字/电话/日期读法：`<say-as interpret-as="telephone">13800138000</say-as>`
- 音效滤镜：`<speak effect="robot">...</speak>`（`robot`、`lolita`、`echo` 等）
- 背景音乐：`<speak bgm="https://example.com/bgm.wav" backgroundMusicVolume="30">...</speak>`

## 3. LaTeX 数学公式朗读（仅中文）

将公式包裹在 `$$...$$`、`$...$`（含 `\` 命令）、`\(...\)` 或 `\[...\]` 中（普通价格如 `$99` 不会被误判为公式）：

```text
这是一道一元二次方程：$x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}$，请认真作答。
```
