"""
Дууны шинж чанарын unit test — синтетик дохиогоор.

  whisper : цагаан чимээ × ярианы хэмнэлтэй (4 Hz) envelope, үе хооронд завсартай
  keyboard: бараг чимээгүй фон + 8 богино (5мс) цохилт
  fan     : тогтмол цагаан чимээ
  cough   : нэг ~250мс-ийн огцом тэсрэлт

Ажиллуулах:  cd backend && python -m pytest tests/test_audio_features.py -q
         эсвэл cd backend && python tests/test_audio_features.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai import audio_features as af  # noqa: E402

SR = 16000
RNG = np.random.default_rng(0)


def whisper(sec=2.0, syl_hz=4.0, level=0.02):
    t = np.arange(int(SR * sec)) / SR
    # Үе бүр нь ~60% хугацаанд дуугарч, завсартаа бараг чимээгүй
    env = np.clip(np.sin(2 * np.pi * syl_hz * t), 0, None) ** 1.5
    return (RNG.standard_normal(len(t)) * level * (0.05 + env)).astype(np.float32)


def keyboard(sec=2.0, clicks=8):
    x = RNG.standard_normal(int(SR * sec)).astype(np.float32) * 0.001
    for c in RNG.choice(np.arange(int(0.1 * SR), int((sec - 0.1) * SR)), clicks, replace=False):
        n = int(0.005 * SR)
        x[c:c + n] += RNG.standard_normal(n) * 0.2 * np.exp(-np.arange(n) / (n / 4))
    return x


def fan(sec=2.0, level=0.01):
    return (RNG.standard_normal(int(SR * sec)) * level).astype(np.float32)


def cough(sec=2.0):
    x = RNG.standard_normal(int(SR * sec)).astype(np.float32) * 0.001
    s, n = int(0.8 * SR), int(0.25 * SR)
    x[s:s + n] += RNG.standard_normal(n) * 0.15 * np.exp(-np.arange(n) / (n / 3))
    return x


def test_whisper_is_speech_like():
    for syl in (3.0, 4.0, 6.0):
        f = af.features(whisper(syl_hz=syl), SR)
        assert af.is_speech_like(f), (syl, f)


def test_keyboard_is_impulsive_not_speech():
    f = af.features(keyboard(), SR)
    assert af.is_impulsive(f) and not af.is_speech_like(f), f


def test_fan_is_not_speech():
    f = af.features(fan(), SR)
    assert not af.is_speech_like(f) and f["mod_depth"] < af.MOD_DEPTH_MIN, f


def test_cough_is_impulsive():
    f = af.features(cough(), SR)
    assert af.is_impulsive(f), f


def test_too_short_input_is_neutral():
    f = af.features(np.zeros(100, dtype=np.float32), SR)
    assert not af.is_speech_like(f) and not af.is_impulsive(f)


if __name__ == "__main__":
    for name, sig in (("whisper", whisper()), ("keyboard", keyboard()), ("fan", fan()), ("cough", cough())):
        print(f"{name:9s}", af.features(sig, SR))
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"{len(fns)}/{len(fns)} passed")
