#!/usr/bin/env python3
"""
AI Proctor - Audio Cheating Classifier v2  (Colab-ready)
=========================================================
Fixes from v1:
  - WRONG: Wav2Vec2ForCTC with replaced lm_head → CTC loss (broken for classification)
  - RIGHT: AutoModelForAudioClassification (WavLM) → CrossEntropy loss
  - Two-phase training: freeze feature extractor → full fine-tune
  - SpecAugment + noise + speed/pitch augmentation
  - Synthetic multi-voice generation for "multiple_voices" class

HOW TO RUN IN GOOGLE COLAB
===========================
1. Upload this file and your data/ folder to Colab (or mount Google Drive)
2. Run each cell in order
3. Download the saved model from ./models/cheating_classifier_v2/

DATA FOLDER STRUCTURE EXPECTED
================================
data/cheating_detection/
  audio/
    normal/                  ← single person speaking normally (use Common Voice MN)
    talking_to_someone/      ← 2 people conversing
    multiple_voices/         ← 3+ people, background chatter
    whispering/              ← whispering speech

Minimum: 50+ samples per class. 100+ is better. 200+ is great.
If you have less, the synthetic augmentation in Cell 6 will help.
"""

# ─────────────────────────────────────────────────────────────────────────────
# CELL 1: Install dependencies  (run once in Colab)
# ─────────────────────────────────────────────────────────────────────────────
# !apt-get install -q ffmpeg          # needed to read M4A files
# !pip install -q transformers datasets soundfile librosa torch torchaudio \
#              accelerate scikit-learn matplotlib seaborn

# ─────────────────────────────────────────────────────────────────────────────
# CELL 2: Imports & Config
# ─────────────────────────────────────────────────────────────────────────────
import os, json, random, shutil
import numpy as np
import torch
import soundfile as sf
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from transformers import (
    AutoFeatureExtractor,
    AutoModelForAudioClassification,
    TrainingArguments,
    Trainer,
)
from datasets import Dataset
from sklearn.metrics import confusion_matrix, classification_report
import librosa


# ── Weighted Trainer — fixes class imbalance by up-weighting minority classes ─
class WeightedTrainer(Trainer):
    def __init__(self, *args, class_weights=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights   # list/tensor, one per label

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels  = inputs.get("labels")
        outputs = model(**inputs)
        logits  = outputs.logits
        if self.class_weights is not None:
            w       = torch.tensor(self.class_weights, dtype=torch.float32, device=logits.device)
            loss_fn = torch.nn.CrossEntropyLoss(weight=w)
        else:
            loss_fn = torch.nn.CrossEntropyLoss()
        loss = loss_fn(logits, labels)
        return (loss, outputs) if return_outputs else loss

# ── Config ────────────────────────────────────────────────────────────────────
# WavLM-base-plus is purpose-built for audio understanding (not just ASR).
# It outperforms wav2vec2-base on classification benchmarks.
# Fallback: "facebook/wav2vec2-base" if WavLM is too slow in Colab.
BASE_MODEL   = "microsoft/wavlm-base-plus"
SAMPLE_RATE  = 16000
MAX_DURATION = 5         # seconds per sample
MAX_LENGTH   = SAMPLE_RATE * MAX_DURATION  # 80 000 samples

DATA_DIR        = Path("./data/cheating_detection")
OUT_DIR         = Path("./models/cheating_classifier_v2")
COMMONVOICE_DIR = Path("./data/cv_sample")       # 400 sampled MP3s → normal class
TALKING_DIR     = Path("./data/2huniiyaria")     # M4A recordings → talking_to_someone
WHISPER_DIR     = Path("./data/whisper")         # M4A recordings → whispering

LABELS   = ["normal", "talking_to_someone", "multiple_voices", "whispering"]
LABEL2ID = {l: i for i, l in enumerate(LABELS)}
ID2LABEL = {i: l for i, l in enumerate(LABELS)}

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")
print(f"Base model: {BASE_MODEL}")

# ─────────────────────────────────────────────────────────────────────────────
# CELL 3: Audio I/O helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_audio(path: str) -> np.ndarray:
    audio, sr = sf.read(path)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SAMPLE_RATE:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=SAMPLE_RATE)
    return audio.astype(np.float32)


