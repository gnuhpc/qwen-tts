#!/usr/bin/env python3
"""
Batch scene audio generator (scene1.mp3, scene2.mp3, ...) with retry.
No default model/voice: pass --voice (and --model unless the voice is a custom voice).
"""
import argparse
import json
import os
import sys
import time

from _common import SkillError, emit_media, init_dashscope, resolve_model_and_voice, synthesize


def load_scenes(input_path):
    if not os.path.exists(input_path):
        raise SkillError(f"Input file not found: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return [str(x) for x in data if str(x).strip()]
        if isinstance(data, dict) and "scenes" in data:
            return [str(x) for x in data["scenes"] if str(x).strip()]
    except Exception:
        pass
    return [line.strip() for line in content.splitlines() if line.strip()]


def generate_scenes(scenes, output_dir, model, voice, api_key, max_retries=3, fmt="mp3", **opts):
    os.makedirs(output_dir, exist_ok=True)
    print(f"🎬 Generating {len(scenes)} scenes to {output_dir} (Voice: {voice}, Model: {model})...")
    results = []
    for i, text in enumerate(scenes, start=1):
        out = os.path.join(output_dir, f"scene{i}.{fmt}")
        print(f"[{i}/{len(scenes)}] {out}")
        for attempt in range(1, max_retries + 1):
            try:
                final = synthesize(text, out, model, voice, api_key, fmt=fmt, **opts)
                emit_media(final)
                results.append(final)
                break
            except SkillError:
                raise  # configuration errors are not retryable
            except Exception as e:
                print(f"  ⚠️ Scene {i} attempt {attempt}/{max_retries} failed: {e}", file=sys.stderr)
                if attempt == max_retries:
                    raise SkillError(f"Scene {i} failed after {max_retries} attempts.")
                time.sleep(2)
    print(f"✅ All {len(results)} scenes generated.")
    return results


def main():
    p = argparse.ArgumentParser(description="Batch scene narration generator.")
    p.add_argument("--input", required=True, help="JSON list / {'scenes': [...]} / line-based text file.")
    p.add_argument("--output-dir", default="audio", help="Output directory.")
    p.add_argument("--model", help="Model ID (optional for custom voices). See fetch_voices.py --models.")
    p.add_argument("--voice", required=True, help="Voice ID (official or custom voice_id).")
    p.add_argument("--instructions", help="Instruct text (models with 指令控制=支持 only).")
    p.add_argument("--speech-rate", type=float, default=1.0)
    p.add_argument("--pitch-rate", type=float, default=1.0)
    p.add_argument("--volume", type=int, default=50)
    p.add_argument("--format", default="mp3", choices=["mp3", "wav", "pcm"])
    p.add_argument("--sample-rate", type=int, default=48000)
    p.add_argument("--region", default="beijing", choices=["beijing", "singapore"])
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--api-key")
    a = p.parse_args()
    try:
        api_key = init_dashscope(a.api_key, a.region)
        model, voice = resolve_model_and_voice(a.model, a.voice, api_key)
        generate_scenes(load_scenes(a.input), a.output_dir, model, voice, api_key, max_retries=a.retries,
                        fmt=a.format, instructions=a.instructions, speech_rate=a.speech_rate,
                        pitch_rate=a.pitch_rate, volume=a.volume, sample_rate=a.sample_rate)
    except SkillError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
