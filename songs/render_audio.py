"""Render the song's score into an audio file.

The score and the lyrics both live inside anniversary-august-15.html, so
the page and this renderer can never drift apart. Run from the repo root:

    python3 songs/render_audio.py out.wav                    # 발라드 + 노래
    python3 songs/render_audio.py out.wav --style piano      # 피아노 한 대
    python3 songs/render_audio.py out.wav --style kpop       # K-POP 편곡
    python3 songs/render_audio.py out.wav --no-voice         # 반주만
"""

import json
import math
import re
import sys
import wave
from pathlib import Path

import numpy as np

import voice as vox

RATE = 32000
ARP = [0, 1, 2, 3, 2, 3, 1, 2]
EIGHTHS = [0, 2, 4, 6, 8, 10, 12, 14]
HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(11)

BEATS = {
    "ballad": {
        "kick": {2: [0, 8], 3: [0, 8]}, "kick_gain": 0.42,
        "hit": {3: [4, 12]}, "hit_voice": "brush", "hit_gain": 0.2,
        "tick": {2: EIGHTHS, 3: EIGHTHS}, "tick_voice": "shaker", "tick_gain": 0.055,
    },
    "kpop": {
        "kick": {1: [0, 10], 2: [0, 6, 10], 3: [0, 6, 10, 13]}, "kick_gain": 0.6,
        "hit": {1: [8], 2: [8], 3: [8, 14]}, "hit_voice": "clap", "hit_gain": 0.28,
        "tick": {1: EIGHTHS, 2: EIGHTHS + [15], 3: [0, 2, 4, 6, 8, 10, 12, 13, 14, 15]},
        "tick_voice": "hat", "tick_gain": 0.095,
    },
}

STYLES = {
    "piano": dict(chord="piano", melody="warm", melody_gain=0.20, swell=None,
                  swell_gain=0, beat=None, bass=0, lift=False, rap=False,
                  opening=False, wet=0.28),
    "ballad": dict(chord="piano", melody="warm", melody_gain=0.19, swell="strings",
                   swell_gain=0.05, beat="ballad", bass=0.30, lift=True, rap=False,
                   opening=True, wet=0.32),
    "kpop": dict(chord="rhodes", melody="lead", melody_gain=0.17, swell="pad",
                 swell_gain=0.03, beat="kpop", bass=0.40, lift=True, rap=True,
                 opening=True, wet=0.16),
}


# ── 악보와 가사 ─────────────────────────────────────────────────────────

def load_page(page):
    html = page.read_text(encoding="utf-8")
    block = re.search(
        r'<script id="score" type="application/json">(.*?)</script>', html, re.S)
    if not block:
        raise SystemExit(f"no score block found in {page}")
    stanzas = re.findall(r'<div class="stanza[^"]*">(.*?)</div>', html, re.S)
    lyrics = [re.sub(r"<[^>]+>", "", line).strip()
              for s in stanzas for line in re.findall(r"<p>(.*?)</p>", s, re.S)]
    return json.loads(block.group(1)), lyrics


def check(score, lyrics):
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
    if len(lyrics) != len(score["lines"]):
        raise SystemExit(
            f"{len(lyrics)} lyric lines but {len(score['lines'])} score lines")
    hook = sum(length for _, length in score["opening"]["hook"])
    intro = sum(span for _, span in score["opening"]["intro"])
    if abs(hook - intro) > 1e-9:
        raise SystemExit(f"hook is {hook} beats over a {intro} beat opening")


def harmony_below(midi, voicing):
    pcs = {n % 12 for n in voicing}
    for n in range(midi - 3, midi - 10, -1):
        if n % 12 in pcs:
            return n
    return None


def lay_out(melody, head):
    """멜로디를 (시작박, 음, 길이) 목록으로 편다."""
    notes, cursor = [], head
    for midi, length in melody:
        if midi > 0:
            notes.append([cursor, midi, length])
        cursor += length
    return notes


def align(chars, notes):
    """음절 수와 음표 수를 맞춘다 — 모자라면 쪼개고, 남으면 끌어서 부른다."""
    notes = [list(n) for n in notes]
    while len(chars) > len(notes) and notes:
        i = max(range(len(notes)), key=lambda j: notes[j][2])
        start, midi, length = notes[i]
        notes[i] = [start, midi, length / 2]
        notes.insert(i + 1, [start + length / 2, midi, length / 2])
    pairs = []
    for j, (start, midi, length) in enumerate(notes):
        if j < len(chars):
            pairs.append((start, midi, length, chars[j], False))
        elif chars:
            pairs.append((start, midi, length, chars[-1], True))   # 끌어 부르기
    return pairs


# ── 시간 위에 펼치기 ────────────────────────────────────────────────────

