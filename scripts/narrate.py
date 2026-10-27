#!/usr/bin/env python3
"""
Positional quick narration helper.

Usage: narrate.py <text> <output> <api_key|auto> <speech_rate> <voice> [model]
  - voice is required (no hardcoded default).
  - model may be omitted only when voice is a custom (cloned/designed) voice_id.
"""
import sys

from _common import SkillError, emit_media, init_dashscope, resolve_model_and_voice, synthesize

USAGE = "Usage: narrate.py <text> <output> <api_key|auto> <speech_rate> <voice> [model]"


def main():
    if len(sys.argv) < 6:
        print(USAGE, file=sys.stderr)
        print("voice 为必填。可用音色：python3 scripts/fetch_voices.py --recommend 或 python3 scripts/clone_voice.py list",
              file=sys.stderr)
        sys.exit(1)
    text, output, api_key_arg, rate, voice = sys.argv[1:6]
    model = sys.argv[6] if len(sys.argv) > 6 else None
    try:
        api_key = init_dashscope(api_key_arg)
        model, voice = resolve_model_and_voice(model, voice, api_key)
        print(f"Generating {output} with voice '{voice}' and model '{model}'...")
        emit_media(synthesize(text, output, model, voice, api_key, speech_rate=float(rate)))
    except SkillError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
