#!/usr/bin/env python3
"""
Speech generation CLI for Alibaba Cloud Model Studio (Qwen-Audio-TTS / CosyVoice / Qwen-TTS).

No model or voice is hardcoded:
  - Discover models:  python3 scripts/fetch_voices.py --models
  - Discover voices:  python3 scripts/fetch_voices.py --recommend
  - Custom voices:    python3 scripts/clone_voice.py list   (--model can be omitted; it is inferred)
"""
import argparse
import sys

from _common import SkillError, emit_media, init_dashscope, resolve_model_and_voice, synthesize


def main():
    parser = argparse.ArgumentParser(description="Generate speech with Alibaba Cloud Model Studio TTS models.")
    parser.add_argument("--text", help="Text to synthesize (plain / SSML <speak>...</speak> / LaTeX).")
    parser.add_argument("--batch-file", help="JSON list or line-based text file of scenes (batch mode).")
    parser.add_argument("--model", help="Model ID. Required unless --voice is a custom (cloned/designed) voice. See fetch_voices.py --models.")
    parser.add_argument("--voice", required=True, help="Voice ID (official voice or custom voice_id).")
    parser.add_argument("--instructions", "--instruction", dest="instructions", help="Instruct text (only for models whose 指令控制=支持).")
    parser.add_argument("--language", default="Chinese", help="Language type (Qwen-TTS only).")
    parser.add_argument("--output", default="speech.mp3", help="Output file (or output dir in batch mode).")
    parser.add_argument("--api-key", help="DashScope API Key.")
    parser.add_argument("--speech-rate", type=float, default=1.0, help="Speech rate (0.5 to 2.0).")
    parser.add_argument("--pitch-rate", type=float, default=1.0, help="Pitch rate (0.5 to 2.0).")
    parser.add_argument("--volume", type=int, default=50, help="Volume (0 to 100).")
    parser.add_argument("--format", default="mp3", choices=["mp3", "wav", "pcm"], help="Output audio format.")
    parser.add_argument("--sample-rate", type=int, default=48000, help="Sample rate (8000/16000/22050/24000/44100/48000).")
    parser.add_argument("--region", default="beijing", choices=["beijing", "singapore"], help="API region.")
    args = parser.parse_args()

    try:
        api_key = init_dashscope(args.api_key, args.region)
        model, voice = resolve_model_and_voice(args.model, args.voice, api_key)
        opts = dict(instructions=args.instructions, speech_rate=args.speech_rate, pitch_rate=args.pitch_rate,
                    volume=args.volume, fmt=args.format, sample_rate=args.sample_rate, language=args.language)

        if args.batch_file:
            from generate_scenes import generate_scenes, load_scenes
            out_dir = args.output if args.output != "speech.mp3" else "audio"
            generate_scenes(load_scenes(args.batch_file), out_dir, model, voice, api_key, **opts)
            return

        if not args.text:
            raise SkillError("非批量模式下必须提供 --text。")
        print(f"Generating {args.output} with voice '{voice}' and model '{model}'...")
        emit_media(synthesize(args.text, args.output, model, voice, api_key, **opts))
    except SkillError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Exception: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
