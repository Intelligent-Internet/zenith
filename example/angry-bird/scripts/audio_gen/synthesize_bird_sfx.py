#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import random
import subprocess
import wave
from pathlib import Path

SAMPLE_RATE = 44_100
MAX_INT16 = 32_767

SFX_SPECS = {
    "sfx-bird-red-cry": {"duration": 0.46, "seed": 11, "kind": "red"},
    "sfx-bird-blues-flutter": {"duration": 0.48, "seed": 12, "kind": "blues_flight"},
    "sfx-bird-chuck-zip": {"duration": 0.38, "seed": 13, "kind": "chuck_flight"},
    "sfx-bird-matilda-glide": {"duration": 0.58, "seed": 14, "kind": "matilda_flight"},
    "sfx-bird-bomb-rumble": {"duration": 0.62, "seed": 15, "kind": "bomb_flight"},
    "sfx-bird-hal-boomerang-flight": {"duration": 0.64, "seed": 16, "kind": "hal_flight"},
    "sfx-blues-split": {"duration": 0.44, "seed": 21, "kind": "blues_split"},
    "sfx-chuck-burst": {"duration": 0.40, "seed": 22, "kind": "chuck_burst"},
    "sfx-matilda-egg-drop": {"duration": 0.50, "seed": 23, "kind": "matilda_egg"},
    "sfx-bomb-fuse-explode": {"duration": 0.90, "seed": 24, "kind": "bomb_fuse"},
    "sfx-hal-boomerang": {"duration": 0.68, "seed": 25, "kind": "hal_boomerang"},
}


def clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def envelope(t: float, duration: float, attack: float = 0.025, release: float = 0.12) -> float:
    if t < attack:
        return t / attack
    remaining = duration - t
    if remaining < release:
        return max(0.0, remaining / release)
    return 1.0


def chirp(phase_time: float, start_hz: float, end_hz: float, duration: float) -> float:
    progress = clamp(phase_time / duration, 0.0, 1.0)
    freq = start_hz + (end_hz - start_hz) * progress
    return math.sin(2.0 * math.pi * freq * phase_time)


def noise(rng: random.Random) -> float:
    return rng.uniform(-1.0, 1.0)


def pulse(t: float, start: float, length: float) -> float:
    if t < start or t > start + length:
        return 0.0
    local = (t - start) / length
    return math.sin(math.pi * local)


def sample(kind: str, t: float, duration: float, rng: random.Random) -> float:
    progress = clamp(t / duration, 0.0, 1.0)
    env = envelope(t, duration)

    if kind == "red":
        voice = 0.65 * chirp(t, 560, 390, duration)
        grit = 0.18 * math.sin(2 * math.pi * 1180 * t) * math.sin(2 * math.pi * 8 * t)
        return env * (voice + grit + 0.04 * noise(rng))

    if kind == "blues_flight":
        flutter = sum(
            0.22 * math.sin(2 * math.pi * freq * t) * pulse(t, offset, 0.18)
            for freq, offset in [(760, 0.02), (960, 0.15), (1160, 0.28)]
        )
        return env * (flutter + 0.08 * noise(rng))

    if kind == "chuck_flight":
        zip_tone = 0.72 * chirp(t, 740, 1650, duration)
        return env * (zip_tone + 0.10 * noise(rng) * (1.0 - progress))

    if kind == "matilda_flight":
        tone = 0.48 * math.sin(2 * math.pi * 430 * t)
        overtone = 0.20 * math.sin(2 * math.pi * 645 * t + math.sin(2 * math.pi * 4 * t))
        return env * (tone + overtone)

    if kind == "bomb_flight":
        rumble = 0.50 * math.sin(2 * math.pi * 88 * t)
        sub = 0.28 * math.sin(2 * math.pi * 44 * t)
        return env * (rumble + sub + 0.06 * noise(rng))

    if kind == "hal_flight":
        swoop = 0.40 * chirp(t, 260, 520, duration) + 0.24 * chirp(t, 660, 220, duration)
        return env * (swoop + 0.08 * noise(rng) * math.sin(math.pi * progress))

    if kind == "blues_split":
        return sum(
            pulse(t, offset, 0.13) * 0.34 * math.sin(2 * math.pi * freq * t)
            for freq, offset in [(920, 0.03), (1180, 0.14), (1460, 0.25)]
        )

    if kind == "chuck_burst":
        burst = 0.74 * chirp(t, 600, 2200, duration)
        scrape = 0.16 * noise(rng) * (1.0 - progress)
        return env * (burst + scrape)

    if kind == "matilda_egg":
        drop = 0.50 * chirp(t, 720, 210, duration)
        pop = 0.22 * math.sin(2 * math.pi * 140 * t) * pulse(t, 0.32, 0.13)
        return env * (drop + pop)

    if kind == "bomb_fuse":
        if progress < 0.42:
            hiss_env = envelope(t, duration * 0.42, attack=0.01, release=0.05)
            return 0.28 * hiss_env * noise(rng)
        boom_t = t - duration * 0.42
        boom_env = math.exp(-5.2 * boom_t)
        boom = 0.86 * math.sin(2 * math.pi * 72 * boom_t) + 0.28 * noise(rng)
        return boom_env * boom

    if kind == "hal_boomerang":
        turn = 0.46 * chirp(t, 740, 240, duration) + 0.32 * chirp(t, 260, 860, duration)
        return env * (turn + 0.06 * noise(rng))

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


def write_wav(path: Path, pcm: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(b"".join(sample.to_bytes(2, "little", signed=True) for sample in pcm))


def encode_ogg(wav_path: Path, ogg_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(wav_path),
            "-c:a",
            "libvorbis",
            "-q:a",
            "4",
            str(ogg_path),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize deterministic bird flight and ability SFX.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("public/assets/audio"),
        help="Directory where .ogg files will be written.",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for key, spec in SFX_SPECS.items():
        wav_path = args.output_dir / f"{key}.wav"
        ogg_path = args.output_dir / f"{key}.ogg"
        write_wav(wav_path, render_pcm(spec))
        encode_ogg(wav_path, ogg_path)
        wav_path.unlink()
        print(f"wrote {ogg_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
