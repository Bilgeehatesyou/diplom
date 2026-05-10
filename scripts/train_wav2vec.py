#!/usr/bin/env python3
"""
Wav2Vec2 Mongolian — Common Voice 16.0 дээр fine-tune хийх
Ажиллуулах: python scripts/train_wav2vec.py --data_dir ./data/wav2vec_commonvoice
"""
import os
import sys
import argparse
from pathlib import Path
import torch
from transformers import (
    Wav2Vec2ForCTC,
    Wav2Vec2Processor,
    Wav2Vec2Config,
    Trainer,
    TrainingArguments,
    DataCollatorCTCWithPadding,
)
from datasets import load_dataset, Audio, DatasetDict


def load_mn_data(data_dir: str, sample_rate: int = 16000):
    """Common Voice Mongolian дата ачаалж буцаана."""
    data_path = Path(data_dir)

    def prepare(batch):
        speech = batch["audio"]["array"]
        batch["input_values"] = processor(
            speech, sampling_rate=sample_rate
        ).input_values[0]
        with processor.as_target_processor():
            batch["labels"] = processor(batch["text"]).input_ids
        return batch

    # Dataset ачаалach
    train_files = str(data_path / "train.tsv")
    val_files = str(data_path / "val.tsv")

    if not Path(train_files).exists():
        raise FileNotFoundError(f"Train TSV олдсонгүй: {train_files}")

    ds = load_dataset(
        "csv",
        data_files={
            "train": train_files,
            "validation": val_files if Path(val_files).exists() else train_files,
        },
        delimiter="\t",
        cache_dir=str(data_path / ".cache"),
    )

    # Audio уншихийн тулд audio column нэмэх
    ds = ds.cast_column(
        "audio",
        Audio(sampling_rate=sample_rate, mono=True)
    )

    # Боловсруулах
    ds = ds.map(
        prepare,
        remove_columns=ds.column_names["train"],
        num_proc=4,
    )

    return ds


def main():
    parser = argparse.ArgumentParser(description="Wav2Vec2 Mongolian fine-tune")
    parser.add_argument(
        "--data_dir",
        type=str,
        default="./data/wav2vec_commonvoice",
        help="Бэлтгэсэн Common Voice дата байрлаж байгаа folder"
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default="facebook/wav2vec2-xls-r-300m",
        help="Pre-trained wav2vec2 загвар (default: facebook/wav2vec2-xls-r-300m)"
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="./models/wav2vec2-mn",
        help="Fine-tune хийсэн загварыг хадгалах folder"
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=5,
        help="Epoch тоо"
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=8,
        help="Batch size"
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=1e-4,
        help="Learning rate"
    )
    parser.add_argument(
        "--warmup_steps",
        type=int,
        default=500,
        help="Warmup steps"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Wav2Vec2 Mongolian — Fine-tune")
    print("=" * 60)
    print(f"   📁 Дата: {args.data_dir}")
    print(f"   🏗️  База загвар: {args.model_name}")
    print(f"   📦 Output: {args.output_dir}")
    print()

    # Device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"   🖥️  Device: {device}")
    print()

    # processor & model
    print("[1/4] Processor ачаалж байна...")
    processor = Wav2Vec2Processor.from_pretrained(args.model_name)
    print("   ✅ OK")

    print("[2/4] Загвар ачаалж байна...")
    model = Wav2Vec2ForCTC.from_pretrained(
        args.model_name,
        ctc_loss_reduction="mean",
        pad_token_id=processor.tokenizer.pad_token_id,
        vocab_size=len(processor.tokenizer),
    )
    model.to(device)
    print("   ✅ OK")

    # Data
    print("[3/4] Дата ачаалж байна...")
    datasets = load_mn_data(args.data_dir)
    print(f"   📊 Train: {len(datasets['train'])}")
    print(f"   📊 Val: {len(datasets['validation'])}")

    # Data collator
    data_collator = DataCollatorCTCWithPadding(
        processor=processor,
        padding=True,
        max_length=160000,  # 10 sec audio at 16kHz
    )

    # Training arguments
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        group_by_length=True,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        warmup_steps=args.warmup_steps,
        logging_steps=100,
        save_steps=500,
        eval_steps=500,
        save_total_limit=2,
        fp16=torch.cuda.is_available(),
        dataloader_num_workers=2,
        remove_unused_columns=False,
        label_names=["labels"],
    )

    # Trainer
    print("[4/4] Fine-tune эхэллээ...")
    trainer = Trainer(
        model=model,
        data_collator=data_collator,
        args=training_args,
        train_dataset=datasets["train"],
        eval_dataset=datasets["validation"],
        tokenizer=processor.feature_extractor,
    )

    trainer.train()

    # Save
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_path)
    processor.save_pretrained(output_path)
    print()
    print("=" * 60)
    print(f"  ✅ Загвар хадгалгдлаа: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
