"""Render the song's score into an audio file.

The score lives inside anniversary-august-15.html as a JSON block, so the
page and this renderer can never drift apart. Run from the repo root:

    python3 songs/render_audio.py out.wav            # 피아노
    python3 songs/render_audio.py out.wav --kpop     # K-POP 편곡
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
KICK = {1: [0, 10], 2: [0, 6, 10], 3: [0, 6, 10, 13]}
CLAP = {1: [8], 2: [8], 3: [8, 14]}
HAT = {
    1: [0, 2, 4, 6, 8, 10, 12, 14],
    2: [0, 2, 4, 6, 8, 10, 12, 14, 15],
    3: [0, 2, 4, 6, 8, 10, 12, 13, 14, 15],
}
HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(11)


# ── 악보 ────────────────────────────────────────────────────────────────

def load_score(page):
    html = page.read_text(encoding="utf-8")
    match = re.search(
        r'<script id="score" type="application/json">(.*?)</script>', html, re.S
    )
    if not match:
        raise SystemExit(f"no score block found in {page}")
    return json.loads(match.group(1))


def check(score):
    """Every phrase and every chord line must fill exactly two 4/4 bars."""
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
    hook = sum(length for _, length in score["kpop"]["hook"])
    intro = sum(span for _, span in score["kpop"]["intro"])
    if abs(hook - intro) > 1e-9:
        raise SystemExit(f"kpop hook is {hook} beats over a {intro} beat intro")


def harmony_below(midi, voicing):
    """Pick a harmony note from the chord under it, so it never clashes."""
    pcs = {n % 12 for n in voicing}
    for n in range(midi - 3, midi - 10, -1):
        if n % 12 in pcs:
            return n
    return None


def schedule(score, kpop):
    """Flatten the score into (start, voice, midi, seconds, gain)."""
    spb = 60 / score["bpm"]
    out = []
    beat = 0.0

    def add(t, voice, midi, dur, gain):
        out.append((t * spb, voice, midi, dur * spb, gain))

    def chords(bars, shift, level):
        nonlocal beat
        spans = []
        for name, span in bars:
            v = [n + shift for n in score["voicings"][name]]
            spans.append((beat, beat + span, v))
            for i in range(int(round(span * 2))):
                add(beat + i * 0.5, "rhodes" if kpop else "piano",
                    v[ARP[i % len(ARP)]], 0.5, 0.115 if i == 0 else 0.075)
            if kpop and level >= 1:
                add(beat, "bass", v[0] - 12, span, 0.40)
            if kpop and level >= 2:
                for n in v[1:]:
                    add(beat, "pad", n + 12, span, 0.03)
            beat += span
        return spans

    def drums(start, level):
        for s in KICK[level]:
            add(start + s * 0.25, "kick", 0, 0.4, 0.6)
        for s in CLAP[level]:
            add(start + s * 0.25, "clap", 0, 0.3, 0.28)
        for s in HAT[level]:
            add(start + s * 0.25, "hat", 0, 0.12, 0.055 if s % 2 else 0.095)

    if kpop:
        head = beat
        chords(score["kpop"]["intro"], 0, 1)
        for b in range(4):
            drums(head + b * 4, 1)
        cursor = head
        for midi, length in score["kpop"]["hook"]:
            if midi > 0:
                add(cursor, "lead", midi, length, 0.16)
            cursor += length
    else:
        chords(score["intro"], 0, 0)

    for line in score["lines"]:
        if not kpop and line.get("rap"):
            continue
        shift = line.get("k", 0) if kpop else 0
        level = line["i"] if kpop else 0
        head = beat
        spans = chords(line["b"], shift, level)
        if level >= 1:
            drums(head, level)
            drums(head + 4, level)
        cursor = head
        for midi, length in score["mel"][line["m"]]:
            if midi > 0:
                n = midi + shift
                add(cursor, "lead" if kpop else "piano", n, length,
                    0.17 if kpop else 0.2)
                if kpop and level >= 3:
                    slot = next((s for s in spans if s[0] <= cursor < s[1]), spans[0])
                    h = harmony_below(n, slot[2])
                    if h:
                        add(cursor, "harm", h, length, 0.055)
            cursor += length

    chords(score["coda"], score["kpop"]["codaShift"] if kpop else 0, 0)
    return out, beat * spb


# ── 소리 ────────────────────────────────────────────────────────────────

def band(x, lo, hi):
    """Cheap FFT filter — only ever used on short bursts."""
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / RATE)
    mask = np.ones_like(freqs)
    if lo:
        mask *= 1 / (1 + (lo / np.maximum(freqs, 1e-6)) ** 4)
    if hi:
        mask *= 1 / (1 + (freqs / hi) ** 4)
    return np.fft.irfft(spec * mask, n=len(x))


def struck(freq, dur, gain, ring, shine):
    tail = dur + ring
    t = np.arange(int(tail * RATE)) / RATE
    env = np.exp(-t * (2.6 / tail)) * np.minimum(t / 0.008, 1.0)
    wave_out = np.zeros_like(t)
    for ratio, weight, fade in ((1.0, 1.0, 1.0), (2.004, 0.30 * shine, 1.9),
                                (3.003, 0.11 * shine, 2.8), (4.01, 0.045 * shine, 4.0)):
        if freq * ratio < RATE / 2.2:
            wave_out += weight * np.sin(2 * np.pi * freq * ratio * t) * np.exp(-t * fade / tail)
    knock = np.zeros_like(t)
    edge = int(0.006 * RATE)
    knock[:edge] = RNG.uniform(-1, 1, edge) * 0.25
    return (wave_out + knock) * env * gain


def saw(freq, t, partials=14):
    out = np.zeros_like(t)
    for k in range(1, partials + 1):
        if freq * k > RATE / 2.2:
            break
        out += np.sin(2 * np.pi * freq * k * t) / k
    return out * 0.55


def sung(freq, dur, gain, cutoff, attack, vibrato):
    hold = max(dur, attack + 0.02)
    t = np.arange(int((hold + 0.3) * RATE)) / RATE
    bend = np.zeros_like(t)
    if vibrato:
        depth = np.minimum(t / 0.45, 1.0) * 0.004
        bend = depth * np.sin(2 * np.pi * 5.2 * t)
    body = saw(freq, t) + saw(freq * (1 + 0.004), t) * 0.4
    body = body * (1 + bend)
    env = np.clip(t / attack, 0, 1) * np.clip((hold + 0.28 - t) / 0.28, 0, 1)
    return band(body * env, None, cutoff) * gain


def pad_voice(freq, dur, gain):
    t = np.arange(int((dur + 0.8) * RATE)) / RATE
    body = saw(freq * 0.9959, t, 8) + saw(freq * 1.0041, t, 8)
    env = np.clip(t / 0.7, 0, 1) * np.clip((dur + 0.7 - t) / 0.7, 0, 1)
    return band(body * env, None, 1100) * gain


def low_end(freq, dur, gain):
    t = np.arange(int((dur + 0.2) * RATE)) / RATE
    body = np.sin(2 * np.pi * freq * t) + 0.12 * np.sin(4 * np.pi * freq * t)
    env = np.clip(t / 0.03, 0, 1) * np.clip((dur + 0.12 - t) / 0.12, 0, 1)
    return body * env * gain


def thump(gain):
    t = np.arange(int(0.4 * RATE)) / RATE
    freq = 44 + (125 - 44) * np.exp(-t / 0.028)
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    return np.sin(phase) * np.exp(-t / 0.09) * gain


def hiss(dur, gain, lo, hi):
    n = int(dur * RATE)
    noise = RNG.uniform(-1, 1, n)
    env = np.exp(-np.arange(n) / RATE / (dur / 3.2))
    return band(noise * env, lo, hi) * gain


def render_voice(voice, midi, dur, gain):
    freq = 440 * 2 ** ((midi - 69) / 12) if midi else 0
    if voice == "piano":
        return struck(freq, dur, gain, 0.55, 0.75)
    if voice == "rhodes":
        return struck(freq, dur, gain, 0.9, 0.35)
    if voice == "lead":
        return sung(freq, dur, gain, 1900, 0.045, True)
    if voice == "harm":
        return sung(freq, dur, gain, 1300, 0.07, False)
    if voice == "pad":
        return pad_voice(freq, dur, gain)
    if voice == "bass":
        return low_end(freq, dur, gain)
    if voice == "kick":
        return thump(gain)
    if voice == "clap":
        first = hiss(0.15, gain, 900, 2600)
        second = hiss(0.19, gain * 0.7, 700, 2100)
        offset = int(0.014 * RATE)
        out = np.zeros(max(len(first), offset + len(second)))
        out[: len(first)] += first
        out[offset : offset + len(second)] += second
        return out
    if voice == "hat":
        return hiss(0.05, gain, 7000, None)
    raise SystemExit(f"unknown voice {voice}")


def reverb(dry, wet):
    rng = np.random.default_rng(15)
    out = np.zeros_like(dry)
    for _ in range(56):
        delay = rng.uniform(0.015, 1.7)
        offset = int(delay * RATE)
        if offset >= len(dry):
            continue
        amp = math.exp(-2.2 * delay) * rng.uniform(0.3, 1.0) * rng.choice([1.0, -1.0])
        out[offset:] += dry[: len(dry) - offset] * amp
    out = np.convolve(out, np.ones(24) / 24, mode="same")
    return dry + out * wet


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    kpop = "--kpop" in sys.argv
    target = Path(args[0] if args else "palwol.wav")

    score = load_score(HERE / "anniversary-august-15.html")
    check(score)
    notes, length = schedule(score, kpop)

    buf = np.zeros(int((length + 3.0) * RATE))
    for start, voice, midi, dur, gain in notes:
        chunk = render_voice(voice, midi, dur, gain)
        at = int(start * RATE)
        room = len(buf) - at
        buf[at : at + len(chunk)] += chunk[:room]

    buf = reverb(buf, 0.16 if kpop else 0.28)
    buf *= 0.89 / max(np.abs(buf).max(), 1e-9)
    fade = int(2.0 * RATE)
    buf[-fade:] *= np.linspace(1, 0, fade)

    pcm = (buf * 32767).astype("<i2")
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm.tobytes())

    style = "K-POP" if kpop else "피아노"
    print(f"{target}  [{style}]  {len(notes)}개 소리  {length:.0f}초  "
          f"{target.stat().st_size / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
