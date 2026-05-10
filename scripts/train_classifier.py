#!/usr/bin/env python3
"""
Cheating Detection - Audio Classification with Wav2Vec2
Uses Wav2Vec2 as feature extractor + classification head
Includes data augmentation for better performance with small datasets
"""
import os
import sys
import argparse
from pathlib import Path
import numpy as np
import torch
import soundfile as sf
import pandas as pd
from datasets import Dataset, DatasetDict
from transformers import (
    Wav2Vec2ForCTC,
    Wav2Vec2CTCTokenizer,
    Wav2Vec2FeatureExtractor,
    Wav2Vec2Processor,
    Trainer,
    TrainingArguments,
)
from dataclasses import dataclass
from typing import Dict, List, Union, Optional
import json
import random


# Data augmentation functions
def add_noise(audio: np.ndarray, noise_level: float = 0.005) -> np.ndarray:
    """Add random background noise."""
    noise = np.random.normal(0, noise_level, audio.shape)
    return audio + noise


def change_pitch(audio: np.ndarray, sample_rate: int = 16000, n_steps: int = 2) -> np.ndarray:
    """Change pitch of audio."""
    try:
        import librosa
        audio_pitch = librosa.effects.pitch_shift(audio, sr=sample_rate, n_steps=n_steps)
        return audio_pitch
    except Exception:
        return audio


def change_speed(audio: np.ndarray, speed_factor: float = 1.1) -> np.ndarray:
    """Change speed of audio."""
    try:
        import librosa
        audio_speed = librosa.effects.time_stretch(audio, rate=speed_factor)
        return audio_speed
    except Exception:
        return audio


