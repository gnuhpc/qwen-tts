# qwen-tts：阿里云百炼语音合成、声音复刻与声音设计 Skill

基于阿里云百炼（Model Studio / DashScope）官方语音合成体系的命令行工具集与 AI Agent 技能包，覆盖 **Qwen-Audio-TTS**、**CosyVoice**、**Qwen-TTS** 三大官方语音模型家族。

---

## ✨ 核心特性

- **三大官方语音家族全覆盖**：统一接入阿里云百炼 **Qwen-Audio-TTS**、**CosyVoice**、**Qwen-TTS** 系列模型，覆盖超拟真旁白、日常对话、多语种与多方言合成。
- **声音复刻（Voice Cloning）**：仅需 10~20 秒清晰真人录音（支持直接传入本地音频文件或公网 URL），即可快速克隆专属音色，并支持音色的创建、更新样本、列表检索、详情查询与删除（CRUD）。
- **声音设计（Voice Design）**：无需任何录音样本，直接用自然语言描述期望的声音特征（如性别、年龄感、音色质感、适用场景），即可从零生成定制音色并保存试听音频。
- **精细化表现力与发音控制**（详见 [references/ssml-latex.md](references/ssml-latex.md)）：
  - **Instruct 情感与场景控制**：支持用自然语言或情感模板指定说话情绪、语气与播报场景（如直播带货、新闻播报、有声书）。
  - **SSML 语音合成标记**：支持插入停顿、多音字注音纠偏、数字/电话规范读法、别名替换、声音特效与背景音乐混音。
  - **LaTeX 数学公式转语音**：自动将包含 `$...$` / `$$...$$` 的数学公式转为规范中文口语朗读，适合教育课件与科普视频。
- **单条口播与多场景批量配音**：支持单条精细参数合成（语速、语调、音量、采样率、`mp3`/`wav`/`pcm` 格式）、单行命令快速口播，以及视频多场景 JSON/文本分镜脚本的批量生成与失败自动重试。
- **模型与音色实时查询**：一键查询百炼官方最新可用模型、能力支持矩阵（是否支持复刻/设计/Instruct）、各家族推荐音色及当前账号下的私有定制音色。

---

## 📦 安装与依赖

### 1. 🤖 让 AI Agent 自动安装（推荐）

直接复制以下 Prompt 发送给你的 AI Agent（如 Claude Code、Codex、Antigravity、OpenClaw、Cursor 等）：

```text
请帮我安装 qwen-tts 技能：
1. 将 https://github.com/gnuhpc/qwen-tts.git 克隆到当前环境的 skills 目录（如 ~/.gemini/skills/qwen-tts 或 ~/.claude/skills/qwen-tts，若已存在则 git pull 更新）；
2. 安装 Python 依赖：pip install -r requirements.txt；
3. 检查系统是否已安装 ffmpeg/ffprobe，并检查 ~/.env 或环境变量中是否已配置 DASHSCOPE_API_KEY（若未配置请提示我如何设置）；
4. 运行 python3 scripts/fetch_voices.py --models --callable-only 验证安装是否成功。
```

### 2. 手动安装与 Python 依赖

```bash
git clone https://github.com/gnuhpc/qwen-tts.git
cd qwen-tts
pip install -r requirements.txt
```

`requirements.txt` 包含：
- `dashscope>=1.20.0`
- `requests>=2.25.0`
- `beautifulsoup4>=4.12.0`

### 3. 可选系统工具（推荐安装）

- `ffmpeg` / `ffprobe`：用于本地复刻样本的时长/采样率预检，以及 `Qwen-TTS` 输出音频格式的自动转换。
  ```bash
  # macOS
  brew install ffmpeg
  ```

---

## 🔑 API Key 配置方式（往哪放？）

