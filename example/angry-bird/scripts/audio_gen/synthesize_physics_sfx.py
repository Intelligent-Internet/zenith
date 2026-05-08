#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from synthesize_bird_sfx import (
    MAX_INT16,
    SAMPLE_RATE,
    chirp,
    clamp,
    encode_ogg,
    envelope,
    noise,
    pulse,
    write_wav,
)

PHYSICS_SFX_SPECS = {
    "sfx-slingshot-pull": {"duration": 0.56, "seed": 31, "kind": "slingshot_pull"},
    "sfx-slingshot-release": {"duration": 0.42, "seed": 32, "kind": "slingshot_release"},
    "sfx-wood-impact": {"duration": 0.34, "seed": 41, "kind": "wood_impact"},
    "sfx-wood-break": {"duration": 0.62, "seed": 42, "kind": "wood_break"},
    "sfx-glass-impact": {"duration": 0.36, "seed": 43, "kind": "glass_impact"},
    "sfx-glass-break": {"duration": 0.78, "seed": 44, "kind": "glass_break"},
    "sfx-stone-impact": {"duration": 0.38, "seed": 45, "kind": "stone_impact"},
    "sfx-stone-break": {"duration": 0.74, "seed": 46, "kind": "stone_break"},
    "sfx-pig-pop": {"duration": 0.45, "seed": 51, "kind": "pig_pop"},
    "sfx-tnt-explosion": {"duration": 1.04, "seed": 52, "kind": "tnt_explosion"},
}


def percussive_decay(t: float, rate: float) -> float:
    return math.exp(-rate * t)


def sample(kind: str, t: float, duration: float, rng: random.Random) -> float:
    progress = clamp(t / duration, 0.0, 1.0)
    env = envelope(t, duration, attack=0.008, release=0.10)

    if kind == "slingshot_pull":
        stretch = 0.36 * chirp(t, 170, 92, duration)
        creak = 0.18 * math.sin(2 * math.pi * 330 * t) * pulse(t, 0.10, 0.28)
        fiber = 0.09 * noise(rng) * (0.2 + progress)
        return env * (stretch + creak + fiber)

    if kind == "slingshot_release":
        snap = percussive_decay(t, 26) * (0.72 * chirp(t, 980, 220, 0.20) + 0.20 * noise(rng))
        whoosh = envelope(t, duration, attack=0.015, release=0.18) * 0.28 * chirp(t, 420, 920, duration)
        return snap + whoosh * (1.0 - progress * 0.35)

    if kind == "wood_impact":
        knock = percussive_decay(t, 32) * (
            0.56 * math.sin(2 * math.pi * 176 * t)
            + 0.26 * math.sin(2 * math.pi * 318 * t)
            + 0.16 * noise(rng)
        )
        return knock

    if kind == "wood_break":
        cracks = sum(
            pulse(t, offset, 0.12) * (0.22 * noise(rng) + 0.16 * math.sin(2 * math.pi * freq * t))
            for offset, freq in [(0.02, 340), (0.13, 420), (0.26, 280), (0.39, 520)]
        )
        body = 0.30 * percussive_decay(t, 5.5) * math.sin(2 * math.pi * 118 * t)
        return env * (body + cracks)

    if kind == "glass_impact":
        chime = percussive_decay(t, 18) * (
            0.48 * math.sin(2 * math.pi * 1860 * t)
            + 0.28 * math.sin(2 * math.pi * 2460 * t)
        )
        return chime + 0.04 * noise(rng) * (1.0 - progress)

    if kind == "glass_break":
        shards = sum(
            pulse(t, offset, 0.18) * 0.20 * math.sin(2 * math.pi * freq * t)
            for offset, freq in [(0.01, 2100), (0.08, 2650), (0.18, 3200), (0.31, 1750)]
        )
        scatter = envelope(t, duration, attack=0.004, release=0.30) * 0.28 * noise(rng) * (1.0 - progress)
        return shards + scatter

    if kind == "stone_impact":
        thud = percussive_decay(t, 20) * (
            0.56 * math.sin(2 * math.pi * 92 * t)
            + 0.24 * math.sin(2 * math.pi * 154 * t)
            + 0.10 * noise(rng)
        )
        return thud

    if kind == "stone_break":
        rumble = 0.44 * percussive_decay(t, 4.2) * math.sin(2 * math.pi * 74 * t)
        crumble = 0.24 * noise(rng) * envelope(t, duration, attack=0.02, release=0.34)
        grit = 0.12 * math.sin(2 * math.pi * 210 * t) * pulse(t, 0.18, 0.34)
        return rumble + crumble * (1.0 - progress * 0.45) + grit

    if kind == "pig_pop":
        pop = percussive_decay(t, 24) * 0.72 * chirp(t, 760, 150, 0.20)
        squeak = 0.20 * math.sin(2 * math.pi * 980 * t) * pulse(t, 0.14, 0.15)
        puff = 0.12 * noise(rng) * pulse(t, 0.08, 0.22)
        return pop + squeak + puff

    if kind == "tnt_explosion":
        transient = pulse(t, 0.0, 0.11) * 0.54 * noise(rng)
        boom_t = max(0.0, t - 0.05)
        boom = percussive_decay(boom_t, 4.4) * (
            0.78 * math.sin(2 * math.pi * 58 * boom_t)
            + 0.26 * math.sin(2 * math.pi * 116 * boom_t)
        )
        debris = 0.18 * noise(rng) * envelope(t, duration, attack=0.015, release=0.45)
        return transient + boom + debris * (1.0 - progress * 0.3)

    raise ValueError(f"unknown SFX kind: {kind}")


def render_pcm(spec: dict[str, object]) -> list[int]:
    duration = float(spec["duration"])
    kind = str(spec["kind"])
    rng = random.Random(int(spec["seed"]))
    frame_count = int(SAMPLE_RATE * duration)
    pcm: list[int] = []

    for index in range(frame_count):
        t = index / SAMPLE_RATE
        value = clamp(sample(kind, t, duration, rng) * 0.78)
        pcm.append(int(value * MAX_INT16))

    return pcm


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize deterministic physics and pig SFX.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("public/assets/audio"),
        help="Directory where .ogg files will be written.",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for key, spec in PHYSICS_SFX_SPECS.items():
        wav_path = args.output_dir / f"{key}.wav"
        ogg_path = args.output_dir / f"{key}.ogg"
        write_wav(wav_path, render_pcm(spec))
        encode_ogg(wav_path, ogg_path)
        wav_path.unlink()
        print(f"wrote {ogg_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
