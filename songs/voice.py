"""A synthetic singing voice for the song.

Not anyone's voice — a source-filter model built from scratch: a glottal
pulse train shaped by three formant resonances, one syllable at a time.
Hangul syllables are decomposed into onset / vowel / coda, and each vowel
carries its own formant targets, so the voice actually pronounces the words.

Used by render_audio.py; the page carries the same tables in JavaScript.
"""

import numpy as np

RATE = 32000

# 초성 · 중성 · 종성
CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JONG_NASAL = {4, 16, 21}      # ㄴ ㅁ ㅇ
JONG_LIQUID = {8}             # ㄹ

# 모음 포먼트 (F1, F2, F3)
VOWEL = {
    "a":  (730, 1090, 2440),
    "ae": (590, 1900, 2550),
    "e":  (530, 1840, 2480),
    "i":  (270, 2290, 3010),
    "o":  (570,  840, 2410),
    "u":  (300,  870, 2240),
    "eu": (300, 1400, 2200),
    "eo": (640, 1190, 2390),
    "oe": (500, 1700, 2400),
}

# 중성 21자 → (미끄러져 들어오는 소리, 머무는 소리)
JUNG = [
    ("a", "a"), ("ae", "ae"), ("i", "a"), ("i", "ae"), ("eo", "eo"),
    ("e", "e"), ("i", "eo"), ("i", "e"), ("o", "o"), ("u", "a"),
    ("u", "ae"), ("oe", "oe"), ("i", "o"), ("u", "u"), ("u", "eo"),
    ("u", "e"), ("u", "i"), ("i", "u"), ("eu", "eu"), ("eu", "i"),
    ("i", "i"),
]

# 초성 19자 → 자음의 종류
ONSET = [
    "velar", "velar", "nasal", "alveolar", "alveolar", "liquid", "nasal",
    "labial", "labial", "fricative", "fricative", None, "affricate",
    "affricate", "affricate", "velar", "alveolar", "labial", "breath",
]

BURST = {"labial": 700, "alveolar": 2600, "velar": 1800}


def decompose(ch):
    """한글 한 글자 → (초성, 중성, 종성) 번호. 한글이 아니면 None."""
    code = ord(ch) - 0xAC00
    if not 0 <= code < 11172:
        return None
    return code // 588, (code % 588) // 28, code % 28


def syllables(text):
    """가사 한 줄에서 한글 음절만 뽑는다."""
    return [ch for ch in text if decompose(ch) is not None]


# ── 소리 만들기 ─────────────────────────────────────────────────────────

def glottal(freq, n, scoop=True, vibrato=True, rng=None):
    """성대 파형 — 배음이 완만하게 떨어지는 펄스열."""
    t = np.arange(n) / RATE
    f = np.full(n, float(freq))
    if scoop:
        f = f * (1 - 0.045 * np.exp(-t / 0.035))
    if vibrato:
        f = f * (1 + 0.006 * np.minimum(t / 0.5, 1.0) * np.sin(2 * np.pi * 5.4 * t))
    if rng is not None:
        f = f * (1 + rng.normal(0, 0.0012, n).cumsum() * 0.02)
    phase = 2 * np.pi * np.cumsum(f) / RATE
    out = np.zeros(n)
    for k in range(1, 41):
        if freq * k > RATE / 2.2:
            break
        out += np.sin(phase * k) / (k ** 1.35)
    return out


def shape(x, formants, breathy=0.02):
    """세 개의 공명으로 모음 색을 입힌다."""
    spec = np.fft.rfft(x)
    fr = np.fft.rfftfreq(len(x), 1 / RATE)
    h = np.zeros_like(fr)
    for f, bw, amp in zip(formants, (90, 110, 170), (1.0, 0.6, 0.32)):
        h += amp / (1 + ((fr - f) / (bw / 2)) ** 2)
    h += breathy / (1 + (fr / 4000) ** 2)
    return np.fft.irfft(spec * h, n=len(x))


