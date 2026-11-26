"""
Дууны энгийн дохионы шинж чанарууд — яриа/шивнээг чимээнээс (гарын товшилт, сэнс) ялгах.

Өмнө нь шивнээг зөвхөн дууны түвшнээр (RMS) илрүүлдэг байсан тул гарын товшилт, сэнс,
цаас шаржигнах чимээ "шивнээ" болж бүртгэгддэг байв. Энд 20мс-ийн фрэймийн энергийн
муруй (envelope)-аас гурван шинж гаргана:

  concentration  Нийт энергийн хэдэн хувь нь хамгийн чанга 5% фрэймд төвлөрсөн бэ.
                 Гарын товшилт = цөөн богино цохилт → өндөр (≥0.5).
                 Яриа/шивнээ = энерги үеүдэд тархсан → бага.
  mod_depth      Envelope-ийн хэлбэлзэл (std/mean). Сэнс, агааржуулагч = тогтмол → бага (<0.3).
                 Яриа = үе үеэрээ чангарч намддаг → өндөр.
  syllabic       Envelope-ийн хэлбэлзлийн энергийн хэдэн хувь нь 2–8 Hz-д байна вэ —
                 хүний ярианы үеийн давтамж (секундэд 2–8 үе).

Босгууд нь синтетик дохиогоор шалгагдсан heuristic; бодит бичлэг дээр тааруулах шаардлагатай.
"""
import numpy as np

FRAME_MS = 20
CONCENTRATION_IMPULSIVE = 0.5
MOD_DEPTH_MIN = 0.3
SYLLABIC_MIN  = 0.4


def envelope(x: np.ndarray, sr: int, frame_ms: int = FRAME_MS) -> np.ndarray | None:
    n = int(sr * frame_ms / 1000)
    k = len(x) // n if n > 0 else 0
    if k < 8:
        return None
    frames = x[:k * n].reshape(k, n)
    return np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)


def features(x: np.ndarray, sr: int) -> dict:
    env = envelope(x, sr)
    if env is None:
        return {"concentration": 0.0, "mod_depth": 0.0, "syllabic": 0.0}
    e2 = env ** 2
    top = max(1, int(round(len(e2) * 0.05)))
    concentration = float(np.sort(e2)[-top:].sum() / (e2.sum() + 1e-12))
    mod_depth = float(np.std(env) / (np.mean(env) + 1e-12))
    rate = 1000.0 / FRAME_MS
    spec = np.abs(np.fft.rfft(env - env.mean())) ** 2
    freqs = np.fft.rfftfreq(len(env), 1.0 / rate)
    band  = spec[(freqs >= 2) & (freqs <= 8)].sum()
    total = spec[(freqs >= 0.5) & (freqs <= 20)].sum() + 1e-12
    return {"concentration": round(concentration, 3),
            "mod_depth": round(mod_depth, 3),
            "syllabic": round(float(band / total), 3)}


def is_impulsive(f: dict) -> bool:
    """Гарын товшилт, тогших, ханиах зэрэг богино цохилт давамгайлсан эсэх."""
    return f["concentration"] >= CONCENTRATION_IMPULSIVE


def is_speech_like(f: dict) -> bool:
    """Ярианы хэмнэлтэй (үе үеэрээ хэлбэлздэг), цохилтот биш дуу."""
    return (not is_impulsive(f)) and f["mod_depth"] >= MOD_DEPTH_MIN and f["syllabic"] >= SYLLABIC_MIN
