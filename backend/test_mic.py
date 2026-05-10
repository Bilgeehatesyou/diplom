import sounddevice as sd
import soundfile as sf
import torch
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
import numpy as np

MODEL_DIR = "./models/wav2vec2-mn"

print("Loading model...")
processor = Wav2Vec2Processor.from_pretrained(MODEL_DIR)
model = Wav2Vec2ForCTC.from_pretrained(MODEL_DIR)
model.eval()
print("Model loaded. Press ENTER to start recording...")

input()
print("Recording... (press ENTER to stop)")
recording = []

def callback(indata, frames, time, status):
    recording.append(indata.copy())

with sd.InputStream(samplerate=16000, channels=1, callback=callback):
    input()

audio = np.concatenate(recording).flatten()
sf.write("testRecording.wav", audio, 16000)
print("Saved to testRecording.wav")

# Transcribe
inputs = processor(audio, sampling_rate=16000, return_tensors="pt", padding=True)
with torch.no_grad():
    logits = model(inputs.input_values).logits
predicted_ids = torch.argmax(logits, dim=-1)
transcription = processor.batch_decode(predicted_ids)[0]

print(f"\nTranscription: {transcription}")