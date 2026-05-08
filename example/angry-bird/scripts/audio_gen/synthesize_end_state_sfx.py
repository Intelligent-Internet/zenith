#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from synthesize_bird_sfx import (
    MAX_INT16,
    SAMPLE_RATE,
    clamp,
    encode_ogg,
    envelope,
    noise,
    pulse,
    write_wav,
)

END_STATE_SFX_SPECS = {
    "sfx-level-win-stinger": {"duration": 1.42, "seed": 61, "kind": "win_stinger"},
    "sfx-level-fail-jingle": {"duration": 1.58, "seed": 62, "kind": "fail_jingle"},
}


def note(t: float, start: float, length: float, hz: float, amplitude: float = 1.0) -> float:
    if t < start or t > start + length:
        return 0.0
    local_t = t - start
    tone_env = envelope(local_t, length, attack=0.012, release=0.18)
    fundamental = math.sin(2 * math.pi * hz * local_t)
    harmonic = 0.32 * math.sin(2 * math.pi * hz * 2 * local_t)
    return amplitude * tone_env * (fundamental + harmonic)


def sample(kind: str, t: float, duration: float, rng: random.Random) -> float:
    progress = clamp(t / duration, 0.0, 1.0)

    if kind == "win_stinger":
        arpeggio = (
            note(t, 0.00, 0.34, 523.25, 0.42)
            + note(t, 0.18, 0.34, 659.25, 0.38)
            + note(t, 0.36, 0.40, 783.99, 0.40)
            + note(t, 0.62, 0.62, 1046.50, 0.36)
        )
        sparkle = sum(
            pulse(t, offset, 0.16) * 0.12 * math.sin(2 * math.pi * freq * t)
            for offset, freq in [(0.22, 1568), (0.48, 2093), (0.78, 2349)]
        )
        lift = 0.10 * noise(rng) * envelope(t, duration, attack=0.04, release=0.45) * (1.0 - progress)
        return arpeggio + sparkle + lift

    if kind == "fail_jingle":
        descent = (
            note(t, 0.00, 0.42, 392.00, 0.36)
            + note(t, 0.30, 0.44, 349.23, 0.34)
            + note(t, 0.62, 0.50, 293.66, 0.34)
            + note(t, 0.98, 0.48, 220.00, 0.30)
        )
        wobble = 0.16 * math.sin(2 * math.pi * 146.83 * t + 4 * math.sin(2 * math.pi * 5 * t))
        thud = pulse(t, 1.18, 0.24) * (
            0.34 * math.sin(2 * math.pi * 82.41 * (t - 1.18))
            + 0.08 * noise(rng)
        )
        return envelope(t, duration, attack=0.02, release=0.28) * (descent + wobble * (1.0 - progress)) + thud

    raise ValueError(f"unknown SFX kind: {kind}")


def render_pcm(spec: dict[str, object]) -> list[int]:
    duration = float(spec["duration"])
    kind = str(spec["kind"])
    rng = random.Random(int(spec["seed"]))
    frame_count = int(SAMPLE_RATE * duration)
    pcm: list[int] = []

    for index in range(frame_count):
        t = index / SAMPLE_RATE
        value = clamp(sample(kind, t, duration, rng) * 0.72)
        pcm.append(int(value * MAX_INT16))

    return pcm


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize deterministic win/fail stingers.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("public/assets/audio"),
        help="Directory where .ogg files will be written.",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for key, spec in END_STATE_SFX_SPECS.items():
        wav_path = args.output_dir / f"{key}.wav"
        ogg_path = args.output_dir / f"{key}.ogg"
        write_wav(wav_path, render_pcm(spec))
        encode_ogg(wav_path, ogg_path)
        wav_path.unlink()
        print(f"wrote {ogg_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