def schedule(score, lyrics, style_name, with_voice):
    style = STYLES[style_name]
    kit = BEATS[style["beat"]] if style["beat"] else None
    spb = 60 / score["bpm"]
    out = []
    beat = 0.0

    def add(t, voice, midi, dur, gain, char=None):
        out.append((t * spb, voice, midi, dur * spb, gain, char))

    def chords(bars, shift, level):
        nonlocal beat
        spans = []
        for name, span in bars:
            v = [n + shift for n in score["voicings"][name]]
            spans.append((beat, beat + span, v))
            for i in range(int(round(span * 2))):
                add(beat + i * 0.5, style["chord"], v[ARP[i % len(ARP)]],
                    0.5, 0.115 if i == 0 else 0.075)
            if style["bass"] and level >= 1:
                add(beat, "bass", v[0] - 12, span, style["bass"])
            if style["swell"] and level >= 2:
                for n in v[1:]:
                    add(beat, style["swell"], n + 12, span, style["swell_gain"])
            beat += span
        return spans

    def drums(start, level):
        if not kit:
            return
        for s in kit["kick"].get(level, []):
            add(start + s * 0.25, "kick", 0, 0.4, kit["kick_gain"])
        for s in kit["hit"].get(level, []):
            add(start + s * 0.25, kit["hit_voice"], 0, 0.3, kit["hit_gain"])
        for s in kit["tick"].get(level, []):
            add(start + s * 0.25, kit["tick_voice"], 0, 0.12,
                kit["tick_gain"] * (0.6 if s % 2 else 1.0))

    if style["opening"]:
        head = beat
        chords(score["opening"]["intro"], 0, 1)
        for b in range(4):
            drums(head + b * 4, 1)
        for start, midi, length in lay_out(score["opening"]["hook"], head):
            add(start, style["melody"], midi, length, style["melody_gain"])
    else:
        chords(score["intro"], 0, 0)

    for index, line in enumerate(score["lines"]):
        if not style["rap"] and line.get("rap"):
            continue
        shift = line.get("k", 0) if style["lift"] else 0
        level = line["i"]
        head = beat
        spans = chords(line["b"], shift, level)
        drums(head, level)
        drums(head + 4, level)

        notes = lay_out(score["mel"][line["m"]], head)
        chars = vox.syllables(lyrics[index])

        if notes:
            if with_voice:
                for start, midi, length, char, tie in align(chars, notes):
                    n = midi + shift
                    add(start, "voice", n, length, 1.0, char if not tie else char)
                    if level >= 3:
                        slot = next((s for s in spans if s[0] <= start < s[1]), spans[0])
                        h = harmony_below(n, slot[2])
                        if h:
                            add(start, "voice-low", h, length, 0.34, char)
            else:
                for start, midi, length in notes:
                    add(start, style["melody"], midi, length, style["melody_gain"])
                    if style["swell"] and level >= 3:
                        slot = next((s for s in spans if s[0] <= start < s[1]), spans[0])
                        h = harmony_below(midi + shift, slot[2])
                        if h:
                            add(start, "harm", h, length, style["melody_gain"] * 0.35)
        elif with_voice and chars:
            # 가락 없는 줄 — 읊조리듯
            speak = 55 + shift
            room = 7.0 / max(len(chars), 1)
            step = min(0.5, room)
            for j, char in enumerate(chars):
                add(head + 0.5 + j * step, "voice", speak - (j // 8), step * 0.9,
                    0.75, char)

        beat = head + 8

    chords(score["coda"], score["opening"]["codaShift"] if style["lift"] else 0, 0)
    return out, beat * spb


# ── 악기 소리 ───────────────────────────────────────────────────────────

def band(x, lo, hi):
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
    out = np.zeros_like(t)
    for ratio, weight, fade in ((1.0, 1.0, 1.0), (2.004, 0.30 * shine, 1.9),
                                (3.003, 0.11 * shine, 2.8), (4.01, 0.045 * shine, 4.0)):
        if freq * ratio < RATE / 2.2:
            out += weight * np.sin(2 * np.pi * freq * ratio * t) * np.exp(-t * fade / tail)
    knock = np.zeros_like(t)
    edge = int(0.006 * RATE)
    knock[:edge] = RNG.uniform(-1, 1, edge) * 0.25
    return (out + knock) * env * gain


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
        bend = np.minimum(t / 0.45, 1.0) * 0.004 * np.sin(2 * np.pi * 5.2 * t)
    body = (saw(freq, t) + saw(freq * 1.004, t) * 0.4) * (1 + bend)
    env = np.clip(t / attack, 0, 1) * np.clip((hold + 0.28 - t) / 0.28, 0, 1)
    return band(body * env, None, cutoff) * gain


def bowed(freq, dur, gain, cutoff, attack):
    t = np.arange(int((dur + attack + 0.2) * RATE)) / RATE
    body = saw(freq * 0.9959, t, 8) + saw(freq * 1.0041, t, 8)
    env = np.clip(t / attack, 0, 1) * np.clip((dur + attack - t) / attack, 0, 1)
    return band(body * env, None, cutoff) * gain


def low_end(freq, dur, gain):
    t = np.arange(int((dur + 0.2) * RATE)) / RATE
    body = np.sin(2 * np.pi * freq * t) + 0.12 * np.sin(4 * np.pi * freq * t)
    env = np.clip(t / 0.03, 0, 1) * np.clip((dur + 0.12 - t) / 0.12, 0, 1)
    return body * env * gain


def thump(gain):
    t = np.arange(int(0.4 * RATE)) / RATE
    freq = 44 + (125 - 44) * np.exp(-t / 0.028)
    return np.sin(2 * np.pi * np.cumsum(freq) / RATE) * np.exp(-t / 0.09) * gain


def hiss(dur, gain, lo, hi):
    n = int(dur * RATE)
    env = np.exp(-np.arange(n) / RATE / (dur / 3.2))
    return band(RNG.uniform(-1, 1, n) * env, lo, hi) * gain


def instrument(kind, midi, dur, gain):
    freq = 440 * 2 ** ((midi - 69) / 12) if midi else 0
    if kind == "piano":
        return struck(freq, dur, gain, 0.55, 0.75)
    if kind == "rhodes":
        return struck(freq, dur, gain, 0.9, 0.35)
    if kind == "warm":
        return sung(freq, dur, gain, 1500, 0.085, True)
    if kind == "lead":
        return sung(freq, dur, gain, 1900, 0.045, True)
    if kind == "harm":
        return sung(freq, dur, gain, 1300, 0.09, False)
    if kind == "strings":
        return bowed(freq, dur, gain, 1500, 1.0)
    if kind == "pad":
        return bowed(freq, dur, gain, 1100, 0.7)
    if kind == "bass":
        return low_end(freq, dur, gain)
    if kind == "kick":
        return thump(gain)
    if kind == "clap":
        first = hiss(0.15, gain, 900, 2600)
        second = hiss(0.19, gain * 0.7, 700, 2100)
        offset = int(0.014 * RATE)
        out = np.zeros(max(len(first), offset + len(second)))
        out[: len(first)] += first
        out[offset : offset + len(second)] += second
        return out
    if kind == "brush":
        return hiss(0.22, gain, 1200, 4200)
    if kind == "hat":
        return hiss(0.05, gain, 7000, None)
    if kind == "shaker":
        return hiss(0.07, gain, 5000, 9000)
    raise SystemExit(f"unknown voice {kind}")


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


def rms(x):
    return float(np.sqrt(np.mean(x ** 2))) or 1e-9


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = Path(args[0] if args else "palwol.wav")
    style_name = "ballad"
    if "--style" in sys.argv:
        style_name = sys.argv[sys.argv.index("--style") + 1]
    with_voice = "--no-voice" not in sys.argv

    score, lyrics = load_page(HERE / "anniversary-august-15.html")
    check(score, lyrics)
    notes, length = schedule(score, lyrics, style_name, with_voice)

    size = int((length + 3.0) * RATE)
    band_buf = np.zeros(size)
    voice_buf = np.zeros(size)

    for start, kind, midi, dur, gain, char in notes:
        if kind.startswith("voice"):
            freq = 440 * 2 ** ((midi - 69) / 12)
            chunk = vox.sing(char, freq, dur, gain, RNG)
            buf = voice_buf
        else:
            chunk = instrument(kind, midi, dur, gain)
            buf = band_buf
        at = int(start * RATE)
        buf[at : at + len(chunk)] += chunk[: size - at]

    if with_voice:
        # 목소리가 반주에 묻히지 않도록 맞춘다
        voice_buf *= (rms(band_buf) * 1.7) / rms(voice_buf)
    mix = reverb(band_buf, STYLES[style_name]["wet"]) + reverb(voice_buf, 0.14)

    mix *= 0.89 / max(np.abs(mix).max(), 1e-9)
    fade = int(2.0 * RATE)
    mix[-fade:] *= np.linspace(1, 0, fade)

    pcm = (mix * 32767).astype("<i2")
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm.tobytes())

    sung_notes = sum(1 for n in notes if n[1].startswith("voice"))
    print(f"{target}  [{style_name}{' + 노래' if with_voice else ''}]  "
          f"{len(notes)}개 소리 (그중 노래 {sung_notes})  {length:.0f}초  "
          f"{target.stat().st_size / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
