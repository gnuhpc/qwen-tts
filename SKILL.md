---
name: qwen-tts
description: Generate speech and manage custom voices (voice cloning & voice design) with Alibaba Cloud Model Studio official TTS models (Qwen-Audio-TTS, CosyVoice, Qwen-TTS). Zero hardcoded models/voices — dynamically queries official docs and voice-enrollment API. Trigger on text-to-speech, voiceovers, narrations, voice cloning (声音复刻), voice design (声音设计), or querying available TTS models/voices.
metadata:
  {
    "openclaw":
      {
        "emoji": "🎙️",
        "requires": { "bins": ["python3"] },
        "install":
          [
            {
              "id": "pip",
              "kind": "exec",
              "command": "pip install -r requirements.txt",
              "label": "Install DashScope & Dependencies (pip)",
            },
          ],
      },
  }
---

# Alibaba Cloud Model Studio TTS Skill

支持阿里云百炼官方语音合成家族（**Qwen-Audio-TTS**、**CosyVoice**、**Qwen-TTS**）的语音合成、批量配音、**声音复刻（Voice Cloning）**与**声音设计（Voice Design）**全生命周期管理。

---

## ⚠️ 核心铁律（Agent 必读）

1. **禁止写死任何模型名或音色名**：所有脚本均无默认模型/音色。合成或复刻前，必须先通过下方的动态发现命令获取实时列表（内置 10 分钟本地缓存）。
2. **不使用第三方模型**：凡模型 ID 含斜杠 `/`（两段式 `Vendor/model`）的第三方模型一律已在代码层过滤并拦截，不得选用。
3. **自定义音色与模型严格绑定**：复刻/设计生成的 `voice_id` 只能配合创建时的 `target_model` 调用。使用自定义 `voice_id` 合成时**可省略 `--model`**，脚本会自动查询并绑定其所属模型；若显式传入不匹配的 `--model` 会直接报错拦截。
4. **删除操作必须先向用户确认**：非交互环境下 `clone_voice.py delete` 不带 `--yes` 会直接拒绝执行。Agent 执行删除前必须先征得用户明确同意，再加 `--yes` 调用。

---

## Step 1：动态查询模型与音色 (`fetch_voices.py`)

官方文档实时数据源：
- [百炼模型总览（音频与语音）](https://help.aliyun.com/zh/model-studio/models#音频与语音) · [语音合成模型选型与能力矩阵](https://help.aliyun.com/zh/model-studio/tts-model)
- [百炼 TTS 音色列表总入口](https://help.aliyun.com/zh/model-studio/tts-voice-list/)

```bash
# 1. 查询官方模型列表与能力矩阵（声音复刻 / 声音设计 / 指令控制 / 本 skill 可调用）
python3 scripts/fetch_voices.py --models --callable-only

# 2. 筛选支持“声音复刻”或“声音设计”的模型
python3 scripts/fetch_voices.py --models --clone-capable
python3 scripts/fetch_voices.py --models --design-capable

# 3. 查询三大官方家族的代表性推荐内置音色（或 --family cosyvoice|qwen-audio|qwen-tts）
python3 scripts/fetch_voices.py --recommend

# 4. 查询当前账号下的自定义（复刻/设计）音色
python3 scripts/fetch_voices.py --cloned-only
```

---

## Step 2：语音合成

### Mode 1：标准 / 高级单条合成 (`generate_tts.py`)

```bash
# 使用官方内置音色（--model 与 --voice 均必填）
python3 scripts/generate_tts.py \
  --model "<MODEL>" \
  --voice "<VOICE>" \
  --text "待合成文本" \
  --output "output.mp3"

# 使用自定义复刻/设计音色（可省略 --model，自动按音色绑定模型合成）
python3 scripts/generate_tts.py \
  --voice "<CUSTOM_VOICE_ID>" \
  --text "待合成文本" \
  --output "output.mp3"

# 启用情感/场景指令（仅限 --models 中“指令控制 = ✅”的模型）
python3 scripts/generate_tts.py \
  --model "<INSTRUCT_CAPABLE_MODEL>" \
  --voice "<VOICE>" \
  --instructions "<INSTRUCT_TEXT>" \
  --text "待合成文本" \
  --output "output.mp3"
```

- **高级特性**（Instruct 模板、`<speak>` SSML 标签、`$...$` LaTeX 数学公式）详见 [references/ssml-latex.md](references/ssml-latex.md)。
- **可选参数**：`--speech-rate` (0.5–2.0)、`--pitch-rate` (0.5–2.0)、`--volume` (0–100)、`--format` (`mp3`|`wav`|`pcm`)、`--sample-rate` (`8000`–`48000`)、`--region` (`beijing`|`singapore`，同时切换 HTTP 与 WebSocket 端点)、`--batch-file <scenes.json>`。

### Mode 2：位置参数快速口播 (`narrate.py`)

```bash
# <voice> 必填；当 <voice> 为自定义 voice_id 时 [model] 可省略
python3 scripts/narrate.py "<text>" "<output.mp3>" auto 1.0 "<VOICE>" "[MODEL]"
```

### Mode 3：多场景批量生成 (`generate_scenes.py`)

```bash
python3 scripts/generate_scenes.py \
  --input scenes.json \
  --output-dir audio/ \
  --voice "<VOICE>" \
  --model "<MODEL>"
```

---

## Step 3：自定义音色管理 CRUD (`clone_voice.py`)

### ① 增：声音复刻 (`create`) — 从真人音频样本复刻
本地文件会先经 `ffprobe` 预检（时长建议 10–20s、不超过 60s），自动上传至 DashScope 并在创建结束后**自动清理云端临时文件**。

```bash
python3 scripts/clone_voice.py create \
  --audio "/path/to/sample.mp3" \
  --model "<CLONE_CAPABLE_MODEL>" \
  --prefix "myvoice" \
  --test-text "复刻完成后的自检试听文本。" \
  --test-output "clone_test.mp3"
```

### ② 增：声音设计 (`design`) — 无录音样本，用文字描述创造音色
```bash
python3 scripts/clone_voice.py design \
  --model "<DESIGN_CAPABLE_MODEL>" \
  --prefix "narrator" \
  --prompt "温暖低沉的中年男声，语速平稳，吐字清晰，适合纪录片解说。" \
  --preview-text "各位观众朋友，大家好，欢迎收看今天的节目。" \
  --preview-output "design_preview.wav"
```

### ③ 查：列表与详情 (`list` / `query`)
```bash
python3 scripts/clone_voice.py list --all
python3 scripts/clone_voice.py query "<CUSTOM_VOICE_ID>"
```

### ④ 改：更换复刻音频样本 (`update`)
保持 `voice_id` 不变，用新音频重新提取声纹（同样自动清理临时上传文件）：
```bash
python3 scripts/clone_voice.py update "<CUSTOM_VOICE_ID>" \
  --audio "/path/to/new_sample.mp3" \
  --test-text "更新后的声音试听。"
```

### ⑤ 删：删除音色 (`delete`) 与清理临时文件 (`cleanup-uploads`)
```bash
# 删除音色（Agent 必须先向用户确认，再带 --yes）
python3 scripts/clone_voice.py delete "<CUSTOM_VOICE_ID>" --yes

# 清理云端残留的临时上传音频（不带 --yes 为 dry-run 预览）
python3 scripts/clone_voice.py cleanup-uploads --yes
```
