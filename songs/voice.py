"""A synthetic singing voice for the song.

Not anyone's voice — a source-filter model built from scratch: a glottal
pulse train shaped by three formant resonances, one syllable at a time.
Hangul syllables are decomposed into onset / vowel / coda, and each vowel
carries its own formant targets, so the voice pronounces the words.

Three things decide whether the words are audible at all:

  1. Pitch. Narrow formants only pass the harmonics that land inside them,
     so a high sung note starves the vowel of evidence. The voice sings a
     full octave below the written melody, in a baritone range where the
     harmonics are close enough together to draw the vowel.
  2. Formant width. Wide enough that several harmonics get through.
  3. Consonants. A burst alone is not a consonant — the ear reads the
     place of articulation from the way F2 slides out of it. Each onset
     therefore starts F2 at its own locus and glides into the vowel.

Used by render_audio.py; the page carries the same tables in JavaScript.
"""

import numpy as np

RATE = 32000

# 사람이 알아듣는 높이로 — 쓰여진 가락보다 한 옥타브 아래에서 부른다
SHIFT = -12

# 포먼트의 폭. 좁으면 배음이 그 사이를 빠져나가 모음이 사라진다.
BW = (130, 170, 250)
AMP = (1.0, 0.55, 0.28)

# 자음이 끝나는 자리 — F2가 여기서 모음 쪽으로 미끄러진다
LOCUS = {"labial": 800, "alveolar": 1750, "velar": 2000}

# 모음 포먼트 (F1, F2, F3) — 남성 음역 기준
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

# 초성 19자 → (자리, 세기)
ONSET = [
    ("velar", "lenis"), ("velar", "tense"), ("nasal", None),
    ("alveolar", "lenis"), ("alveolar", "tense"), ("liquid", None),
    ("nasal", None), ("labial", "lenis"), ("labial", "tense"),
    ("fricative", "lenis"), ("fricative", "tense"), (None, None),
    ("affricate", "lenis"), ("affricate", "tense"), ("affricate", "aspirated"),
    ("velar", "aspirated"), ("alveolar", "aspirated"), ("labial", "aspirated"),
    ("breath", None),
]

CLOSURE = {"lenis": 0.030, "tense": 0.045, "aspirated": 0.028}
ASPIRATION = {"lenis": 0.022, "tense": 0.008, "aspirated": 0.055}
BURST = {"labial": 900, "alveolar": 2700, "velar": 1900}
BURST_GAIN = {"lenis": 0.7, "tense": 1.0, "aspirated": 0.85}

JONG_NASAL = {4, 16, 21}      # ㄴ ㅁ ㅇ
JONG_LIQUID = {8}             # ㄹ


def decompose(ch):
    """한글 한 글자 → (초성, 중성, 종성) 번호. 한글이 아니면 None."""
    code = ord(ch) - 0xAC00
    if not 0 <= code < 11172:
        return None
    return code // 588, (code % 588) // 28, code % 28


def syllables(text):
    return [ch for ch in text if decompose(ch) is not None]


# ── 소리 만들기 ─────────────────────────────────────────────────────────

def glottal(freq, n, scoop=True, rng=None):
    """성대 파형 — 배음이 완만하게 떨어지는 펄스열."""
    t = np.arange(n) / RATE
    f = np.full(n, float(freq))
    if scoop:
        f = f * (1 - 0.035 * np.exp(-t / 0.03))
    # 비브라토는 얕게. 깊으면 포먼트가 흔들려 모음이 뭉개진다.
    f = f * (1 + 0.0032 * np.minimum(t / 0.7, 1.0) * np.sin(2 * np.pi * 5.0 * t))
    if rng is not None:
        f = f * (1 + rng.normal(0, 0.0008, n).cumsum() * 0.015)
    phase = 2 * np.pi * np.cumsum(f) / RATE
    out = np.zeros(n)
    for k in range(1, 61):
        if freq * k > RATE / 2.2:
            break
        out += np.sin(phase * k) / (k ** 1.2)
    return out


def shape(x, formants, breathy=0.015):
    """세 개의 공명으로 모음 색을 입힌다."""
    spec = np.fft.rfft(x)
    fr = np.fft.rfftfreq(len(x), 1 / RATE)
    h = np.zeros_like(fr)
    for f, bw, amp in zip(formants, BW, AMP):
        h += amp / (1 + ((fr - f) / (bw / 2)) ** 2)
    h += breathy / (1 + (fr / 3500) ** 2)
    return np.fft.irfft(spec * h, n=len(x))


def noise(n, centre, width, rng):
    x = rng.uniform(-1, 1, n)
    spec = np.fft.rfft(x)
    fr = np.fft.rfftfreq(n, 1 / RATE)
    return np.fft.irfft(spec * (1 / (1 + ((fr - centre) / width) ** 2)), n=n)


