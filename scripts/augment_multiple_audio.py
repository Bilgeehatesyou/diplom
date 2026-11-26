"""
Talking class дээжүүдийг хослуулж "multiple voices" class-ын synthetic дээж үүсгэнэ.

Audio mixing нь стандарт ML data augmentation. 2 хүний нэг зэрэг ярих
acoustic pattern-ийг random offset + random weight-ээр сайн taatraдаг.

Хэрэглэх:
    python scripts/augment_multiple_audio.py

Урьдчилсан нөхцөл:
    models/training_data/talking/*.webm — хамгийн багадаа 10 дээж
    ffmpeg PATH-д байх
"""

import json
import os
import shutil
import subprocess
import tempfile
import wave
from itertools import combinations
from pathlib import Path

import numpy as np
from pydub import AudioSegment

ROOT          = Path(__file__).resolve().parent.parent
TRAIN_DIR     = ROOT / "models" / "training_data"
TALKING_DIR   = TRAIN_DIR / "talking"
MULTIPLE_DIR  = TRAIN_DIR / "multiple"
TARGET_SR     = 16000
TARGET_LEN_S  = 5
N_SAMPLES     = 30   # үүсгэх synthetic дээжний тоо
SEED          = 42


def find_ffmpeg():
    p = shutil.which("ffmpeg")
    if p:
        return p
    candidates = [
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
    ]
    winget = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.isdir(winget):
        for pkg in os.listdir(winget):
            if "ffmpeg" in pkg.lower():
                for r, _, fs in os.walk(os.path.join(winget, pkg)):
                    for fn in fs:
                        if fn in ("ffmpeg.exe", "ffmpeg"):
                            candidates.append(os.path.join(r, fn))
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise RuntimeError("ffmpeg олдсонгүй — суулгаарай")


FFMPEG = find_ffmpeg()


def webm_to_pcm(path: Path) -> np.ndarray:
    """WebM → 16kHz mono float32 [-1, 1]."""
    audio = AudioSegment.from_file(str(path), format="webm")
    audio = audio.set_frame_rate(TARGET_SR).set_channels(1).set_sample_width(2)
    pcm = np.frombuffer(audio.raw_data, np.int16).astype(np.float32) / 32768.0
    target = TARGET_SR * TARGET_LEN_S
    return pcm[:target] if len(pcm) >= target else np.pad(pcm, (0, target - len(pcm)))


def pcm_to_webm(pcm: np.ndarray, output_path: Path):
    """PCM → WebM/Opus (production-той ижил pipeline)."""
    pcm_int16 = np.clip(pcm * 32767, -32767, 32767).astype(np.int16)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        with wave.open(wav_path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(TARGET_SR)
            f.writeframes(pcm_int16.tobytes())
        result = subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error",
             "-i", wav_path, "-c:a", "libopus", "-b:a", "32k", str(output_path)],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg алдаа: {result.stderr.decode(errors='replace')}")
    finally:
        try: os.unlink(wav_path)
        except OSError: pass


def mix_audios(a1: np.ndarray, a2: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Random offset + weight-ээр 2 audio-г хосолно."""
    # Random offset: a2-ийг 0 - 1.5 секундийн дотор саатуулна (realistic conversation overlap)
    offset = rng.integers(0, int(TARGET_SR * 1.5))
    a2_shifted = np.pad(a2, (offset, 0))[:len(a1)]
    if len(a2_shifted) < len(a1):
        a2_shifted = np.pad(a2_shifted, (0, len(a1) - len(a2_shifted)))

    # Random weights — нэг дуу нөгөөгөөсөө бага зэрэг чанга
    w1 = rng.uniform(0.45, 0.65)
    w2 = 1.0 - w1
    mixed = a1 * w1 + a2_shifted * w2

    # Clipping-аас сэргийлэх
    peak = np.abs(mixed).max()
    if peak > 0.95:
        mixed = mixed * (0.9 / peak)

    return mixed.astype(np.float32)


def main():
    if not TALKING_DIR.exists():
        print(f"❌ Talking folder олдсонгүй: {TALKING_DIR}")
        return

    talking_files = sorted(TALKING_DIR.glob("*.webm"))
    if len(talking_files) < 4:
        print(f"❌ Хэт цөөн talking дээж ({len(talking_files)}). Хамгийн багадаа 4 хэрэгтэй.")
        return

    print(f"📁 Talking файлууд: {len(talking_files)}")
    MULTIPLE_DIR.mkdir(parents=True, exist_ok=True)

    # Хуучин augmented файлуудыг арилгах (энэ скриптийн өөрийн үүсгэсэн aug_multiple_* л)
    old = list(MULTIPLE_DIR.glob("*aug_multiple_*.webm"))
    if old:
        print(f"🧹 Хуучин {len(old)} augmented дээж устгаж байна...")
        for f in old:
            f.unlink()

    rng = np.random.default_rng(SEED)
    # Random хослолуудыг үүсгэх
    all_pairs = list(combinations(range(len(talking_files)), 2))
    rng.shuffle(all_pairs)

    n_target = min(N_SAMPLES, len(all_pairs))
    print(f"🎛 {n_target} synthetic multiple-voices дээж үүсгэж байна...")

    # Ижил микрофоны клипүүдийг л холино (cm_+cm_, wc_+wc_) → mic-ээр split хийх боломжтой
    def mic(p): return p.name[:3] if p.name[:3] in ("cm_", "wc_") else ""
    all_pairs = [(a, b) for a, b in all_pairs if mic(talking_files[a]) == mic(talking_files[b])]
    n_target = min(N_SAMPLES, len(all_pairs))

    # Manifest: mix бүр аль эх клипүүдээс үүссэн бэ → scripts/audio_split.py leakage-гүй хуваахад ашиглана
    manifest = {}
    success = 0
    for i, (a_idx, b_idx) in enumerate(all_pairs[:n_target]):
        try:
            pcm_a = webm_to_pcm(talking_files[a_idx])
            pcm_b = webm_to_pcm(talking_files[b_idx])
            mixed = mix_audios(pcm_a, pcm_b, rng)
            prefix = mic(talking_files[a_idx])
            out_path = MULTIPLE_DIR / f"{prefix}aug_multiple_{i:03d}.webm"
            pcm_to_webm(mixed, out_path)
            manifest[out_path.name] = [talking_files[a_idx].name, talking_files[b_idx].name]
            success += 1
            if (i + 1) % 5 == 0:
                print(f"   {i+1}/{n_target} бэлэн")
        except Exception as e:
            print(f"   ⚠ Алдаа [{i}]: {e}")

    (MULTIPLE_DIR / "aug_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n✅ {success}/{n_target} дээж үүссэн: {MULTIPLE_DIR} (+ aug_manifest.json)")
    print(f"\nДараа нь:")
    print(f"   python scripts/retrain_audio_classifier.py")
    print(f"\nЭсвэл Colab дээр training_data.zip-нд хамтруулж upload.")


if __name__ == "__main__":
    main()
