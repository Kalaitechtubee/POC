#!/usr/bin/env python3
print("[DEBUG] Script started", flush=True)
import queue
import sounddevice as sd
from vosk import Model, KaldiRecognizer
import json
import socketio
import threading
import numpy as np
from faster_whisper import WhisperModel
import time
import sys
import argparse
from pathlib import Path

# --- Fix Windows stdout encoding (cp1252 -> utf-8) ---
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        # Fallback for older python versions if needed
        pass

# --- Configuration ---
parser = argparse.ArgumentParser(description='Dual-Mode Live Subtitle (Vosk + Faster-Whisper)')
parser.add_argument('--server',     default='http://localhost:3000', help='Server URL')
parser.add_argument('--model',      default='base',                 help='Faster-Whisper model size')
parser.add_argument('--vosk-model', default='vosk-model-small-en-us-0.15', help='Vosk model directory')
parser.add_argument('--device',     type=int, default=None,         help='Mic device index')
parser.add_argument('--chunk',      type=int, default=4,            help='Whisper chunk size in seconds')
args = parser.parse_args()

# --- Socket.io Setup ---
sio = socketio.Client()

@sio.event
def connect():
    print("[WS]  Connected to server")

@sio.event
def disconnect():
    print("[WS]  Disconnected")

def connect_to_server():
    try:
        url = f"{args.server}?type=python"
        sio.connect(url)
        return True
    except Exception as e:
        print(f"[WS]  Connection failed: {e}")
        return False

# --- Model Loading ---
print(f"[VOSK]  Loading model from {args.vosk_model}...")
if not Path(args.vosk_model).exists():
    print(f"[ERROR] Vosk model directory not found: {args.vosk_model}")
    sys.exit(1)
vosk_model = Model(args.vosk_model)
rec = KaldiRecognizer(vosk_model, 16000)

print(f"[WHISPER] Loading Faster-Whisper model '{args.model}'...")
whisper_model = WhisperModel(args.model, device="cpu", compute_type="int8") # Use "cuda" if available
print("[SYSTEM]  Models ready")

# --- Audio Handling ---
audio_q = queue.Queue()
whisper_q = queue.Queue()

def audio_callback(indata, frames, time, status):
    if status:
        print(f"[AUDIO] {status}", file=sys.stderr)
    # Vosk expects 16-bit PCM bytes
    audio_q.put(bytes(indata))

def whisper_processor():
    """Background thread to process chunks with Whisper for high accuracy."""
    while True:
        audio_chunk = whisper_q.get()
        if audio_chunk is None: break
        
        # Convert to float32 for Whisper
        audio_np = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        
        t0 = time.time()
        # Tip: For Tamil/Mix, you can add language="ta" to transcribe()
        segments, info = whisper_model.transcribe(audio_np, beam_size=5)
        
        full_text = ""
        for segment in segments:
            full_text += segment.text
        
        full_text = full_text.strip()
        if full_text:
            dt = time.time() - t0
            print(f"[WHISPER] Final: \"{full_text}\" ({dt:.2f}s)")
            sio.emit("final_subtitle", full_text)
        
        whisper_q.task_done()

def run_dual_mode():
    SAMPLE_RATE = 16000
    CHUNK_SIZE  = int(SAMPLE_RATE * args.chunk) # samples per whisper chunk
    
    # Start Whisper worker thread
    threading.Thread(target=whisper_processor, daemon=True).start()
    
    print(f"\n[MIC]  Starting capture (Device: {args.device if args.device is not None else 'Default'})")
    print("[MIC]  Speak now! Vosk handles live typing, Whisper handles corrections.\n")

    current_chunk_buffer = bytearray()
    
    try:
        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=4000, device=args.device,
                               dtype='int16', channels=1, callback=audio_callback):
            while True:
                data = audio_q.get()
                current_chunk_buffer.extend(data)
                
                # 1. Vosk Live Processing
                if rec.AcceptWaveform(data):
                    res = json.loads(rec.Result())
                    text = res.get("text", "")
                    if text:
                        print(f"Vosk (Final Segment): {text}")
                        sio.emit("live_subtitle", text)
                else:
                    res = json.loads(rec.PartialResult())
                    partial = res.get("partial", "")
                    if partial:
                        # Only emit if partial has changed or significant
                        sio.emit("live_subtitle", partial)

                # 2. Whisper Chunking
                # If we have enough data for a Whisper chunk, send it to the worker
                if len(current_chunk_buffer) >= (CHUNK_SIZE * 2): # *2 because int16 is 2 bytes
                    whisper_q.put(bytes(current_chunk_buffer))
                    current_chunk_buffer = bytearray()

    except KeyboardInterrupt:
        print("\n[SYSTEM] Stopping...")
    except Exception as e:
        print(f"[ERROR] {e}")

if __name__ == '__main__':
    if connect_to_server():
        run_dual_mode()
    else:
        print("[ERROR] Could not connect to server. Is it running?")