def ramp(n, lo, hi):
    return np.linspace(lo, hi, max(n, 1))


def onset(kind, force, vowel, freq, rng):
    """자음 하나 → (소리, F2가 출발할 자리). 소리가 곧 모음까지의 시간."""
    if kind is None:
        return np.zeros(0), None

    if kind in ("labial", "alveolar", "velar"):
        gap = int(CLOSURE[force] * RATE)
        burst_n = int(0.016 * RATE)
        asp_n = int(ASPIRATION[force] * RATE)
        out = np.zeros(gap + burst_n + asp_n)
        out[gap : gap + burst_n] = (
            noise(burst_n, BURST[kind], 1100, rng) * BURST_GAIN[force]
            * ramp(burst_n, 1.0, 0.3))
        if asp_n:
            breath = shape(noise(asp_n, 1600, 2600, rng), vowel, breathy=0.4)
            out[gap + burst_n :] = breath * ramp(asp_n, 0.55, 0.2)
        return out, LOCUS[kind]

    if kind == "affricate":
        gap = int(CLOSURE[force] * RATE)
        fric_n = int((0.075 if force == "aspirated" else 0.055) * RATE)
        out = np.zeros(gap + fric_n)
        out[gap:] = noise(fric_n, 3400, 1600, rng) * 0.55 * ramp(fric_n, 0.5, 1.0)
        return out, LOCUS["alveolar"]

    if kind == "fricative":
        n = int((0.10 if force == "tense" else 0.085) * RATE)
        return noise(n, 5200, 2400, rng) * 0.5 * ramp(n, 0.3, 1.0), LOCUS["alveolar"]

    if kind == "breath":
        n = int(0.06 * RATE)
        return shape(noise(n, 1400, 2400, rng), vowel, breathy=0.5) * ramp(n, 0.2, 0.8), None

    if kind == "nasal":
        n = int(0.07 * RATE)
        hum = shape(glottal(freq, n, scoop=False), (280, 1000, 2300))
        return hum * 0.7 * ramp(n, 0.6, 1.0), LOCUS["alveolar"]

    if kind == "liquid":
        n = int(0.04 * RATE)
        flap = shape(glottal(freq, n, scoop=False), (400, 1150, 2600))
        return flap * 0.75 * ramp(n, 0.4, 1.0), 1150

    return np.zeros(0), None


def coda(jong, vowel, freq, n, rng):
    """받침 — 콧소리나 혀끝소리로 음절을 닫는다."""
    if jong in JONG_NASAL:
        hum = shape(glottal(freq, n, scoop=False), (270, 1050, 2300))
        return hum * 0.75
    if jong in JONG_LIQUID:
        return shape(glottal(freq, n, scoop=False), (400, 1150, 2600)) * 0.7
    return None


def sing(char, freq, dur, gain, rng, tie=False):
    """음절 하나를 그 높이로 부른다."""
    parts = decompose(char) if char else None
    if parts is None:
        return np.zeros(int(dur * RATE))
    cho, jung, jong = parts
    glide, steady = JUNG[jung]
    fa, fb = VOWEL[glide], VOWEL[steady]

    head, locus = (np.zeros(0), None) if tie else onset(
        *ONSET[cho], fb, freq, rng)

    total = int(dur * RATE)
    voiced_n = max(total - len(head), int(0.08 * RATE))
    src = glottal(freq, voiced_n, scoop=not tie, rng=rng)

    # 자리 → 미끄러지는 모음 → 머무는 모음, 세 걸음으로 옮겨간다
    layers = []
    if locus is not None:
        layers.append((shape(src, (fa[0] * 0.6, locus, fa[2])), int(0.045 * RATE)))
    layers.append((shape(src, fa), int(0.085 * RATE)))
    tail_layer = shape(src, fb) if fa != fb else layers[-1][0]

    body = tail_layer.copy()
    edge = 0
    for layer, span in layers:
        span = min(span, max(voiced_n - edge, 1))
        blend = np.linspace(0, 1, span)
        body[edge : edge + span] = (
            layer[edge : edge + span] * (1 - blend) + body[edge : edge + span] * blend)
        if edge > 0:
            body[:edge] = layer[:edge]
        edge += span

    env = np.ones(voiced_n)
    rise = min(int(0.014 * RATE), voiced_n)
    fall = min(int(0.045 * RATE), voiced_n)
    env[:rise] = np.linspace(0, 1, rise)
    env[-fall:] *= np.linspace(1, 0.2, fall)
    body = body * env

    closer = coda(jong, fb, freq, min(int(0.085 * RATE), voiced_n // 3), rng)
    if closer is not None and len(closer) > 8:
        body[-len(closer):] = body[-len(closer):] * 0.3 + closer * np.linspace(1, 0, len(closer))

    out = np.zeros(len(head) + voiced_n)
    out[: len(head)] += head
    out[len(head):] += body
    return out * gain