def noise(n, centre, width, rng):
    x = rng.uniform(-1, 1, n)
    spec = np.fft.rfft(x)
    fr = np.fft.rfftfreq(n, 1 / RATE)
    h = 1 / (1 + ((fr - centre) / width) ** 2)
    return np.fft.irfft(spec * h, n=n)


def consonant(kind, vowel_formants, freq, rng):
    """자음 하나. (소리, 앞의 묵음 길이) 를 돌려준다."""
    if kind is None:
        return np.zeros(0), 0.0
    if kind in ("labial", "alveolar", "velar"):
        gap = 0.028
        n = int(0.014 * RATE)
        return noise(n, BURST[kind], 900, rng) * 0.5, gap
    if kind == "affricate":
        gap = 0.022
        n = int(0.06 * RATE)
        env = np.linspace(0.3, 1.0, n) ** 2
        return noise(n, 3600, 1800, rng) * env * 0.32, gap
    if kind == "fricative":
        n = int(0.085 * RATE)
        env = np.linspace(0.2, 1.0, n) ** 2
        return noise(n, 5600, 2600, rng) * env * 0.3, 0.0
    if kind == "breath":
        n = int(0.055 * RATE)
        env = np.linspace(0.15, 1.0, n)
        return shape(noise(n, 1500, 2500, rng), vowel_formants) * env * 0.5, 0.0
    if kind == "nasal":
        n = int(0.06 * RATE)
        hum = shape(glottal(freq, n, scoop=False, vibrato=False), (280, 1100, 2300))
        return hum * np.linspace(0.5, 1.0, n) * 0.55, 0.0
    if kind == "liquid":
        n = int(0.032 * RATE)
        flap = shape(glottal(freq, n, scoop=False, vibrato=False), (420, 1050, 2600))
        return flap * np.linspace(0.35, 1.0, n) * 0.6, 0.0
    return np.zeros(0), 0.0


def sing(char, freq, dur, gain, rng, tie=False):
    """음절 하나를 그 높이로 부른다."""
    parts = decompose(char) if char else None
    if parts is None:
        return np.zeros(int(dur * RATE))
    cho, jung, jong = parts
    glide, steady = JUNG[jung]
    fa, fb = VOWEL[glide], VOWEL[steady]

    head, gap = (np.zeros(0), 0.0) if tie else consonant(
        ONSET[cho], fb, freq, rng)
    coda_kind = "nasal" if jong in JONG_NASAL else (
        "liquid" if jong in JONG_LIQUID else None)

    total = int(dur * RATE)
    lead = int(gap * RATE) + len(head)
    voiced_n = max(total - lead, int(0.06 * RATE))

    src = glottal(freq, voiced_n, scoop=not tie, rng=rng)
    a = shape(src, fa)
    b = shape(src, fb)
    blend = np.minimum(np.arange(voiced_n) / max(int(0.09 * RATE), 1), 1.0)
    if fa == fb:
        blend[:] = 1.0
    body = a * (1 - blend) + b * blend

    env = np.ones(voiced_n)
    rise = int(0.022 * RATE)
    fall = int(0.05 * RATE)
    env[:rise] = np.linspace(0, 1, rise)
    env[-fall:] *= np.linspace(1, 0.25, fall)
    body = body * env

    if coda_kind:
        tail_n = int(0.075 * RATE)
        if voiced_n > tail_n * 2:
            tail, _ = consonant(coda_kind, fb, freq, rng)
            tail = tail[:tail_n] * np.linspace(1, 0, min(tail_n, len(tail)))
            body[-len(tail):] = body[-len(tail):] * 0.35 + tail

    out = np.zeros(lead + voiced_n)
    if len(head):
        out[int(gap * RATE) : int(gap * RATE) + len(head)] += head
    out[lead:] += body
    return out * gain