def pad_or_crop(audio: np.ndarray, max_len: int = MAX_LENGTH,
                training: bool = True) -> np.ndarray:
    if len(audio) >= max_len:
        if training:
            start = random.randint(0, len(audio) - max_len)
            return audio[start : start + max_len]
        return audio[:max_len]
    return np.pad(audio, (0, max_len - len(audio)))


# ─────────────────────────────────────────────────────────────────────────────
# CELL 4: Data augmentation
# ─────────────────────────────────────────────────────────────────────────────

def aug_noise(audio: np.ndarray, snr_db: float = None) -> np.ndarray:
    snr_db = snr_db or random.uniform(10, 30)
    sig_pow = np.mean(audio ** 2) + 1e-9
    noise   = np.random.normal(0, np.sqrt(sig_pow / (10 ** (snr_db / 10))), len(audio))
    return (audio + noise).astype(np.float32)


def aug_volume(audio: np.ndarray) -> np.ndarray:
    return (audio * random.uniform(0.4, 1.6)).astype(np.float32)


def aug_speed(audio: np.ndarray) -> np.ndarray:
    rate = random.uniform(0.85, 1.15)
    out  = librosa.effects.time_stretch(audio, rate=rate)
    return out.astype(np.float32)


def aug_pitch(audio: np.ndarray) -> np.ndarray:
    steps = random.randint(-4, 4)
    out   = librosa.effects.pitch_shift(audio, sr=SAMPLE_RATE, n_steps=steps)
    return out.astype(np.float32)


def aug_reverb(audio: np.ndarray) -> np.ndarray:
    delay = int(random.uniform(0.02, 0.1) * SAMPLE_RATE)
    rev   = np.zeros_like(audio)
    rev[delay:] = audio[:-delay] * random.uniform(0.1, 0.4)
    return (audio + rev).astype(np.float32)


def augment(audio: np.ndarray, p: float = 0.85) -> np.ndarray:
    if random.random() > p:
        return audio
    fns = [aug_noise, aug_volume, aug_reverb]
    try:
        fns += [aug_speed, aug_pitch]
    except Exception:
        pass
    # Apply 1–2 random augmentations
    chosen = random.sample(fns, k=random.randint(1, 2))
    for fn in chosen:
        try:
            audio = fn(audio)
        except Exception:
            pass
    return audio


# ─────────────────────────────────────────────────────────────────────────────
# CELL 4b: Copy recorded M4A files into training structure
# ─────────────────────────────────────────────────────────────────────────────

def setup_recorded_class(src_dir: Path, cls_name: str):
    """
    Reads M4A (or WAV/MP3) recordings from src_dir,
    converts them to 16kHz mono WAV and saves into
    data/cheating_detection/audio/<cls_name>/.
    """
    out_dir = DATA_DIR / "audio" / cls_name
    out_dir.mkdir(parents=True, exist_ok=True)

    existing = list(out_dir.glob("*.wav"))
    audio_files = (
        list(src_dir.glob("*.m4a")) +
        list(src_dir.glob("*.wav")) +
        list(src_dir.glob("*.mp3")) +
        list(src_dir.glob("*.ogg"))
    )

    if not audio_files:
        print(f"  WARNING: No audio files found in {src_dir}")
        return

    already_done = {f.stem for f in existing}
    new_files = [f for f in audio_files if f.stem not in already_done]

    if not new_files:
        print(f"  {cls_name}: all {len(existing)} files already converted, skipping")
        return

    print(f"  Converting {len(new_files)} files for '{cls_name}'...")
    saved = 0
    for src in new_files:
        try:
            # librosa handles M4A via audioread/ffmpeg
            audio = librosa.load(str(src), sr=SAMPLE_RATE, mono=True)[0].astype(np.float32)
            if len(audio) < SAMPLE_RATE * 1:
                continue
            audio = pad_or_crop(audio, training=False)
            sf.write(out_dir / f"{src.stem}.wav", audio, SAMPLE_RATE)
            saved += 1
        except Exception as e:
            print(f"    Skip {src.name}: {e}")

    total = len(list(out_dir.glob("*.wav")))
    print(f"  Done. '{cls_name}': {total} samples total")


