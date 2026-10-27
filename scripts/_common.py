#!/usr/bin/env python3
"""
Shared helpers for the qwen-tts skill.

Design rules:
- NO hardcoded model or voice names. Models/capabilities come from the official
  Alibaba Cloud Model Studio docs (cached locally); custom voices come from the
  voice-enrollment service.
- Third-party models (model IDs containing "/", e.g. "Vendor/model") are excluded.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import dashscope

# ---------------------------------------------------------------------------
# Official doc sources
# ---------------------------------------------------------------------------
URL_MODELS_INDEX = "https://help.aliyun.com/zh/model-studio/models#音频与语音"
URL_TTS_MODELS = "https://help.aliyun.com/zh/model-studio/tts-model"
URL_VOICE_LIST_INDEX = "https://help.aliyun.com/zh/model-studio/tts-voice-list/"
URL_QWEN_TTS_VOICES = "https://help.aliyun.com/zh/model-studio/qwen-tts-voice-list"
URL_COSYVOICE_VOICES = "https://help.aliyun.com/zh/model-studio/cosyvoice-voice-list"
URL_QWEN_AUDIO_VOICES = "https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list"
URL_SSML_LATEX = "https://help.aliyun.com/zh/model-studio/ssml-latex-user-guide"

CACHE_DIR = os.path.expanduser("~/.cache/qwen-tts")
CACHE_TTL_SECONDS = 600

REGION_ENDPOINTS = {
    "beijing": ("https://dashscope.aliyuncs.com/api/v1",
                "wss://dashscope.aliyuncs.com/api-ws/v1/inference"),
    "singapore": ("https://dashscope-intl.aliyuncs.com/api/v1",
                  "wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference"),
}

# Custom (cloned / designed) voice IDs end with a 32-hex unique id.
CUSTOM_VOICE_RE = re.compile(r"^(?P<model>.+?)-(?:vd-)?[a-z0-9]{1,10}-[0-9a-f]{32}$")


class SkillError(Exception):
    """User-facing error with an actionable message."""


# ---------------------------------------------------------------------------
# Auth & region
# ---------------------------------------------------------------------------
def get_api_key(passed_key=None):
    if passed_key and passed_key != "auto":
        return passed_key
    key = os.getenv("DASHSCOPE_API_KEY")
    if key:
        return key
    env_paths = [
        os.path.expanduser("~/.env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        os.path.expanduser("~/skills/.env"),
        os.path.expanduser("~/.claude/.env"),
    ]
    for env_path in env_paths:
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    if line.startswith("DASHSCOPE_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip("'\"")
                        if key:
                            return key
    return None


def init_dashscope(api_key=None, region="beijing"):
    """Resolve API key and configure BOTH http and websocket endpoints."""
    key = get_api_key(api_key)
    if not key:
        raise SkillError("DASHSCOPE_API_KEY 未设置：请设置环境变量、写入 ~/.env，或传入 --api-key。")
    if region not in REGION_ENDPOINTS:
        raise SkillError(f"不支持的 region: {region}，可选 {list(REGION_ENDPOINTS)}")
    http_url, ws_url = REGION_ENDPOINTS[region]
    dashscope.api_key = key
    dashscope.base_http_api_url = http_url
    dashscope.base_websocket_api_url = ws_url
    return key


# ---------------------------------------------------------------------------
# Doc fetching with cache
# ---------------------------------------------------------------------------
def _cache_path(name):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, name)


def fetch_doc_content(url, use_cache=True):
    """Return the HTML body of an Aliyun help page (cached for CACHE_TTL_SECONDS)."""
    cache_file = _cache_path(re.sub(r"[^a-zA-Z0-9]+", "_", url)[-80:] + ".html")
    if use_cache and os.path.exists(cache_file) and time.time() - os.path.getmtime(cache_file) < CACHE_TTL_SECONDS:
        with open(cache_file, "r", encoding="utf-8") as f:
            return f.read()

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8")
    content = html
    m = re.search(r"window\.__ICE_PAGE_PROPS__=(\{.*?\});\s*</script>", html, re.DOTALL)
    if m:
        try:
            content = json.loads(m.group(1))["docDetailData"]["storeData"]["data"]["content"]
        except Exception:
            pass
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write(content)
    return content


def is_third_party(model_id):
    return "/" in (model_id or "")


def model_family(model_id):
    if model_id.startswith("qwen-audio"):
        return "Qwen-Audio-TTS"
    if model_id.startswith("cosyvoice"):
        return "CosyVoice"
    if model_id.startswith("qwen3-tts") or model_id.startswith("qwen-tts"):
        return "Qwen-TTS"
    return "Other"


def synth_backend(model_id):
    """Which SDK path this skill uses for a model; None = not callable by this skill."""
    if is_third_party(model_id) or model_id.endswith("-realtime"):
        return None
    fam = model_family(model_id)
    if fam in ("CosyVoice", "Qwen-Audio-TTS"):
        return "tts_v2"
    if fam == "Qwen-TTS":
        return "multimodal"
    return None


def fetch_official_models(use_cache=True):
    """Parse the capability matrix from the official TTS model doc.

    Returns list of dicts: model_id, family, api, voice_clone, voice_design,
    instruct (bool|None), callable (bool). Third-party models are dropped.
    """
    from bs4 import BeautifulSoup

    content = fetch_doc_content(URL_TTS_MODELS, use_cache=use_cache)
    soup = BeautifulSoup(content, "html.parser")
    models, seen = [], set()

    def yes(v):
        if v is None:
            return None
        return v.strip() == "支持"

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        if "模型 ID" not in headers:
            continue
        for r in rows[1:]:
            cols = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
            row = dict(zip(headers, cols))
            mid = row.get("模型 ID")
            if not mid or mid in seen or is_third_party(mid):
                continue
            seen.add(mid)
            models.append({
                "model_id": mid,
                "family": row.get("系列") or model_family(mid),
                "api": row.get("API", "-"),
                "voice_clone": yes(row.get("声音复刻")),
                "voice_design": yes(row.get("声音设计")),
                "instruct": yes(row.get("指令控制")),
                "callable": synth_backend(mid) is not None,
            })
    if not models:
        raise SkillError(
            f"未能从官方文档解析出任何模型（页面结构可能已变更）：{URL_TTS_MODELS}\n"
            "请人工打开该页面确认，或删除缓存目录 ~/.cache/qwen-tts 后重试。"
        )
    return models


def get_model_info(model_id):
    """Return capability dict for a model, or None if unknown / docs unavailable."""
    try:
        for m in fetch_official_models():
            if m["model_id"] == model_id:
                return m
    except Exception as e:  # network / parse failure must not block synthesis
        print(f"Warning: 无法获取官方模型能力矩阵（{e}），跳过能力校验。", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Custom voice binding
# ---------------------------------------------------------------------------
def is_custom_voice(voice):
    return bool(voice and CUSTOM_VOICE_RE.match(voice))


def resolve_custom_voice_model(voice, api_key):
    """Query voice-enrollment for the model a custom voice is bound to."""
    from dashscope.audio.tts_v2 import VoiceEnrollmentService
    try:
        info = VoiceEnrollmentService(api_key=api_key).query_voice(voice)
        status = info.get("status")
        if status and status != "OK":
            print(f"Warning: 音色 {voice} 当前状态为 {status}，可能尚未就绪。", file=sys.stderr)
        if info.get("target_model"):
            return info["target_model"]
    except Exception as e:
        print(f"Warning: 查询音色绑定模型失败（{e}），改用 voice_id 前缀推断。", file=sys.stderr)
    m = CUSTOM_VOICE_RE.match(voice)
    return m.group("model") if m else None


def resolve_model_and_voice(model, voice, api_key):
    """Validate (model, voice). Model may be omitted only for custom voices."""
    if not voice:
        raise SkillError(
            "必须指定 --voice。可用音色请先查询：\n"
            "  python3 scripts/fetch_voices.py --recommend      # 官方内置音色\n"
            "  python3 scripts/clone_voice.py list              # 账号下的复刻/设计音色"
        )
    if model and is_third_party(model):
        raise SkillError(f"本 skill 不使用第三方模型（含 '/' 的模型名）：{model}")

    if is_custom_voice(voice):
        bound = resolve_custom_voice_model(voice, api_key)
        if not model:
            if not bound:
                raise SkillError(f"无法推断音色 {voice} 绑定的模型，请显式传入 --model。")
            print(f"Info: 自定义音色绑定模型为 {bound}，已自动使用。", file=sys.stderr)
            return bound, voice
        if bound and model != bound:
            raise SkillError(
                f"音色与模型不匹配：{voice} 绑定的是 {bound}，但传入了 --model {model}。\n"
                f"复刻/设计音色只能配合其绑定模型使用，请改用 --model {bound}（或省略 --model 自动推断）。"
            )
        return model, voice

    if not model:
        raise SkillError(
            "必须指定 --model（官方内置音色无法推断模型）。最新可用模型请先查询：\n"
            "  python3 scripts/fetch_voices.py --models"
        )
    return model, voice


# ---------------------------------------------------------------------------
# Text feature detection
# ---------------------------------------------------------------------------
LATEX_RE = re.compile(r"\$\$.+?\$\$|\$[^$\n]*\\[a-zA-Z]+[^$\n]*\$|\\\(.+?\\\)|\\\[.+?\\\]", re.DOTALL)


def is_ssml(text):
    return "<speak" in text and "</speak>" in text


def is_latex(text):
    return bool(LATEX_RE.search(text))


# ---------------------------------------------------------------------------
# Synthesis router
# ---------------------------------------------------------------------------
def _audio_format(fmt, sample_rate):
    from dashscope.audio.tts_v2 import AudioFormat
    candidates = {
        "wav": f"WAV_{sample_rate}HZ_MONO_16BIT",
        "pcm": f"PCM_{sample_rate}HZ_MONO_16BIT",
    }
    if fmt == "mp3":
        for kbps in ("256KBPS", "128KBPS"):
            name = f"MP3_{sample_rate}HZ_MONO_{kbps}"
            if hasattr(AudioFormat, name):
                return getattr(AudioFormat, name)
    elif fmt in candidates and hasattr(AudioFormat, candidates[fmt]):
        return getattr(AudioFormat, candidates[fmt])
    print(f"Warning: 不支持的格式/采样率组合 {fmt}@{sample_rate}，使用服务端默认格式。", file=sys.stderr)
    return AudioFormat.DEFAULT


def _convert_audio(src_bytes, src_ext, dst_path):
    """Convert audio bytes to dst_path's format using ffmpeg. Returns final path."""
    dst_ext = os.path.splitext(dst_path)[1].lstrip(".").lower()
    if dst_ext == src_ext or not dst_ext:
        with open(dst_path, "wb") as f:
            f.write(src_bytes)
        return dst_path
    if not shutil.which("ffmpeg"):
        fallback = os.path.splitext(dst_path)[0] + "." + src_ext
        with open(fallback, "wb") as f:
            f.write(src_bytes)
        print(f"Warning: 未安装 ffmpeg，无法转为 {dst_ext}，已保存为 {fallback}", file=sys.stderr)
        return fallback
    with tempfile.NamedTemporaryFile(suffix="." + src_ext, delete=False) as tmp:
        tmp.write(src_bytes)
        tmp_path = tmp.name
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp_path, dst_path], check=True)
    finally:
        os.unlink(tmp_path)
    return dst_path


