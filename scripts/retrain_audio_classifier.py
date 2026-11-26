"""
Browser-recorded audio sample-аас WavLM classifier-ийг fine-tune хийнэ.

Хэрэглэх:
    python scripts/retrain_audio_classifier.py

Бэлдэх:
    1. scripts/record_audio_samples.html-г Chrome дээр нээж дээж бичих
    2. Татагдсан .webm файлуудыг ангилж байршуулах:
         models/training_data/normal/*.webm
         models/training_data/talking/*.webm
         models/training_data/whispering/*.webm
         models/training_data/multiple/*.webm
    3. Class бүрд хамгийн багадаа 15-20 дээж (тус бүр 5 секунд)
    4. Энэ script-ийг ажиллуулах

Үр дүн:
    models/cheating_classifier_v3/ - шинэ fine-tuned model
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset
from transformers import (
    AutoFeatureExtractor,
    AutoModelForAudioClassification,
    Trainer,
    TrainingArguments,
)

ROOT          = Path(__file__).resolve().parent.parent
SOURCE_MODEL  = ROOT / "models" / "cheating_classifier_v2"
TARGET_MODEL  = ROOT / "models" / "cheating_classifier_v3"
TRAIN_DIR     = ROOT / "models" / "training_data"
LABELS        = ["normal", "talking", "whispering", "multiple"]
LABEL_TO_ID   = {l: i for i, l in enumerate(LABELS)}
TARGET_SR     = 16000
TARGET_LEN_S  = 5  # секунд

PRODUCTION_LABELS = ["normal", "talking_to_someone", "multiple_voices", "whispering"]
PRODUCTION_MAP    = {
    "normal":     "normal",
    "talking":    "talking_to_someone",
    "multiple":   "multiple_voices",
    "whispering": "whispering",
}


def find_ffmpeg() -> str:
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
                for root, _, files in os.walk(os.path.join(winget, pkg)):
                    for fn in files:
                        if fn in ("ffmpeg.exe", "ffmpeg"):
                            candidates.append(os.path.join(root, fn))
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise RuntimeError("ffmpeg олдсонгүй — суулгаарай")


_FFMPEG = find_ffmpeg()


def webm_to_pcm(webm_path: Path) -> np.ndarray:
    """WebM/Opus → 16kHz mono float32 PCM."""
    from pydub import AudioSegment
    audio = AudioSegment.from_file(str(webm_path), format="webm")
    audio = audio.set_frame_rate(TARGET_SR).set_channels(1).set_sample_width(2)
    pcm = np.frombuffer(audio.raw_data, np.int16).astype(np.float32) / 32768.0
    target = TARGET_SR * TARGET_LEN_S
    if len(pcm) >= target:
        return pcm[:target]
    return np.pad(pcm, (0, target - len(pcm)))


class WebMDataset(Dataset):
    def __init__(self, files: list, labels: list, extractor):
        self.files     = files
        self.labels    = labels
        self.extractor = extractor

    def __len__(self):
        return len(self.files)

    def __getitem__(self, idx):
        pcm = webm_to_pcm(self.files[idx])
        feat = self.extractor(
            pcm, sampling_rate=TARGET_SR, return_tensors="pt",
            max_length=TARGET_SR * TARGET_LEN_S, truncation=True, padding="max_length",
        )
        item = {k: v.squeeze(0) for k, v in feat.items()}
        item["labels"] = torch.tensor(self.labels[idx], dtype=torch.long)
        return item


class WeightedTrainer(Trainer):
    """Class imbalance тэнцвэржүүлсэн loss."""
    def __init__(self, class_weights, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels  = inputs.pop("labels")
        outputs = model(**inputs)
        logits  = outputs.logits
        loss_fct = torch.nn.CrossEntropyLoss(weight=self.class_weights.to(logits.device))
        loss = loss_fct(logits, labels)
        return (loss, outputs) if return_outputs else loss


def main():
    if not SOURCE_MODEL.exists():
        print(f"❌ Source model олдсонгүй: {SOURCE_MODEL}")
        print("   models/cheating_classifier_v2/ folder байх ёстой")
        sys.exit(1)

    if not TRAIN_DIR.exists():
        print(f"❌ Training data folder олдсонгүй: {TRAIN_DIR}")
        print("   Дараах folder-уудыг үүсгэж .webm файл бэлдэх:")
        for lbl in LABELS:
            print(f"     {TRAIN_DIR / lbl}/")
        sys.exit(1)

    # 1. Файл цуглуулах
    print(f"📂 Training data {TRAIN_DIR}-ээс цуглуулж байна...")
    files, labels = [], []
    counts = {l: 0 for l in LABELS}
    for lbl in LABELS:
        cls_dir = TRAIN_DIR / lbl
        if not cls_dir.exists():
            print(f"   ⚠ {cls_dir} олдсонгүй (skip)")
            continue
        webms = sorted(cls_dir.glob("*.webm"))
        for f in webms:
            files.append(f)
            labels.append(LABEL_TO_ID[lbl])
            counts[lbl] += 1

    print(f"\n📊 Дээжний тоо:")
    for lbl, c in counts.items():
        flag = "✓" if c >= 15 else "⚠"
        print(f"   {flag} {lbl:12} {c}")

    if sum(counts.values()) < 30:
        print(f"\n❌ Хэт цөөн дээж ({sum(counts.values())}). Class бүрд 15+ хэрэгтэй.")
        sys.exit(1)

    # 2. Model + extractor ачаалах
    print(f"\n🧠 Source model ачаалж байна: {SOURCE_MODEL}")
    extractor = AutoFeatureExtractor.from_pretrained(str(SOURCE_MODEL))
    model     = AutoModelForAudioClassification.from_pretrained(
        str(SOURCE_MODEL), num_labels=len(LABELS), ignore_mismatched_sizes=True,
    )

    # 3. Class weights (imbalance-г засах)
    total   = sum(counts.values())
    weights = torch.tensor(
        [total / (len(LABELS) * counts[l]) if counts[l] > 0 else 0.0 for l in LABELS],
        dtype=torch.float32,
    )
    print(f"\n⚖ Class weights: {dict(zip(LABELS, weights.tolist()))}")

    # 4. Train/val split (80/20 stratified)
    print(f"\n🔀 Train/val split...")
    by_class = {l: [] for l in range(len(LABELS))}
    for i, lbl_id in enumerate(labels):
        by_class[lbl_id].append(i)
    train_idx, val_idx = [], []
    rng = np.random.default_rng(42)
    for cls_id, idxs in by_class.items():
        if not idxs:
            continue
        rng.shuffle(idxs)
        n_val = max(1, len(idxs) // 5)
        val_idx.extend(idxs[:n_val])
        train_idx.extend(idxs[n_val:])

    train_files  = [files[i]  for i in train_idx]
    train_labels = [labels[i] for i in train_idx]
    val_files    = [files[i]  for i in val_idx]
    val_labels   = [labels[i] for i in val_idx]
    print(f"   train: {len(train_files)},  val: {len(val_files)}")

    train_ds = WebMDataset(train_files, train_labels, extractor)
    val_ds   = WebMDataset(val_files,   val_labels,   extractor)

    # 5. Training args
    args = TrainingArguments(
        output_dir=str(TARGET_MODEL),
        per_device_train_batch_size=4,
        per_device_eval_batch_size=4,
        num_train_epochs=8,
        learning_rate=2e-5,
        warmup_ratio=0.1,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        logging_steps=5,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        remove_unused_columns=False,
        report_to=[],
        fp16=torch.cuda.is_available(),
    )

    trainer = WeightedTrainer(
        class_weights=weights,
        model=model,
        args=args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
    )

    print(f"\n🚀 Training эхэллээ... (epochs={args.num_train_epochs})")
    trainer.train()

    # 6. Validation
    print(f"\n✅ Validation үр дүн:")
    metrics = trainer.evaluate()
    for k, v in metrics.items():
        print(f"   {k:20} {v:.4f}")

    # 7. Save (label mapping-ийг production-той ижил болгох)
    print(f"\n💾 Хадгалж байна: {TARGET_MODEL}")
    model.config.id2label = {i: PRODUCTION_MAP[l] for i, l in enumerate(LABELS)}
    model.config.label2id = {v: k for k, v in model.config.id2label.items()}
    trainer.save_model(str(TARGET_MODEL))
    extractor.save_pretrained(str(TARGET_MODEL))

    print(f"\n🎉 Бэлэн! Production-д ашиглах:")
    print(f"   1. backend/ai/analyzer.py-н _CLF_MODEL_DIR-ийг 'cheating_classifier_v3' болгох")
    print(f"   2. Backend restart хийх")


if __name__ == "__main__":
    main()