# ─────────────────────────────────────────────────────────────────────────────
# CELL 5: Synthetic data generation
# Mixes audio files to create extra training samples for scarce classes.
# ─────────────────────────────────────────────────────────────────────────────

def mix_two_speakers(a1: np.ndarray, a2: np.ndarray) -> np.ndarray:
    """Overlay two mono signals at slightly different volumes."""
    min_len = min(len(a1), len(a2), MAX_LENGTH)
    a1 = a1[:min_len]
    a2 = a2[:min_len]
    ratio = random.uniform(0.4, 0.6)
    mixed = ratio * a1 + (1 - ratio) * a2
    return mixed.astype(np.float32)


def generate_synthetic_samples(cls_name: str, audio_dir: Path,
                                out_dir: Path, target_count: int = 80):
    """
    For 'talking_to_someone'  → mix pairs from normal class
    For 'multiple_voices'     → mix 3 files from normal class with random offsets
    For 'whispering'          → lower volume + add distance reverb
    """
    existing = list((audio_dir / cls_name).glob("*.wav"))
    if len(existing) >= target_count:
        print(f"  {cls_name}: already has {len(existing)} samples, skipping synthesis")
        return

    out_cls = out_dir / cls_name
    out_cls.mkdir(parents=True, exist_ok=True)

    normal_files = list((audio_dir / "normal").glob("*.wav"))
    if len(normal_files) < 2:
        print(f"  Not enough 'normal' files to synthesise {cls_name}")
        return

    needed = target_count - len(existing)
    print(f"  Synthesising {needed} extra samples for '{cls_name}'...")

    for i in range(needed):
        try:
            if cls_name == "talking_to_someone":
                f1, f2 = random.sample(normal_files, 2)
                audio   = mix_two_speakers(load_audio(str(f1)), load_audio(str(f2)))

            elif cls_name == "multiple_voices":
                files = random.sample(normal_files, min(3, len(normal_files)))
                audios = [load_audio(str(f)) for f in files]
                # Stagger the start times
                base   = audios[0].copy()
                for j, a in enumerate(audios[1:], 1):
                    offset = int(j * 0.8 * SAMPLE_RATE)
                    end    = min(len(base), offset + len(a))
                    base[offset:end] += a[:end - offset] * 0.6
                audio = base.astype(np.float32)

            elif cls_name == "whispering":
                f     = random.choice(normal_files)
                audio = load_audio(str(f))
                audio = (audio * random.uniform(0.05, 0.2)).astype(np.float32)
                audio = aug_reverb(audio)

            else:
                continue

            audio = pad_or_crop(audio, training=True)
            sf.write(out_cls / f"synth_{i:05d}.wav", audio, SAMPLE_RATE)
        except Exception as e:
            print(f"    synthesis error sample {i}: {e}")

    print(f"  Done. Total for '{cls_name}': {len(list(out_cls.glob('*.wav'))) + len(existing)}")


