#!/usr/bin/env python3
"""
Custom voice lifecycle CLI (voice-enrollment service) for Alibaba Cloud Model Studio.

  create          [增] 声音复刻：从音频样本创建音色（本地文件自动上传，用完自动删除临时文件）
  design          [增] 声音设计：用文字描述创建全新音色，并保存试听音频
  update          [改] 用新音频样本更新已有复刻音色（voice_id 不变）
  list            [查] 列出账号下所有自定义音色（--all 自动翻页）
  query / get     [查] 查询单个音色详情、状态与绑定模型
  delete          [删] 删除音色（Agent 必须先征得用户确认，再带 --yes 执行）
  cleanup-uploads 清理本 skill 上传到 DashScope 文件存储的临时样本

No model is hardcoded: --model is required for create/design.
Find capable models with:  python3 scripts/fetch_voices.py --models --clone-capable   (or --design-capable)
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time

import requests
from dashscope import Files
from dashscope.audio.tts_v2 import VoiceEnrollmentService

import dashscope
from _common import (SkillError, emit_media, get_model_info, init_dashscope,
                     is_third_party, synthesize)

UPLOAD_TAG = "qwen-tts-skill:voice-sample"
POLL_MAX, POLL_INTERVAL = 30, 2


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def sanitize_prefix(prefix):
    clean = re.sub(r"[^a-z0-9]", "", (prefix or "").lower())[:9]
    if not clean:
        raise SkillError("--prefix 必须包含小写字母或数字（最多 9 位）。")
    if clean != prefix:
        print(f"Info: prefix 已规范化为 '{clean}'", file=sys.stderr)
    return clean


def check_model(model, capability):
    """capability: 'voice_clone' | 'voice_design'"""
    if is_third_party(model):
        raise SkillError(f"本 skill 不使用第三方模型（含 '/' 的模型名）：{model}")
    info = get_model_info(model)
    label = {"voice_clone": "声音复刻", "voice_design": "声音设计"}[capability]
    flag = {"voice_clone": "--clone-capable", "voice_design": "--design-capable"}[capability]
    if info is None:
        print(f"Warning: 官方能力矩阵中未找到 {model}，无法确认是否支持{label}，继续尝试。", file=sys.stderr)
    elif info.get(capability) is False:
        raise SkillError(f"模型 {model} 不支持{label}。请运行 python3 scripts/fetch_voices.py --models {flag} 选择模型。")
    elif not info.get("callable"):
        print(f"Warning: 模型 {model} 支持{label}，但本 skill 无法用它合成语音。", file=sys.stderr)


def precheck_audio(path):
    """Validate a local sample with ffprobe (duration 10–20s recommended, ≤60s)."""
    if not shutil.which("ffprobe"):
        print("Notice: 未安装 ffprobe，跳过音频预检。", file=sys.stderr)
        return
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=sample_rate,channels:format=duration", "-of", "json", path],
            capture_output=True, text=True, check=True).stdout
        meta = json.loads(out)
        dur = float(meta.get("format", {}).get("duration", 0))
        stream = (meta.get("streams") or [{}])[0]
        sr = int(stream.get("sample_rate", 0) or 0)
    except Exception as e:
        print(f"Warning: 音频预检失败（{e}），继续提交。", file=sys.stderr)
        return
    print(f"Audio precheck: duration={dur:.1f}s sample_rate={sr}Hz channels={stream.get('channels')}")
    if dur < 5:
        raise SkillError(f"样本仅 {dur:.1f}s，过短（至少需要一段 >5s 的连续语音，建议 10–20s）。")
    if dur > 60:
        print("Warning: 样本超过 60s，官方建议 10–20s，过长可能被截断或失败。", file=sys.stderr)
    elif not 10 <= dur <= 20:
        print("Notice: 官方建议样本时长 10–20s。", file=sys.stderr)
    if sr and sr < 16000:
        print("Warning: 采样率低于 16kHz，复刻效果可能下降。", file=sys.stderr)


def resolve_audio(source, api_key):
    """Return (url, uploaded_file_id_or_None)."""
    if source.startswith(("http://", "https://")):
        return source, None
    path = os.path.expanduser(source)
    if not os.path.isfile(path):
        raise SkillError(f"本地音频不存在：{path}")
    precheck_audio(path)
    print(f"Uploading {path} ...")
    up = Files.upload(file_path=path, purpose="inference", description=UPLOAD_TAG, api_key=api_key)
    if up.status_code != 200 or not up.output.get("uploaded_files"):
        raise SkillError(f"上传失败：{up.code} - {up.message} {up.output}")
    file_id = up.output["uploaded_files"][0]["file_id"]
    info = Files.get(file_id=file_id, api_key=api_key)
    url = (info.output or {}).get("url") if info.status_code == 200 else None
    if not url:
        delete_upload(file_id, api_key)
        raise SkillError(f"获取上传文件 URL 失败：{info.code} - {info.message}")
    return url, file_id


def delete_upload(file_id, api_key):
    if not file_id:
        return
    try:
        r = Files.delete(file_id=file_id, api_key=api_key)
        if r.status_code == 200:
            print(f"Cleaned up temporary upload {file_id}")
        else:
            print(f"Warning: 临时文件 {file_id} 删除失败：{r.code} {r.message}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: 临时文件 {file_id} 删除失败：{e}", file=sys.stderr)


def wait_ready(service, voice_id):
    print("Waiting for voice deployment...")
    for i in range(POLL_MAX):
        status = service.query_voice(voice_id).get("status")
        print(f"  [{i + 1}/{POLL_MAX}] Status: {status}")
        if status == "OK":
            print("Voice is READY.")
            return
        if status in ("FAILED", "ERROR", "UNDEPLOYED"):
            raise SkillError(f"音色部署失败，状态：{status}")
        time.sleep(POLL_INTERVAL)
    print("Notice: 仍在部署中，稍后可用 `clone_voice.py query <voice_id>` 查看。")


def test_synth(voice_id, text, output, api_key, model):
    out = output or f"{voice_id.split('-')[-2]}_test.mp3"
    print(f"Generating test audio -> {out}")
    emit_media(synthesize(text, out, model, voice_id, api_key))


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_create(a, service, api_key):
    check_model(a.model, "voice_clone")
    prefix = sanitize_prefix(a.prefix)
    url, file_id = resolve_audio(a.audio, api_key)
    try:
        kwargs = {"language_hints": [a.language_hints]} if a.language_hints else {}
        print(f"Submitting clone: model={a.model} prefix={prefix}")
        voice_id = service.create_voice(target_model=a.model, prefix=prefix, url=url, **kwargs)
        print(f"Voice ID: {voice_id}")
        if a.wait:
            wait_ready(service, voice_id)
    finally:
        if not a.keep_upload:
            delete_upload(file_id, api_key)
    if a.test_text:
        test_synth(voice_id, a.test_text, a.test_output, api_key, a.model)


def cmd_design(a, service, api_key):
    check_model(a.model, "voice_design")
    prefix = sanitize_prefix(a.prefix)
    if not 15 <= len(a.preview_text) <= 200:
        raise SkillError("--preview-text 长度需在 15–200 字符之间。")
    if len(a.prompt) > 500:
        raise SkillError("--prompt 最长 500 字符。")
    payload = {
        "model": "voice-enrollment",
        "input": {"action": "create_voice", "target_model": a.model, "voice_prompt": a.prompt,
                  "preview_text": a.preview_text, "prefix": prefix,
                  "language_hints": [a.language_hints or "zh"]},
        "parameters": {"sample_rate": 24000, "response_format": "wav"},
    }
    print(f"Submitting voice design: model={a.model} prefix={prefix}")
    r = requests.post(f"{dashscope.base_http_api_url}/services/audio/tts/customization",
                      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                      json=payload, timeout=120)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200:
        raise SkillError(f"声音设计失败：HTTP {r.status_code} {body.get('code')} {body.get('message') or r.text[:300]}")
    out = body.get("output", {})
    voice_id = out.get("voice_id")
    print(f"Voice ID: {voice_id}")
    preview = out.get("preview_audio") or {}
    if preview.get("data"):
        ext = preview.get("response_format", "wav")
        path = a.preview_output or f"{prefix}_design_preview.{ext}"
        with open(path, "wb") as f:
            f.write(base64.b64decode(preview["data"]))
        print("Preview audio:")
        emit_media(path)
    if a.wait:
        wait_ready(service, voice_id)
    if a.test_text:
        test_synth(voice_id, a.test_text, a.test_output, api_key, a.model)


def cmd_update(a, service, api_key):
    url, file_id = resolve_audio(a.audio, api_key)
    try:
        print(f"Updating {a.voice_id} ...")
        service.update_voice(voice_id=a.voice_id, url=url)
        print("Update submitted.")
        if a.wait:
            wait_ready(service, a.voice_id)
    finally:
        if not a.keep_upload:
            delete_upload(file_id, api_key)
    if a.test_text:
        model = service.query_voice(a.voice_id).get("target_model")
        test_synth(a.voice_id, a.test_text, a.test_output, api_key, model)


def cmd_list(a, service, api_key):
    voices, page = [], a.page
    while True:
        batch = service.list_voices(prefix=a.prefix, page_index=page, page_size=a.page_size) or []
        voices.extend(batch)
        if not a.all or len(batch) < a.page_size:
            break
        page += 1
    if a.json:
        print(json.dumps(voices, ensure_ascii=False, indent=2))
        return
    if not voices:
        print("No custom voices found.")
        return
    print(f"{'Voice ID':<66} {'Model':<26} {'Type':<7} {'Status':<10} Created")
    print("-" * 128)
    for v in voices:
        vid = v.get("voice_id", "")
        vtype = "design" if "-vd-" in vid else "clone"
        print(f"{vid:<66} {v.get('target_model', ''):<26} {vtype:<7} {v.get('status', ''):<10} {v.get('gmt_create', '')}")
    if not a.all and len(voices) == a.page_size:
        print(f"(可能还有更多，使用 --all 或 --page {a.page + 1})")


def cmd_query(a, service, api_key):
    d = service.query_voice(a.voice_id)
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return
    print("Voice Details:")
    for k, v in d.items():
        print(f"  {k}: {v}")


def cmd_delete(a, service, api_key):
    if not a.yes:
        if not sys.stdin.isatty():
            raise SkillError("非交互环境下删除必须带 --yes（请先向用户确认）。")
        if input(f"确认删除音色 '{a.voice_id}'？此操作不可恢复 (y/N): ").lower() not in ("y", "yes"):
            print("已取消。")
            return
    service.delete_voice(a.voice_id)
    print(f"Voice '{a.voice_id}' deleted.")


def cmd_cleanup(a, service, api_key):
    targets, page = [], 1
    while True:
        r = Files.list(page=page, page_size=100, api_key=api_key)
        if r.status_code != 200:
            raise SkillError(f"列出文件失败：{r.code} {r.message}")
        files = r.output.get("files", [])
        for f in files:
            if f.get("description") == UPLOAD_TAG or f.get("file_id") in (a.file_id or []):
                targets.append(f)
        if len(files) < 100:
            break
        page += 1
    if not targets:
        print("没有需要清理的 skill 临时上传文件。")
        return
    for f in targets:
        print(f"  {f['file_id']}  {f.get('name')}  {f.get('gmt_create')}")
    if not a.yes:
        print(f"共 {len(targets)} 个文件（dry-run）。确认后加 --yes 执行删除。")
        return
    for f in targets:
        delete_upload(f["file_id"], api_key)


# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Custom voice CRUD (声音复刻 / 声音设计) for Alibaba Cloud Model Studio",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--api-key")
    p.add_argument("--region", default="beijing", choices=["beijing", "singapore"])
    sub = p.add_subparsers(dest="cmd")

    def add_common_test(sp):
        sp.add_argument("--no-wait", dest="wait", action="store_false", help="Do not poll until status=OK")
        sp.add_argument("--test-text", help="Synthesize this text with the new voice afterwards")
        sp.add_argument("--test-output", help="Output path for the test audio")

    c = sub.add_parser("create", help="[增] 声音复刻")
    c.add_argument("--audio", "-a", required=True, help="Local file or public http(s) URL")
    c.add_argument("--model", "-m", required=True, help="Target model (see fetch_voices.py --models --clone-capable)")
    c.add_argument("--prefix", "-p", required=True, help="Lowercase alphanumeric, <=9 chars")
    c.add_argument("--language-hints", help="e.g. zh / en")
    c.add_argument("--keep-upload", action="store_true", help="Keep the temporary uploaded file")
    add_common_test(c)

    d = sub.add_parser("design", help="[增] 声音设计（文字描述生成音色）")
    d.add_argument("--prompt", required=True, help="Voice description, <=500 chars (zh/en)")
    d.add_argument("--preview-text", required=True, help="Preview text, 15–200 chars")
    d.add_argument("--model", "-m", required=True, help="Target model (see fetch_voices.py --models --design-capable)")
    d.add_argument("--prefix", "-p", required=True, help="Lowercase alphanumeric, <=9 chars")
    d.add_argument("--language-hints", help="zh (default) / en")
    d.add_argument("--preview-output", help="Where to save the preview audio")
    add_common_test(d)

    u = sub.add_parser("update", help="[改] 用新样本更新复刻音色")
    u.add_argument("voice_id")
    u.add_argument("--audio", "-a", required=True)
    u.add_argument("--keep-upload", action="store_true")
    add_common_test(u)

    l = sub.add_parser("list", help="[查] 列出自定义音色")
    l.add_argument("--prefix")
    l.add_argument("--page", type=int, default=0)
    l.add_argument("--page-size", type=int, default=20)
    l.add_argument("--all", action="store_true", help="Fetch all pages")
    l.add_argument("--json", action="store_true")

    q = sub.add_parser("query", aliases=["get"], help="[查] 查询音色详情")
    q.add_argument("voice_id")
    q.add_argument("--json", action="store_true")

    x = sub.add_parser("delete", help="[删] 删除音色")
    x.add_argument("voice_id")
    x.add_argument("--yes", "-y", action="store_true", help="Skip prompt (Agent: only after user confirmation)")

    cl = sub.add_parser("cleanup-uploads", help="清理本 skill 上传的临时样本文件（默认 dry-run）")
    cl.add_argument("--file-id", action="append", help="Additionally delete this specific file_id (repeatable)")
    cl.add_argument("--yes", "-y", action="store_true")

    a = p.parse_args()
    if not a.cmd:
        p.print_help()
        return
    handlers = {"create": cmd_create, "design": cmd_design, "update": cmd_update, "list": cmd_list,
                "query": cmd_query, "get": cmd_query, "delete": cmd_delete, "cleanup-uploads": cmd_cleanup}
    try:
        api_key = init_dashscope(a.api_key, a.region)
        handlers[a.cmd](a, VoiceEnrollmentService(api_key=api_key), api_key)
    except SkillError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Exception: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
