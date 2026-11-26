"""
Хуучин training data-г (mp3, m4a, wav) Opus → WebM-руу encode хийж
production-той ижил distribution-той болгоно.

Mongolian Common Voice (commonvoice25) → talking class
2 хүний яриа (2huniiyaria)           → multiple class

Хэрэглэх:
    python scripts/encode_legacy_to_webm.py

Үр дүн:
    models/training_data/talking/legacy_cv_*.webm    (~500 sample, random sub)
    models/training_data/multiple/legacy_2y_*.webm   (бүгд 117)
"""

import os
import random
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
from pydub import AudioSegment

ROOT       = Path(__file__).resolve().parent.parent
DATA_DIR   = ROOT / "data"
CV_DIR     = DATA_DIR / "commonvoice25" / "mn" / "clips"
H2_DIR     = DATA_DIR / "2huniiyaria"
TRAIN_DIR  = ROOT / "models" / "training_data"

TARGET_SR  = 16000
TARGET_LEN = 5  # секунд
N_CV       = 500  # commonvoice-аас санамсаргүйгээр сонгох тоо
SEED       = 42


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
    raise RuntimeError("ffmpeg олдсонгүй")


FFMPEG = find_ffmpeg()


def encode_to_opus_webm(src_path: Path, dst_path: Path) -> bool:
    """src audio (mp3/m4a/wav) → 16kHz mono WAV → Opus encoded WebM (5 sec)."""
    try:
        audio = AudioSegment.from_file(str(src_path))
        audio = audio.set_frame_rate(TARGET_SR).set_channels(1).set_sample_width(2)

        # 5 секундэд padding/trim
        target_ms = TARGET_LEN * 1000
        if len(audio) >= target_ms:
            # Дунд хэсгээс 5 сек авах (start/end ихэвчлэн silence)
            mid = len(audio) // 2
            audio = audio[max(0, mid - target_ms // 2): mid + target_ms // 2]
            audio = audio[:target_ms]
        else:
            # Хэт богино — silence-аар padding
            audio = audio + AudioSegment.silent(duration=target_ms - len(audio))

        # WAV хэлбэрийг tmp дээр хадгал
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_wav = tmp.name
        audio.export(tmp_wav, format="wav")

        # ffmpeg-ээр Opus → WebM (production-той ижил bitrate)
        result = subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error",
             "-i", tmp_wav, "-c:a", "libopus", "-b:a", "32k", str(dst_path)],
            capture_output=True,
        )
        os.unlink(tmp_wav)

        if result.returncode != 0:
            return False
        return True
    except Exception as e:
        print(f"   ⚠ Алдаа [{src_path.name}]: {e}")
        return False


def process_commonvoice():
    """Random sample N_CV files from commonvoice → training_data/talking/"""
    print(f"\n📂 Common Voice → talking class")
    if not CV_DIR.exists():
        print(f"   ❌ Олдсонгүй: {CV_DIR}")
        return 0

    dst_dir = TRAIN_DIR / "talking"
    dst_dir.mkdir(parents=True, exist_ok=True)

    # Хуучин legacy файлуудыг арилгах
    for old in dst_dir.glob("legacy_cv_*.webm"):
        old.unlink()

    all_files = list(CV_DIR.glob("*.mp3"))
    print(f"   Нийт олдсон: {len(all_files)} mp3")

    if len(all_files) == 0:
        return 0

    rng = random.Random(SEED)
    sample = rng.sample(all_files, min(N_CV, len(all_files)))
    print(f"   Random {len(sample)} sample сонгож encode хийнэ...")

    success = 0
    for i, src in enumerate(sample):
        dst = dst_dir / f"legacy_cv_{i:04d}.webm"
        if encode_to_opus_webm(src, dst):
            success += 1
        if (i + 1) % 50 == 0:
            print(f"   {i+1}/{len(sample)}")

    print(f"   ✅ {success}/{len(sample)} файл амжилттай")
    return success


def process_2huniiyaria():
    """All 117 files → training_data/multiple/"""
    print(f"\n📂 2huniiyaria → multiple class")
    if not H2_DIR.exists():
        print(f"   ❌ Олдсонгүй: {H2_DIR}")
        return 0

    dst_dir = TRAIN_DIR / "multiple"
    dst_dir.mkdir(parents=True, exist_ok=True)

    # Хуучин legacy файлуудыг арилгах
    for old in dst_dir.glob("legacy_2y_*.webm"):
        old.unlink()

    all_files = sorted(H2_DIR.glob("*.m4a"))
    print(f"   Нийт олдсон: {len(all_files)} m4a")

    if len(all_files) == 0:
        return 0

    success = 0
    for i, src in enumerate(all_files):
        dst = dst_dir / f"legacy_2y_{i:03d}.webm"
        if encode_to_opus_webm(src, dst):
            success += 1
        if (i + 1) % 20 == 0:
            print(f"   {i+1}/{len(all_files)}")

    print(f"   ✅ {success}/{len(all_files)} файл амжилттай")
    return success


def main():
    print("=" * 60)
    print("Legacy audio → Opus/WebM encoder")
    print("=" * 60)

    total = 0
    total += process_commonvoice()
    total += process_2huniiyaria()

    print(f"\n{'=' * 60}")
    print(f"🎉 Нийт {total} файл production-format-руу encode хийгдсэн")
    print(f"\nДараагийн алхамууд:")
    print(f"  1. python scripts/prepare_training_data.py  # newdata-ыг нэгтгэх")
    print(f"  2. training_data folder-г zip хийж Drive-руу upload")
    print(f"  3. Colab-аар retrain")


if __name__ == "__main__":
    main()