def setup_normal_from_commonvoice(target_count: int = 300):
    """
    Common Voice MN clips-аас 'normal' class-ийн дата бэлдэнэ.
    MP3-г librosa-аар унших тул soundfile хэрэггүй.
    """
    out_dir = DATA_DIR / "audio" / "normal"
    out_dir.mkdir(parents=True, exist_ok=True)

    existing = list(out_dir.glob("*.wav"))
    if len(existing) >= target_count:
        print(f"  normal: already has {len(existing)} samples, skipping")
        return

    if not COMMONVOICE_DIR.exists():
        print(f"  WARNING: Common Voice folder not found: {COMMONVOICE_DIR}")
        print("  Set COMMONVOICE_DIR at the top of this script.")
        return

    mp3_files = list(COMMONVOICE_DIR.glob("*.mp3"))
    if not mp3_files:
        print(f"  WARNING: No MP3 files in {COMMONVOICE_DIR}")
        return

    random.shuffle(mp3_files)
    needed = target_count - len(existing)
    print(f"  Preparing {needed} 'normal' samples from {len(mp3_files)} Common Voice clips...")

    saved = 0
    for mp3 in mp3_files:
        if saved >= needed:
            break
        try:
            audio = librosa.load(str(mp3), sr=SAMPLE_RATE, mono=True)[0].astype(np.float32)
            if len(audio) < SAMPLE_RATE * 1:   # skip clips shorter than 1 sec
                continue
            audio = pad_or_crop(audio, training=False)
            sf.write(out_dir / f"normal_{saved:06d}.wav", audio, SAMPLE_RATE)
            saved += 1
        except Exception as e:
            pass  # skip corrupt files silently

    print(f"  Done. 'normal' class: {saved + len(existing)} samples total")


def run_synthesis():
    audio_dir = DATA_DIR / "audio"
    # Only synthesise multiple_voices — the other classes have real recordings
    generate_synthetic_samples("multiple_voices", audio_dir, audio_dir, target_count=150)


# ─────────────────────────────────────────────────────────────────────────────
# CELL 6: Build CSV splits
# ─────────────────────────────────────────────────────────────────────────────

def build_splits(train_ratio: float = 0.85):
    audio_dir = DATA_DIR / "audio"
    all_rows  = []
    for cls in LABELS:
        cls_dir = audio_dir / cls
        if not cls_dir.exists():
            print(f"  WARNING: missing folder {cls_dir}")
            continue
        for wav in cls_dir.glob("*.wav"):
            all_rows.append({
                "file_name": str(wav.relative_to(DATA_DIR)),
                "label": cls,
            })

    if not all_rows:
        raise RuntimeError("No audio files found! Add WAV files to data/cheating_detection/audio/<class>/")

    df = pd.DataFrame(all_rows).sample(frac=1, random_state=42)

    # Stratified split
    train_rows, val_rows = [], []
    for cls in LABELS:
        sub = df[df["label"] == cls]
        n   = int(len(sub) * train_ratio)
        train_rows.append(sub.iloc[:n])
        val_rows.append(sub.iloc[n:])

    train_df = pd.concat(train_rows).sample(frac=1, random_state=42)
    val_df   = pd.concat(val_rows).sample(frac=1, random_state=42)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    train_df.to_csv(DATA_DIR / "train.csv", index=False)
    val_df.to_csv(DATA_DIR   / "val.csv",   index=False)

    print(f"Train: {len(train_df)}  Val: {len(val_df)}")
    for cls in LABELS:
        t = len(train_df[train_df["label"] == cls])
        v = len(val_df[val_df["label"] == cls])
        print(f"  {cls}: train={t}, val={v}")

    return train_df, val_df


# ─────────────────────────────────────────────────────────────────────────────
# CELL 7: HuggingFace Dataset builder
# ─────────────────────────────────────────────────────────────────────────────

def make_hf_dataset(csv_path: Path, feature_extractor,
                    is_train: bool = False) -> Dataset:
    df       = pd.read_csv(csv_path)
    base_dir = csv_path.parent
    records  = []

    for _, row in df.iterrows():
        audio_path = base_dir / row["file_name"]
        if not audio_path.exists():
            print(f"  Missing: {audio_path}")
            continue
        try:
            audio = load_audio(str(audio_path))
            if is_train:
                audio = augment(audio)
            audio = pad_or_crop(audio, training=is_train)

            inputs = feature_extractor(
                audio,
                sampling_rate=SAMPLE_RATE,
                return_tensors="np",
                max_length=MAX_LENGTH,
                truncation=True,
                padding="max_length",
            )
            records.append({
                "input_values": inputs.input_values[0].astype(np.float32),
                "label": LABEL2ID[row["label"]],
            })
        except Exception as e:
            print(f"  Skipping {audio_path.name}: {e}")

    print(f"  Loaded {'train' if is_train else 'val'}: {len(records)} samples")
    return Dataset.from_list(records)


