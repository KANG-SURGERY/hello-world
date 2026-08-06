"""Render the song's score into an audio file.

The score lives inside anniversary-august-15.html as a JSON block, so the
page and this renderer can never drift apart. Run from the repo root:

    python3 songs/render_audio.py out.wav
"""

import json
import math
import re
import sys
import wave
from pathlib import Path

import numpy as np

RATE = 32000
ARP = [0, 1, 2, 3, 2, 3, 1, 2]
HERE = Path(__file__).resolve().parent


def load_score(page):
    """Pull the <script id="score"> block out of the page."""
    html = page.read_text(encoding="utf-8")
    match = re.search(
        r'<script id="score" type="application/json">(.*?)</script>', html, re.S
    )
    if not match:
        raise SystemExit(f"no score block found in {page}")
    return json.loads(match.group(1))


def check(score):
    """Every phrase and every chord bar must fill exactly two 4/4 bars."""
    for name, notes in score["mel"].items():
        total = sum(length for _, length in notes)
        if abs(total - 8) > 1e-9:
            raise SystemExit(f"melody {name} is {total} beats, expected 8")
    for i, line in enumerate(score["lines"]):
        total = sum(span for _, span in line["b"])
        if abs(total - 8) > 1e-9:
            raise SystemExit(f"line {i} chords total {total} beats, expected 8")
        for chord, _ in line["b"]:
            if chord not in score["voicings"]:
                raise SystemExit(f"line {i} uses unknown chord {chord}")


def schedule(score):
    """Flatten the score into (start seconds, midi, seconds, gain, tone)."""
    spb = 60 / score["bpm"]
    notes = []
    beat = 0.0

    def strum(bars):
        nonlocal beat
        for chord, span in bars:
            voicing = score["voicings"][chord]
            for i in range(int(round(span * 2))):
                notes.append((
                    (beat + i * 0.5) * spb,
                    voicing[ARP[i % len(ARP)]],
                    0.5 * spb,
                    0.115 if i == 0 else 0.075,
                    0.45,
                ))
            beat += span

    strum(score["intro"])
    for line in score["lines"]:
        head = beat
        strum(line["b"])
        cursor = head
        for midi, length in score["mel"][line["m"]]:
            if midi > 0:
                notes.append((cursor * spb, midi, length * spb * 0.96, 0.2, 1.0))
            cursor += length
    strum(score["coda"])

    return notes, beat * spb


def piano(freq, dur, gain, tone):
    """One struck note: a few partials under an exponential decay."""
    tail = dur + 0.7
    n = int(tail * RATE)
    t = np.arange(n) / RATE

    decay = math.exp(-3.4 / max(tail, 0.35))
    env = np.exp(-t * (2.6 / tail))
    attack = np.minimum(t / 0.008, 1.0)
    env = env * attack

    partials = [(1.0, 1.0, 1.0), (2.001, 0.30 * tone, 1.9),
                (3.003, 0.11 * tone, 2.8), (4.01, 0.045 * tone, 4.0)]
    wave_out = np.zeros(n)
    for ratio, weight, fade in partials:
        if freq * ratio > RATE / 2.2:
            continue
        wave_out += weight * np.sin(2 * np.pi * freq * ratio * t) * np.exp(-t * fade / tail)

    # a touch of hammer noise at the very start
    knock = np.zeros(n)
    edge = int(0.006 * RATE)
    knock[:edge] = np.random.default_rng(int(freq)).uniform(-1, 1, edge) * 0.25

    return (wave_out * env + knock * env) * gain * decay


def reverb(dry, wet=0.28):
    """Multi-tap ambience — cheap, and kinder than a dry piano."""
    rng = np.random.default_rng(15)
    out = np.zeros_like(dry)
    for _ in range(56):
        delay = rng.uniform(0.015, 1.7)
        offset = int(delay * RATE)
        if offset >= len(dry):
            continue
        amp = math.exp(-2.2 * delay) * rng.uniform(0.3, 1.0) * rng.choice([1.0, -1.0])
        out[offset:] += dry[: len(dry) - offset] * amp
    # soften the tail
    kernel = np.ones(24) / 24
    out = np.convolve(out, kernel, mode="same")
    return dry + out * wet


def main():
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "palwol.wav")
    score = load_score(HERE / "anniversary-august-15.html")
    check(score)
    notes, length = schedule(score)

    buf = np.zeros(int((length + 3.0) * RATE))
    for start, midi, dur, gain, tone in notes:
        freq = 440 * 2 ** ((midi - 69) / 12)
        voice = piano(freq, dur, gain, tone)
        at = int(start * RATE)
        buf[at : at + len(voice)] += voice[: len(buf) - at]

    buf = reverb(buf)
    buf *= 0.89 / max(np.abs(buf).max(), 1e-9)

    # ease the last two seconds out
    fade = int(2.0 * RATE)
    buf[-fade:] *= np.linspace(1, 0, fade)

    pcm = (buf * 32767).astype("<i2")
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm.tobytes())

    print(f"{target}  {len(notes)} notes  {length:.0f}s  {target.stat().st_size/1e6:.1f}MB")


if __name__ == "__main__":
    main()
