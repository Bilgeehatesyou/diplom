#!/usr/bin/env python3
"""
Cheating Detection Audio Classification - Data Preparation
Prepare audio data into 4 classes: normal, talking_to_someone, multiple_voices, whispering
"""
import os
import shutil
import subprocess
from pathlib import Path
import random

# Config
DATA_DIR = Path("./data/cheating_detection")
NORMAL_DIR = Path("./data/wav2vec_commonvoice/audio")
TARGET_SAMPLE_RATE = 16000

CLASSES = ["normal", "talking_to_someone", "multiple_voices", "whispering"]


def convert_to_wav(audio_path: Path, output_path: Path):
    """Convert any audio to WAV (16kHz, mono)."""
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-ar", str(TARGET_SAMPLE_RATE),
        "-ac", "1",
        "-hide_banner", "-loglevel", "error",
        str(output_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def prepare_normal_class(output_dir: Path, max_samples: int = 1000):
    """Use existing Common Voice data as 'normal' class."""
    normal_audio_dir = output_dir / "audio" / "normal"
    normal_audio_dir.mkdir(parents=True, exist_ok=True)

    train_dir = NORMAL_DIR / "train"
    val_dir = NORMAL_DIR / "val"

    all_wavs = []
    if train_dir.exists():
        all_wavs.extend(list(train_dir.glob("*.wav")))
    if val_dir.exists():
        all_wavs.extend(list(val_dir.glob("*.wav")))

    random.shuffle(all_wavs)
    all_wavs = all_wavs[:max_samples]

    print(f"   📦 Preparing {len(all_wavs)} normal samples...")
    for i, src in enumerate(all_wavs):
        dst = normal_audio_dir / f"normal_{i:06d}.wav"
        if src != dst:
            shutil.copy2(src, dst)

    return len(all_wavs)


def setup_folder_structure(output_dir: Path):
    """Create folder structure for all classes."""
    for cls in CLASSES:
        cls_dir = output_dir / "audio" / cls
        cls_dir.mkdir(parents=True, exist_ok=True)

    # Create metadata file
    meta_path = output_dir / "metadata.csv"
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("file_name,label\n")

    return meta_path


def create_train_val_split(output_dir: Path, train_ratio: float = 0.8):
    """Split data into train/val sets."""
    import pandas as pd

    all_data = []
    for cls in CLASSES:
        cls_dir = output_dir / "audio" / cls
        if cls_dir.exists():
            for wav_file in cls_dir.glob("*.wav"):
                all_data.append({
                    "file_name": str(wav_file.relative_to(output_dir)),
                    "label": cls,
                    "path": str(wav_file)
                })

    if not all_data:
        print("❌ No data found! Please add audio files to each class folder.")
        return

    df = pd.DataFrame(all_data)
    df = df.sample(frac=1, random_state=42)  # shuffle

    split_idx = int(len(df) * train_ratio)
    train_df = df.iloc[:split_idx]
    val_df = df.iloc[split_idx:]

    train_df.to_csv(output_dir / "train.csv", index=False)
    val_df.to_csv(output_dir / "val.csv", index=False)

    print(f"   ✅ Train: {len(train_df)}, Val: {len(val_df)}")

    # Print class distribution
    print("\n   📊 Class distribution:")
    for cls in CLASSES:
        train_count = len(train_df[train_df["label"] == cls])
        val_count = len(val_df[val_df["label"] == cls])
        print(f"      {cls}: train={train_count}, val={val_count}")


def main():
    print("=" * 60)
    print("  Cheating Detection - Data Preparation")
    print("=" * 60)
    print()

    # Create folders
    print("[1/3] Creating folder structure...")
    setup_folder_structure(DATA_DIR)

    # Prepare normal class from existing data
    print("[2/3] Preparing 'normal' class from Common Voice...")
    normal_count = prepare_normal_class(DATA_DIR, max_samples=1000)

    print(f"\n   ✅ Normal class ready: {normal_count} samples")
    print("\n📝 NEXT STEPS:")
    print("   1. Add your recorded audio to these folders:")
    for cls in CLASSES[1:]:  # Skip normal
        print(f"      - {DATA_DIR / 'audio' / cls}")
    print("\n   2. Each folder should have at least 30 samples for good accuracy")
    print("   3. Then run this script again to create train/val split:")
    print(f"      python scripts/prepare_classification.py --split")

    # Check if we should split
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--split":
        print("\n[3/3] Creating train/val split...")
        create_train_val_split(DATA_DIR)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--split":
        create_train_val_split(DATA_DIR)
    else:
        main()