前往 [阿里云百炼控制台 - API-Key 管理](https://bailian.console.aliyun.com/?apiKey=1) 获取 `DASHSCOPE_API_KEY`。

本技能所有脚本均通过统一的 `get_api_key()` 按以下**优先级从高到低**自动查找 API Key（任选一种配置即可，**切勿将 Key 硬编码进代码文件**）：

| 优先级 | 配置位置 | 示例 |
| :---: | :--- | :--- |
| **1** | 命令行参数 `--api-key` | `--api-key "sk-xxxxxxxx"` |
| **2** | 系统环境变量 `DASHSCOPE_API_KEY` | `export DASHSCOPE_API_KEY="sk-xxxxxxxx"`（可写入 `~/.zshrc`） |
| **3** | 用户主目录 `~/.env`（**推荐**） | 在 `~/.env` 中添加一行：`DASHSCOPE_API_KEY=sk-xxxxxxxx` |
| **4** | 本技能根目录 `.env` | 在 `/path/to/qwen-tts/.env` 中添加：`DASHSCOPE_API_KEY=sk-xxxxxxxx` |
| **5** | `~/skills/.env` 或 `~/.claude/.env` | 在对应文件中添加：`DASHSCOPE_API_KEY=sk-xxxxxxxx` |

---

## 🚀 功能与用法指南

### 一、 动态查询模型与音色 (`scripts/fetch_voices.py`)

在合成或复刻前，先查询当前可用的官方模型与音色：

```bash
# 1. 查看百炼官方语音合成模型与能力矩阵（声音复刻 / 声音设计 / 指令控制 / 本 skill 可调用）
python3 scripts/fetch_voices.py --models --callable-only

# 2. 筛选支持“声音复刻”或“声音设计”的模型
python3 scripts/fetch_voices.py --models --clone-capable
python3 scripts/fetch_voices.py --models --design-capable

# 3. 查看各家族代表性推荐官方音色（或用 --family cosyvoice|qwen-audio|qwen-tts 按家族筛选）
python3 scripts/fetch_voices.py --recommend

# 4. 查看当前账号下已创建的自定义（复刻/设计）音色
python3 scripts/fetch_voices.py --cloned-only

# 5. 输出 JSON 格式或强制刷新缓存（跳过 10 分钟本地缓存）
python3 scripts/fetch_voices.py --models --format json --no-cache
```

---

### 二、 语音合成 (`scripts/generate_tts.py` / `narrate.py` / `generate_scenes.py`)

#### 1. 标准与高级单条合成 (`generate_tts.py`)

```bash
# ① 使用官方内置音色合成（--model 与 --voice 均必填）
python3 scripts/generate_tts.py \
  --model "<MODEL>" \
  --voice "<VOICE>" \
  --text "大家好，欢迎体验语音合成服务。" \
  --output "output.mp3"

# ② 使用自定义（复刻/设计）音色合成（可省略 --model，自动匹配音色绑定的模型）
python3 scripts/generate_tts.py \
  --voice "<CUSTOM_VOICE_ID>" \
  --text "大家好，这是使用我的专属复刻音色合成的语音。" \
  --output "custom_output.mp3"

# ③ 指令控制（Instruct，仅限 --models 中“指令控制 = ✅”的模型）
python3 scripts/generate_tts.py \
  --model "<INSTRUCT_CAPABLE_MODEL>" \
  --voice "<VOICE>" \
  --instructions "你正在进行广告促销，你说话的情感是happy。" \
  --text "限时五折特惠，千万不要错过！" \
  --output "promo.mp3"

# ④ SSML 标记与 LaTeX 数学公式合成（需选择支持对应特性的模型与音色）
python3 scripts/generate_tts.py \
  --model "<MODEL>" \
  --voice "<VOICE>" \
  --text '<speak>请注意，<break time="500ms"/>我们要去<phoneme alphabet="py" ph="chong2 qing4">重庆</phoneme>开会。</speak>' \
  --output "ssml.mp3"
```

**常用可选参数**：
- `--speech-rate`：语速倍率 `0.5` ~ `2.0`（默认 `1.0`）
- `--pitch-rate`：语调倍率 `0.5` ~ `2.0`（默认 `1.0`）
- `--volume`：音量 `0` ~ `100`（默认 `50`）
- `--format`：`mp3` | `wav` | `pcm`（默认 `mp3`）
- `--sample-rate`：`8000` | `16000` | `22050` | `24000` | `44100` | `48000`（默认 `48000`）
- `--region`：`beijing`（默认）| `singapore`（同时切换 HTTP 与 WebSocket 接入点）

#### 2. 位置参数快速口播 (`narrate.py`)

```bash
# 语法：narrate.py <text> <output> <api_key|auto> <speech_rate> <voice> [model]
# 当 <voice> 为自定义音色 ID 时，末尾的 [model] 可省略
python3 scripts/narrate.py "大家好，欢迎收看本期视频。" "speech.mp3" auto 1.0 "<VOICE>" "<MODEL>"
```

#### 3. 视频多场景批量配音 (`generate_scenes.py`)

支持 JSON 数组文件（`["场景1...", "场景2..."]`）、`{"scenes": [...]}` 或按行分隔的纯文本文件，内置失败重试：

```bash
python3 scripts/generate_scenes.py \
  --input scenes.json \
  --output-dir audio/ \
  --voice "<VOICE>" \
  --model "<MODEL>" \
  --speech-rate 1.0
```

---

### 三、 自定义音色管理 CRUD (`scripts/clone_voice.py`)

#### 1. 增：声音复刻 (`create`)
提供一段 **10~20 秒**（不超过 60 秒）清晰、无背景噪音的单人音频（本地文件路径或公网 URL）：

```bash
python3 scripts/clone_voice.py create \
  --audio "/path/to/sample.mp3" \
  --model "<CLONE_CAPABLE_MODEL>" \
  --prefix "myvoice" \
  --test-text "复刻完成后的自检试听句子。" \
  --test-output "clone_test.mp3"
```

#### 2. 增：声音设计 (`design`)
无需音频样本，通过文字描述生成全新虚拟音色并保存试听文件：

```bash
python3 scripts/clone_voice.py design \
  --model "<DESIGN_CAPABLE_MODEL>" \
  --prefix "narrator" \
  --prompt "温暖低沉的中年男声，语速平稳，吐字清晰，适合纪录片解说。" \
  --preview-text "各位观众朋友，大家好，欢迎收看今天的节目。" \
  --preview-output "design_preview.wav"
```

#### 3. 查：列出音色与查询详情 (`list` / `query`)

```bash
# 列出账号下全部自定义音色（--all 自动翻页，--prefix 按前缀筛选，--json 输出 JSON）
python3 scripts/clone_voice.py list --all

# 查询单个音色的详细状态、创建时间与绑定模型
python3 scripts/clone_voice.py query "<CUSTOM_VOICE_ID>"
```

#### 4. 改：更换复刻音频样本 (`update`)
保持 `voice_id` 不变，使用新音频样本重新提取声纹：

```bash
python3 scripts/clone_voice.py update "<CUSTOM_VOICE_ID>" \
  --audio "/path/to/new_sample.mp3" \
  --test-text "更新样本后的试听效果。"
```

#### 5. 删：删除音色与清理云端临时文件 (`delete` / `cleanup-uploads`)

```bash
# 删除指定自定义音色（非交互环境下必须带 --yes）
python3 scripts/clone_voice.py delete "<CUSTOM_VOICE_ID>" --yes

# 清理本技能上传至 DashScope 文件存储的临时音频样本（不加 --yes 为预览模式）
python3 scripts/clone_voice.py cleanup-uploads --yes
```

---

## 📂 目录结构

```text
qwen-tts/
├── SKILL.md                   # AI Agent 技能指令与交互规范
├── README.md                  # 项目功能、配置与使用手册（本文档）
├── requirements.txt           # Python 依赖声明
├── references/
│   └── ssml-latex.md          # Instruct / SSML / LaTeX 高级语法参考
└── scripts/
    ├── _common.py             # 公共核心：鉴权、地域切换、文档缓存解析、绑定校验、合成路由
    ├── fetch_voices.py        # 官方模型能力矩阵与音色列表实时拉取工具
    ├── generate_tts.py        # 单条/批量语音合成主入口
    ├── generate_scenes.py     # 多场景分镜批量语音生成工具
    ├── narrate.py             # 位置参数快速口播合成脚本
    └── clone_voice.py         # 自定义音色（声音复刻 & 声音设计）增删改查 CLI
```