# ─────────────────────────────────────────────────────────────────────────────
# CELL 8: Metrics
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=1)
    acc   = (preds == labels).mean()
    return {"accuracy": float(acc)}


def print_classification_report(trainer, val_dataset):
    preds_out = trainer.predict(val_dataset)
    preds     = np.argmax(preds_out.predictions, axis=1)
    labels    = preds_out.label_ids

    print("\n" + "=" * 60)
    print("  Classification Report")
    print("=" * 60)
    print(classification_report(labels, preds, target_names=LABELS))

    cm = confusion_matrix(labels, preds)
    plt.figure(figsize=(6, 5))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues",
                xticklabels=LABELS, yticklabels=LABELS)
    plt.ylabel("True")
    plt.xlabel("Predicted")
    plt.title("Confusion Matrix")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "confusion_matrix.png", dpi=120)
    plt.show()
    print(f"Confusion matrix saved to {OUT_DIR}/confusion_matrix.png")


# ─────────────────────────────────────────────────────────────────────────────
# CELL 9: Training — Phase 1 (frozen feature extractor)
# ─────────────────────────────────────────────────────────────────────────────

def phase1_args(out_dir: Path, steps_per_epoch: int) -> TrainingArguments:
    eval_every = max(steps_per_epoch, 50)
    return TrainingArguments(
        output_dir=str(out_dir / "phase1"),
        per_device_train_batch_size=16,
        per_device_eval_batch_size=16,
        gradient_accumulation_steps=2,   # effective batch = 32
        learning_rate=1e-4,              # 1e-3 was too high → loss plateaued, now 1e-4
        num_train_epochs=10,
        warmup_ratio=0.1,
        lr_scheduler_type="cosine",
        weight_decay=0.01,
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=eval_every,
        save_strategy="steps",
        save_steps=eval_every,
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        greater_is_better=True,
        save_total_limit=2,
        fp16=torch.cuda.is_available(),
        report_to="none",
        remove_unused_columns=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CELL 10: Training — Phase 2 (full fine-tune)
# ─────────────────────────────────────────────────────────────────────────────

def phase2_args(out_dir: Path, steps_per_epoch: int) -> TrainingArguments:
    eval_every = max(steps_per_epoch, 50)
    return TrainingArguments(
        output_dir=str(out_dir / "phase2"),
        per_device_train_batch_size=8,
        per_device_eval_batch_size=16,
        gradient_accumulation_steps=4,   # effective batch = 32
        learning_rate=5e-6,              # very low LR for full fine-tune
        num_train_epochs=5,
        warmup_ratio=0.15,
        lr_scheduler_type="cosine",
        weight_decay=0.01,
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=eval_every,
        save_strategy="steps",
        save_steps=eval_every,
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        greater_is_better=True,
        save_total_limit=2,
        fp16=torch.cuda.is_available(),
        report_to="none",
        remove_unused_columns=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CELL 11: Main — put it all together
# ─────────────────────────────────────────────────────────────────────────────

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Build all class folders ──────────────────────────────────────
    print("=" * 60)
    print("Step 1/5: Setting up data...")

    print("  [normal] Sampling from Common Voice MN...")
    setup_normal_from_commonvoice(target_count=300)

    print("  [talking_to_someone] Converting your recordings...")
    setup_recorded_class(TALKING_DIR, "talking_to_someone")

    print("  [whispering] Converting your recordings...")
    setup_recorded_class(WHISPER_DIR, "whispering")

    print("  [multiple_voices] Synthesising from Common Voice...")
    run_synthesis()

    # ── Step 2: Build CSV splits ──────────────────────────────────────────────
    print("\nStep 2/5: Building train/val splits...")
    build_splits()

    # ── Step 3: Load feature extractor + model ────────────────────────────────
    print(f"\nStep 3/5: Loading {BASE_MODEL}...")
    feature_extractor = AutoFeatureExtractor.from_pretrained(BASE_MODEL)

    # AutoModelForAudioClassification uses correct CrossEntropy loss, NOT CTC.
    model = AutoModelForAudioClassification.from_pretrained(
        BASE_MODEL,
        num_labels=len(LABELS),
        label2id=LABEL2ID,
        id2label=ID2LABEL,
        ignore_mismatched_sizes=True,
    )

    total   = sum(p.numel() for p in model.parameters())
    print(f"  Total params: {total:,}")

    # ── Step 4: Prepare datasets ──────────────────────────────────────────────
    print("\nStep 4/5: Preparing HuggingFace datasets...")
    train_ds = make_hf_dataset(DATA_DIR / "train.csv", feature_extractor, is_train=True)
    val_ds   = make_hf_dataset(DATA_DIR / "val.csv",   feature_extractor, is_train=False)

    steps_per_epoch = max(1, len(train_ds) // 32)

    # ── Compute class weights to handle imbalance ─────────────────────────────
    from collections import Counter
    label_counts = Counter(train_ds["label"])
    total_samples = sum(label_counts.values())
    n_cls = len(LABELS)
    class_weights = [
        total_samples / (n_cls * max(label_counts.get(i, 1), 1))
        for i in range(n_cls)
    ]
    print(f"\nClass distribution (train): {dict(label_counts)}")
    print(f"Class weights: { {LABELS[i]: round(w, 3) for i, w in enumerate(class_weights)} }")

    # ── Step 5a: Phase 1 — freeze feature extractor ───────────────────────────
    print("\nStep 5a/5: Phase 1 — training with frozen feature extractor...")
    for param in model.wavlm.feature_extractor.parameters():
        param.requires_grad = False
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Trainable params (frozen FE): {trainable:,}")

    trainer1 = WeightedTrainer(
        model=model,
        args=phase1_args(OUT_DIR, steps_per_epoch),
        train_dataset=train_ds,
        eval_dataset=val_ds,
        compute_metrics=compute_metrics,
        class_weights=class_weights,
    )
    trainer1.train()

    # ── Step 5b: Phase 2 — unfreeze and fine-tune ─────────────────────────────
    print("\nStep 5b/5: Phase 2 — full fine-tune (unfrozen)...")
    for param in model.wavlm.feature_extractor.parameters():
        param.requires_grad = True
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Trainable params (unfrozen): {trainable:,}")

    trainer2 = WeightedTrainer(
        model=model,
        args=phase2_args(OUT_DIR, steps_per_epoch),
        train_dataset=train_ds,
        eval_dataset=val_ds,
        compute_metrics=compute_metrics,
        class_weights=class_weights,
    )
    trainer2.train()

    # ── Evaluation ────────────────────────────────────────────────────────────
    print("\nFinal evaluation...")
    print_classification_report(trainer2, val_ds)

    # ── Save final model ──────────────────────────────────────────────────────
    model.save_pretrained(OUT_DIR)
    feature_extractor.save_pretrained(OUT_DIR)
    with open(OUT_DIR / "label_mapping.json", "w") as f:
        json.dump({
            "label2id": LABEL2ID,
            "id2label": {str(k): v for k, v in ID2LABEL.items()},
        }, f, indent=2)

    print("\n" + "=" * 60)
    print(f"  Model saved to: {OUT_DIR}")
    print("=" * 60)

    # ── Colab: copy to Google Drive ───────────────────────────────────────────
    # Uncomment if you mounted Drive at /content/drive/MyDrive
    # drive_out = Path("/content/drive/MyDrive/ai_proctor/cheating_classifier_v2")
    # shutil.copytree(OUT_DIR, drive_out, dirs_exist_ok=True)
    # print(f"  Also copied to Drive: {drive_out}")


if __name__ == "__main__":
    main()
