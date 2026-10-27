#!/usr/bin/env python3
"""
Live model & voice discovery for Alibaba Cloud Model Studio speech synthesis.

Nothing is hardcoded: models + capabilities come from the official doc
(https://help.aliyun.com/zh/model-studio/tts-model, linked from
https://help.aliyun.com/zh/model-studio/models#音频与语音), official voices come
from the per-family voice-list pages, custom voices from the voice-enrollment API.
Third-party models (IDs containing "/") are excluded.
"""
import argparse
import json
import re
import sys

from _common import (URL_COSYVOICE_VOICES, URL_MODELS_INDEX, URL_QWEN_AUDIO_VOICES, URL_QWEN_TTS_VOICES,
                     URL_TTS_MODELS, URL_VOICE_LIST_INDEX, SkillError, fetch_doc_content,
                     fetch_official_models, init_dashscope)


def _flag(text_block, *names):
    for name in names:
        if re.search(rf"{re.escape(name)}\s*[：:]\s*支持", text_block):
            return True
        if re.search(rf"{re.escape(name)}\s*[：:]\s*不支持", text_block):
            return False
    return None


def parse_voices_table(html, family):
    """Parse any Model Studio voice-list page (Qwen-TTS, CosyVoice, Qwen-Audio)."""
    from bs4 import BeautifulSoup
    voices, seen = [], set()
    for r in BeautifulSoup(html, "html.parser").find_all("tr"):
        cols = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
        if not cols:
            continue
        block = " ".join(cols)
        vm = re.search(r"voice\s*参数\s*[：:]\s*([a-zA-Z0-9_.\-]+)", block)
        if not vm:
            continue
        vid = vm.group(1)
        if vid in seen:
            continue
        seen.add(vid)
        name_m = re.search(r"(?:音色)?名称\s*[：:]\s*([^\s]+)", block)
        trait_m = re.search(r"特质\s*[：:]\s*([^\s]+)", block)
        desc_m = re.search(r"描述\s*[：:]\s*([^\s（(]+)", block)
        desc = (trait_m.group(1) if trait_m else (desc_m.group(1) if desc_m else
                (cols[1] if len(cols) > 1 and len(cols[1]) <= 12 else "")))
        voices.append({
            "family": family,
            "voice": vid,
            "name": name_m.group(1) if name_m else vid,
            "desc": desc,
            "ssml": _flag(block, "SSML"),
            "instruct": _flag(block, "Instruct", "指令控制"),
        })
    return voices


def suggest_models(models):
    """Per family, the callable models in official-doc order (no hardcoding)."""
    out = {}
    for m in models:
        if m["callable"]:
            out.setdefault(m["family"], []).append(m["model_id"])
    return out


def fetch_custom_voices(models):
    from dashscope.audio.tts_v2 import VoiceEnrollmentService
    key = init_dashscope()
    caps = {m["model_id"]: m for m in models}
    voices, page = [], 0
    svc = VoiceEnrollmentService(api_key=key)
    while True:
        batch = svc.list_voices(page_index=page, page_size=50) or []
        for v in batch:
            vid, tm = v.get("voice_id", ""), v.get("target_model", "")
            cap = caps.get(tm, {})
            voices.append({
                "family": "Custom-Design" if "-vd-" in vid else "Custom-Clone",
                "voice": vid,
                "name": vid.split("-")[-2] if vid.count("-") >= 2 else vid,
                "desc": f"状态 {v.get('status')} | 创建 {v.get('gmt_create')}",
                "ssml": None,
                "instruct": cap.get("instruct"),
                "model": tm,
            })
        if len(batch) < 50:
            break
        page += 1
    return voices


def mark(v):
    return "✅" if v is True else ("❌" if v is False else "—")