def add_reverb(audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """Add reverb effect."""
    try:
        import librosa
        # Simple reverb using delay
        delay_samples = int(0.05 * sample_rate)  # 50ms delay
        reverb = np.zeros_like(audio)
        reverb[delay_samples:] = audio[:-delay_samples] * 0.3
        return audio + reverb
    except Exception:
        return audio


def augment_audio(audio: np.ndarray, sample_rate: int = 16000) -> List[np.ndarray]:
    """Apply multiple augmentation strategies."""
    augmented = [audio]  # Original

    # Add noise
    augmented.append(add_noise(audio, noise_level=0.01))

    # Speed variations
    try:
        augmented.append(change_speed(audio, 0.9))
        augmented.append(change_speed(audio, 1.1))
    except Exception:
        pass

    # Pitch variations
    try:
        augmented.append(change_pitch(audio, sample_rate, -2))
        augmented.append(change_pitch(audio, sample_rate, 2))
    except Exception:
        pass

    return augmented


@dataclass
class DataCollatorForClassification:
    processor: Wav2Vec2Processor
    padding: bool = True
    max_length: int = 32000  # ~2 seconds at 16kHz

    def __call__(self, features: List[Dict]) -> Dict[str, torch.Tensor]:
        input_features = [{"input_values": f["input_values"]} for f in features]
        labels = torch.tensor([f["labels"] for f in features])

        batch = self.processor.pad(
            input_features,
            padding=self.padding,
            return_tensors="pt",
            max_length=self.max_length,
            truncation=True,
        )

        batch["labels"] = labels
        return batch


def build_processor():
    """Build processor for Wav2Vec2."""
    # Simple vocab for classification (just need tokenizer)
    vocab = {"<pad>": 0, "<unk>": 1, "a": 2, "b": 3, "c": 4}

    tmp_vocab_path = "/tmp/vocab_class.json"
    with open(tmp_vocab_path, "w", encoding="utf-8") as f:
        json.dump(vocab, f)

    tokenizer = Wav2Vec2CTCTokenizer(
        tmp_vocab_path,
        unk_token="<unk>",
        pad_token="<pad>",
    )

    feature_extractor = Wav2Vec2FeatureExtractor(
        feature_size=1,
        sampling_rate=16000,
        padding_value=0.0,
        do_normalize=True,
        return_attention_mask=True,
    )

    processor = Wav2Vec2Processor(
        feature_extractor=feature_extractor,
        tokenizer=tokenizer,
    )
    return processor


def load_audio(audio_path: str, sample_rate: int = 16000) -> np.ndarray:
    """Load audio file."""
    speech, sr = sf.read(audio_path)
    if sr != sample_rate:
        import librosa
        speech = librosa.resample(speech, orig_sr=sr, target_sr=sample_rate)
    if len(speech.shape) > 1:
        speech = speech.mean(axis=1)
    return speech


def prepare_dataset(csv_path: Path, processor, augment: bool = False):
    """Load and preprocess dataset."""
    df = pd.read_csv(csv_path)

    # Label mapping
    label2id = {
        "normal": 0,
        "talking_to_someone": 1,
        "multiple_voices": 2,
        "whispering": 3,
    }
    id2label = {v: k for k, v in label2id.items()}

    def process_example(example):
        audio_path = str(csv_path.parent / example["file_name"])
        audio = load_audio(audio_path)

        # Apply augmentation if enabled (only during training)
        if augment and random.random() > 0.5:
            aug_audio = random.choice([
                add_noise(audio, noise_level=0.01),
                change_speed(audio, random.choice([0.9, 1.1])),
                add_noise(audio, noise_level=0.005),
            ])
            audio = aug_audio

        input_values = processor(
            audio, sampling_rate=16000
        ).input_values[0]

        return {
            "input_values": input_values,
            "labels": label2id[example["label"]],
        }

    dataset = Dataset.from_pandas(df)
    dataset = dataset.map(
        process_example,
        remove_columns=dataset.column_names,
        desc="Processing audio"
    )

    return dataset, label2id, id2label


def compute_metrics(eval_pred):
    """Compute accuracy metric."""
    predictions, labels = eval_pred
    predictions = np.argmax(predictions, axis=1)
    accuracy = np.mean(predictions == labels)
    return {"accuracy": accuracy}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", type=str, default="./data/cheating_detection")
    parser.add_argument("--model_name", type=str, default="facebook/wav2vec2-base")
    parser.add_argument("--output_dir", type=str, default="./models/cheating_classifier")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--augment", action="store_true", default=True, help="Enable data augmentation")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Load processor
    processor = build_processor()
    print("✅ Processor built")

    # Load datasets
    data_dir = Path(args.data_dir)
    print("\nLoading datasets...")

    train_csv = data_dir / "train.csv"
    val_csv = data_dir / "val.csv"

    if not train_csv.exists() or not val_csv.exists():
        print("❌ Train/Val CSV not found!")
        print("   Run: python scripts/prepare_classification.py")
        sys.exit(1)

    train_dataset, label2id, id2label = prepare_dataset(train_csv, processor, augment=args.augment)
    val_dataset, _, _ = prepare_dataset(val_csv, processor, augment=False)

    print(f"   Train: {len(train_dataset)} samples")
    print(f"   Val: {len(val_dataset)} samples")
    print(f"   Labels: {label2id}")

    # Load model - use Wav2Vec2ForCTC but modify for classification
    model = Wav2Vec2ForCTC.from_pretrained(
        args.model_name,
        ctc_loss_reduction="mean",
        pad_token_id=processor.tokenizer.pad_token_id,
        vocab_size=len(processor.tokenizer),
        ignore_mismatched_sizes=True,
    )

    # Replace CTC head with classification head
    model.lm_head = torch.nn.Linear(
        model.config.hidden_size,
        len(label2id)
    )
    model.config.num_labels = len(label2id)
    model.config.id2label = id2label
    model.config.label2id = label2id
    model = model.to(device)

    print("✅ Model loaded with classification head")

    # Data collator
    data_collator = DataCollatorForClassification(processor=processor)

    # Training arguments
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        warmup_steps=500,
        logging_steps=100,
        save_steps=500,
        eval_steps=500,
        save_total_limit=2,
        fp16=torch.cuda.is_available(),
        dataloader_num_workers=2,
        evaluation_strategy="steps",
        save_strategy="steps",
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        greater_is_better=True,
    )

    # Trainer
    trainer = Trainer(
        model=model,
        data_collator=data_collator,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
    )

    print("\n🚀 Starting training...")
    trainer.train()

    # Save model
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output_dir)
    processor.save_pretrained(args.output_dir)

    # Save label mapping
    with open(Path(args.output_dir) / "label_mapping.json", "w") as f:
        json.dump({"label2id": label2id, "id2label": id2label}, f)

    print("\n✅ Training complete!")
    print(f"   Model saved to: {args.output_dir}")


if __name__ == "__main__":
    sys.argv = [
        "train",
        "--data_dir", "./data/cheating_detection",
        "--output_dir", "./models/cheating_classifier",
        "--epochs", "10",
        "--batch_size", "8",
        "--lr", "1e-4",
    ]
    main()