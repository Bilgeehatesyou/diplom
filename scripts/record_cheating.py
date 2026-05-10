#!/usr/bin/env python3
"""
Record audio samples for cheating detection classes
Run this script to record samples for: talking_to_someone, multiple_voices, whispering
"""
import sounddevice as sd
import soundfile as sf
import numpy as np
from pathlib import Path
import time

# Config
SAMPLE_RATE = 16000
DURATION = 5  # seconds per recording
DATA_DIR = Path("./data/cheating_detection/audio")

CLASSES = {
    "1": "talking_to_someone",
    "2": "multiple_voices",
    "3": "whispering",
}


def record_audio(duration: int, sample_rate: int = 16000) -> np.ndarray:
    """Record audio from microphone."""
    print(f"🎤 Recording for {duration} seconds...")
    print("   Press ENTER to start...")
    input()

    recording = sd.rec(duration * sample_rate, samplerate=sample_rate, channels=1)
    sd.wait()
    return recording.flatten()


def save_audio(audio: np.ndarray, filename: Path, sample_rate: int = 16000):
    """Save audio to file."""
    sf.write(filename, audio, sample_rate)
    print(f"   ✅ Saved: {filename}")


def main():
    print("=" * 60)
    print("  Cheating Detection - Audio Recorder")
    print("=" * 60)
    print("\nInstructions:")
    print("   You need to record at least 30 samples per class")
    print("   Each recording will be 5 seconds long")
    print("\nClasses to record:")
    for key, cls in CLASSES.items():
        folder = DATA_DIR / cls
        count = len(list(folder.glob("*.wav"))) if folder.exists() else 0
        print(f"   [{key}] {cls}: {count}/30 samples")

    print("\n" + "=" * 60)
    print("HOW TO RECORD:")
    print("=" * 60)
    print("""
1. Create a folder for each class under:
   ./data/cheating_detection/audio/

2. Recording tips:
   - talking_to_someone: Record 2 people having a conversation
   - multiple_voices: Record with multiple people talking in background
   - whispering: Record someone whispering

3. Use any recording app (phone, computer) to save WAV files
   to the corresponding folders, OR run this script.

4. File naming: {class}_{number}.wav
   Example: talking_to_someone_001.wav
""")

    print("\nDo you want to record now? (y/n)")
    response = input("> ").strip().lower()

    if response != "y":
        print("Ok, run this script when ready to record.")
        return

    print("\nSelect class to record:")
    for key, cls in CLASSES.items():
        print(f"   [{key}] {cls}")
    print("   [q] Quit")

    while True:
        print("\n" + "-" * 40)
        choice = input("Select class: ").strip()

        if choice == "q":
            break

        if choice not in CLASSES:
            print("Invalid choice!")
            continue

        cls_name = CLASSES[choice]
        cls_dir = DATA_DIR / cls_name
        cls_dir.mkdir(parents=True, exist_ok=True)

        # Count existing files
        existing = list(cls_dir.glob("*.wav"))
        start_num = len(existing) + 1

        print(f"\n📁 Recording to: {cls_dir}")
        print(f"   Starting from number: {start_num}")
        print(f"   Press ENTER to record, 'q' to stop")

        while True:
            user_input = input("Record next? (ENTER/q): ").strip()
            if user_input.lower() == 'q':
                break

            try:
                audio = record_audio(DURATION, SAMPLE_RATE)
                filename = cls_dir / f"{cls_name}_{start_num:03d}.wav"
                save_audio(audio, filename, SAMPLE_RATE)
                start_num += 1
            except Exception as e:
                print(f"❌ Error: {e}")

        # Summary
        count = len(list(cls_dir.glob("*.wav")))
        print(f"\n   Total for {cls_name}: {count} samples")


if __name__ == "__main__":
    main()