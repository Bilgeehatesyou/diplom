import os
import torch
import soundfile as sf
import pandas as pd
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

# Point to the root models folder (parent of backend)
MODEL_DIR = os.path.abspath("../models/wav2vec2-mn")
DATA_DIR = os.path.abspath("../data/wav2vec_commonvoice")

print(f"Loading model from: {MODEL_DIR}")
processor = Wav2Vec2Processor.from_pretrained(MODEL_DIR, local_files_only=True)
model = Wav2Vec2ForCTC.from_pretrained(MODEL_DIR, local_files_only=True)
model.eval()
print("Model loaded ✓")

# Load validation data
val_df = pd.read_csv(f"{DATA_DIR}/val.tsv", sep="\t")
val_df = val_df.dropna(subset=["text"])
print(f"Validation samples: {len(val_df)}")

def transcribe(audio_path):
    speech, sr = sf.read(audio_path)
    if sr != 16000:
        import librosa
        speech = librosa.resample(speech, orig_sr=sr, target_sr=16000)
    if len(speech.shape) > 1:
        speech = speech.mean(axis=1)

    inputs = processor(speech, sampling_rate=16000, return_tensors="pt", padding=True)
    with torch.no_grad():
        logits = model(inputs.input_values).logits
    predicted_ids = torch.argmax(logits, dim=-1)
    return processor.batch_decode(predicted_ids)[0]

def wer(ref, hyp):
    ref_words = ref.split()
    hyp_words = hyp.split()
    d = [[0] * (len(hyp_words) + 1) for _ in range(len(ref_words) + 1)]
    for i in range(len(ref_words) + 1):
        d[i][0] = i
    for j in range(len(hyp_words) + 1):
        d[0][j] = j
    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            cost = 0 if ref_words[i-1] == hyp_words[j-1] else 1
            d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + cost)
    return d[len(ref_words)][len(hyp_words)] / len(ref_words)

# Test on first 10 samples
print("\n--- Testing on 10 samples ---\n")
total_wer = 0
results = []

for i, row in val_df.head(10).iterrows():
    audio_path = f"{DATA_DIR}/{row['file_name']}"
    ground_truth = row['text']
    prediction = transcribe(audio_path)

    w = wer(ground_truth, prediction)
    total_wer += w

    results.append({
        "id": i,
        "ground_truth": ground_truth,
        "prediction": prediction,
        "wer": round(w * 100, 1)
    })

    print(f"[{i}] WER: {w*100:.1f}%")
    print(f"    GT: {ground_truth[:80]}...")
    print(f"    PD: {prediction[:80]}...")
    print()

avg_wer = total_wer / 10
accuracy = (1 - avg_wer) * 100
print(f"\n=== Average WER: {avg_wer*100:.1f}% ===")
print(f"=== Accuracy: {accuracy:.1f}% ===")