def synthesize(text, output, model, voice, api_key, instructions=None,
               speech_rate=1.0, pitch_rate=1.0, volume=50,
               fmt="mp3", sample_rate=48000, language="Chinese"):
    """Synthesize one utterance and write it to `output`. Returns final file path."""
    backend = synth_backend(model)
    if backend is None:
        raise SkillError(
            f"模型 {model} 不能通过本 skill 调用（第三方模型、实时 WebSocket 模型或未知家族）。\n"
            "请运行 python3 scripts/fetch_voices.py --models 查看“本 skill 可调用”的模型。"
        )

    info = get_model_info(model)
    if info is None:
        print(f"Warning: 官方能力矩阵中未找到 {model}，可能是新模型或已下线，继续尝试调用。", file=sys.stderr)
    if instructions and info is not None and info.get("instruct") is False:
        raise SkillError(f"模型 {model} 不支持指令控制（Instruct）。请换用 --models 中“指令控制=支持”的模型，或去掉 --instructions。")
    if (is_ssml(text) or is_latex(text)) and backend == "multimodal":
        print(f"Notice: SSML/LaTeX 主要由 CosyVoice / Qwen-Audio 系列支持，当前模型 {model} 可能按普通文本朗读。", file=sys.stderr)

    out_dir = os.path.dirname(os.path.abspath(output))
    os.makedirs(out_dir, exist_ok=True)

    if backend == "tts_v2":
        from dashscope.audio.tts_v2 import SpeechSynthesizer
        kwargs = dict(model=model, voice=voice, format=_audio_format(fmt, sample_rate),
                      speech_rate=speech_rate, pitch_rate=pitch_rate, volume=volume)
        if instructions:
            kwargs["instruction"] = instructions
        audio = SpeechSynthesizer(**kwargs).call(text)
        if not audio:
            raise SkillError("合成返回空音频，请检查模型/音色是否匹配、文本是否为空。")
        with open(output, "wb") as f:
            f.write(audio)
        return output

    # backend == "multimodal" (Qwen-TTS)
    from dashscope import MultiModalConversation
    if (speech_rate, pitch_rate, volume) != (1.0, 1.0, 50):
        print("Notice: Qwen-TTS 接口不支持 speech_rate / pitch_rate / volume 参数，已忽略。", file=sys.stderr)
    kwargs = dict(model=model, api_key=api_key, text=text, voice=voice,
                  language_type=language, stream=False)
    if instructions:
        kwargs["instructions"] = instructions
        kwargs["optimize_instructions"] = True
    resp = MultiModalConversation.call(**kwargs)
    if resp.status_code != 200:
        raise SkillError(f"Qwen-TTS 调用失败：{resp.code} - {resp.message}")
    audio_info = (resp.output or {}).get("audio") or {}
    if audio_info.get("data"):
        raw = base64.b64decode(audio_info["data"])
    elif audio_info.get("url"):
        import requests
        r = requests.get(audio_info["url"], timeout=60)
        r.raise_for_status()
        raw = r.content
    else:
        raise SkillError(f"Qwen-TTS 未返回音频：{resp.output}")
    return _convert_audio(raw, "wav", output)


def emit_media(path):
    print(f"Audio saved to {path}")
    print(f"MEDIA: {os.path.abspath(path)}")