def main():
    p = argparse.ArgumentParser(description="Live model & voice discovery (no hardcoded lists).")
    p.add_argument("--models", action="store_true", help="List official TTS models + capability matrix.")
    p.add_argument("--clone-capable", action="store_true", help="With --models: only models supporting 声音复刻.")
    p.add_argument("--design-capable", action="store_true", help="With --models: only models supporting 声音设计.")
    p.add_argument("--callable-only", action="store_true", help="With --models: only models this skill can call.")
    p.add_argument("--family", choices=["all", "qwen-tts", "cosyvoice", "qwen-audio"], default="all")
    p.add_argument("--recommend", action="store_true", help="A few representative voices per family.")
    p.add_argument("--include-cloned", action="store_true", help="Also list the account's custom voices.")
    p.add_argument("--cloned-only", action="store_true", help="Only list the account's custom voices.")
    p.add_argument("--no-cache", action="store_true", help="Bypass the 10-minute doc cache.")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    a = p.parse_args()

    try:
        models = fetch_official_models(use_cache=not a.no_cache)
    except SkillError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if a.models:
        rows = [m for m in models
                if (not a.clone_capable or m["voice_clone"])
                and (not a.design_capable or m["voice_design"])
                and (not a.callable_only or m["callable"])]
        if a.format == "json":
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return
        print("\n### 🤖 百炼语音合成官方模型与能力矩阵（实时抓取，已排除第三方模型）\n")
        print(f"> 数据源：[模型总览·音频与语音]({URL_MODELS_INDEX}) · [语音合成模型选型]({URL_TTS_MODELS})\n")
        print("| 模型 ID | 系列 | API | 声音复刻 | 声音设计 | 指令控制 | 本 skill 可调用 |")
        print("| :--- | :--- | :--- | :---: | :---: | :---: | :---: |")
        for m in rows:
            print(f"| `{m['model_id']}` | {m['family']} | {m['api']} | {mark(m['voice_clone'])} | "
                  f"{mark(m['voice_design'])} | {mark(m['instruct'])} | {mark(m['callable'])} |")
        print()
        return

    suggestions = suggest_models(models)
    results = []
    if a.cloned_only or a.include_cloned:
        try:
            results.extend(fetch_custom_voices(models))
        except Exception as e:
            print(f"Warning: 获取自定义音色失败：{e}", file=sys.stderr)

    if not a.cloned_only:
        sources = [("qwen-tts", "Qwen-TTS", URL_QWEN_TTS_VOICES),
                   ("cosyvoice", "CosyVoice", URL_COSYVOICE_VOICES),
                   ("qwen-audio", "Qwen-Audio-TTS", URL_QWEN_AUDIO_VOICES)]
        for key, fam, url in sources:
            if a.family not in ("all", key):
                continue
            try:
                parsed = parse_voices_table(fetch_doc_content(url, use_cache=not a.no_cache), fam)
                if not parsed:
                    print(f"Warning: {fam} 音色页解析结果为空（页面结构可能变更）：{url}", file=sys.stderr)
                fam_models = suggestions.get(fam, [])
                for v in parsed:
                    v["model"] = " / ".join(fam_models[:2]) if fam_models else "（官方矩阵中无可调用模型）"
                results.extend(parsed)
            except Exception as e:
                print(f"Warning: 获取 {fam} 音色失败：{e}", file=sys.stderr)

    if a.recommend:
        limit, recs, counts = 5, [], {}
        for v in results:
            fam = v["family"]
            if fam.startswith("Custom") or counts.get(fam, 0) < limit:
                if fam == "CosyVoice" and v["ssml"] is False and v["instruct"] is False:
                    continue
                recs.append(v)
                counts[fam] = counts.get(fam, 0) + 1
        results = recs

    if a.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    print("\n### 🎙️ 百炼音色列表（实时抓取）\n")
    print(f"> 数据源：[音色列表]({URL_VOICE_LIST_INDEX})；“建议模型”取自官方能力矩阵中本 skill 可调用的同家族模型。"
          "自定义音色只能用其绑定模型。\n")
    print("| 系列 | 建议/绑定模型 | voice 参数 | 名称 | 特质 | SSML | Instruct |")
    print("| :--- | :--- | :--- | :--- | :--- | :---: | :---: |")
    for v in results:
        print(f"| {v['family']} | `{v['model']}` | `{v['voice']}` | {v['name']} | {v['desc']} | "
              f"{mark(v['ssml'])} | {mark(v['instruct'])} |")
    print()


if __name__ == "__main__":
    main()
