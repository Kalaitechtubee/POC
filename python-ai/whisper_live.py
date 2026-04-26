#!/usr/bin/env python3
"""
Live Auto Subtitle System — Python Whisper AI Layer
====================================================
Captures live microphone audio in chunks, transcribes with OpenAI Whisper,
optionally matches against a known script using sentence-transformers,
then emits the subtitle over WebSocket to the Node.js server.

Usage:
    python whisper_live.py                     # Basic mode
    python whisper_live.py --model small       # Better accuracy
    python whisper_live.py --script script.txt # Enable script matching
    python whisper_live.py --chunk 3           # 3-second chunks (faster)
    python whisper_live.py --test              # Send test subtitles (no mic needed)
"""

import argparse
import tempfile
import time
import os
import sys
import threading
from pathlib import Path

# ── Fix Windows stdout encoding (cp1252 → utf-8) ──────────
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ── Dependency check helper ───────────────────────────────
def check_import(name, install_hint):
    try:
        return __import__(name)
    except ImportError:
        print(f"[ERROR] Missing package: {name}")
        print(f"        Install with:  {install_hint}")
        sys.exit(1)

# ── Parse args first (so --test works without sounddevice) ─
parser = argparse.ArgumentParser(description='Live Auto Subtitle — Python Whisper')
parser.add_argument('--server',    default='http://localhost:3000', help='Node.js server URL')
parser.add_argument('--model',     default='base', choices=['tiny','base','small','medium','large'], help='Whisper model size')
parser.add_argument('--chunk',     type=int,   default=5,     help='Audio chunk duration in seconds')
parser.add_argument('--script',    default=None,              help='Path to script .txt file for matching')
parser.add_argument('--test',      action='store_true',       help='Test mode: send hardcoded subtitles, no mic')
parser.add_argument('--lang',      default=None,              help='Force language (e.g. en, ta, hi)')
parser.add_argument('--device',    type=int,   default=None,  help='Mic device index (use --listdev to see options)')
parser.add_argument('--listdev',   action='store_true',       help='List all audio input devices and exit')
parser.add_argument('--threshold', type=float, default=0.005, help='Silence threshold RMS (default 0.005)')
args = parser.parse_args()

# ── List devices and exit if requested ───────────────────
if args.listdev:
    import sounddevice as sd
    devices = sd.query_devices()
    print("\nAvailable audio INPUT devices:")
    print("-" * 50)
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            marker = " <-- DEFAULT" if i == sd.default.device[0] else ""
            print(f"  [{i}] {d['name']}{marker}")
    print("-" * 50)
    print("\nUse:  py -3 whisper_live.py --device <index>")
    sys.exit(0)

# ── Core imports ──────────────────────────────────────────
import socketio
import numpy as np

sio = socketio.Client()

# ── Socket.io events ─────────────────────────────────────
@sio.event
def connect():
    print("[WS]  ✅ Connected to Node.js server")

@sio.event
def disconnect():
    print("[WS]  ❌ Disconnected from server")

@sio.event
def server_stats(data):
    connected = data.get('connected', {})
    print(f"[STATS] Python:{connected.get('python',0)}  Flutter:{connected.get('flutter',0)}  Web:{connected.get('web',0)}  Total sent:{data.get('total_sent',0)}")

# ── Connect to server ─────────────────────────────────────
def connect_to_server():
    retries = 0
    while retries < 10:
        try:
            # Pass type=python in query string so server.js can identify us
            url = f"{args.server}?type=python"
            print(f"[WS]  Connecting to {url} ...", flush=True)
            sio.connect(url)
            return True
        except Exception as e:
            retries += 1
            print(f"[WS]  Connection failed (attempt {retries}/10): {e}", flush=True)
            time.sleep(3)
    print("[WS]  Could not connect. Is the Node.js server running?", flush=True)
    return False

# ── Script Matching (optional) ────────────────────────────
script_lines     = []
script_embeddings = None
matcher          = None

def load_script(script_path: str):
    global script_lines, script_embeddings, matcher
    if not script_path or not Path(script_path).exists():
        print(f"[SCRIPT]  File not found: {script_path}")
        return

    try:
        from sentence_transformers import SentenceTransformer, util as st_util
        global st_util
    except ImportError:
        print("[SCRIPT]  sentence-transformers not installed. Script matching disabled.")
        print("          Install: pip install sentence-transformers")
        return

    with open(script_path, encoding='utf-8') as f:
        script_lines = [l.strip() for l in f if l.strip()]

    print(f"[SCRIPT]  Loading ML model (all-MiniLM-L6-v2)...")
    matcher = SentenceTransformer('all-MiniLM-L6-v2')
    script_embeddings = matcher.encode(script_lines, show_progress_bar=False)
    print(f"[SCRIPT]  ✅ {len(script_lines)} script lines loaded and embedded")

    sio.emit('script_loaded', {'line_count': len(script_lines)})

def match_script(whisper_text: str) -> tuple[str, float]:
    """Returns (best_matching_line, confidence_score) or original text."""
    if not script_lines or matcher is None:
        return whisper_text, 1.0

    from sentence_transformers import util as st_util
    emb_input  = matcher.encode(whisper_text)
    scores     = st_util.cos_sim(emb_input, script_embeddings)[0]
    best_idx   = int(scores.argmax())
    confidence = float(scores[best_idx])

    if confidence > 0.5:   # threshold: only use match if similar enough
        return script_lines[best_idx], confidence
    return whisper_text, confidence

# ── Whisper transcription ─────────────────────────────────
def load_whisper():
    try:
        import whisper
        print(f"[WHISPER]  Loading model '{args.model}' (first run downloads it)...")
        model = whisper.load_model(args.model)
        print(f"[WHISPER]  ✅ Model '{args.model}' ready")
        return model
    except ImportError:
        print("[ERROR]  openai-whisper not installed. Run:  pip install openai-whisper")
        sys.exit(1)

def transcribe(model, audio_array: np.ndarray, sample_rate: int) -> str:
    """
    Advanced transcription using Whisper's low-level API.
    Bypasses ffmpeg entirely by working directly with Mel Spectrograms.
    """
    import whisper
    import torch

    try:
        # 1. Prepare audio (ensure float32 and correct length)
        # Whisper expects 16k samples. We pad/trim to 30s as per model requirements.
        audio = whisper.pad_or_trim(audio_array.astype(np.float32))

        # 2. Convert to Log-Mel Spectrogram
        # This part is pure math/tensor work, no ffmpeg involved!
        mel = whisper.log_mel_spectrogram(audio).to(model.device)
        
        # Select FP32 if on CPU to avoid warnings
        if model.device.type == 'cpu':
            mel = mel.float()

        # 3. Decode
        options = whisper.DecodingOptions(
            fp16=(model.device.type != 'cpu'),
            language=args.lang if args.lang else None
        )
        result = whisper.decode(model, mel, options)
        
        return result.text.strip()

    except Exception as e:
        print(f"\n[ERROR] Transcription failed: {e}")
        if "[WinError 2]" in str(e):
            print("        Tip: This error usually means ffmpeg is missing.")
            print("        I tried to bypass it, but your Whisper version might still require it.")
        return ""

# ── Send subtitle ─────────────────────────────────────────
def send_subtitle(text: str, source: str = 'whisper', confidence: float = None):
    if not text:
        return
    payload = {'text': text, 'source': source, 'confidence': confidence}
    sio.emit('subtitle', payload)
    print(f"[SENT]  [{source}]  {text}")

# ── Test mode (no mic) ────────────────────────────────────
TEST_SUBTITLES = [
    "Hello everyone, welcome to the show.",
    "Please take your seats.",
    "The performance will begin shortly.",
    "Thank you for joining us tonight.",
    "We hope you enjoy the performance.",
    "Our first act will now begin.",
    "Please silence your mobile phones.",
    "Photography is not permitted during the show.",
    "Thank you for your cooperation.",
    "Enjoy the show!",
]

def run_test_mode():
    print("[TEST]  Running in test mode — no microphone required")
    print("[TEST]  Sending hardcoded subtitles every 3 seconds...")
    for i, line in enumerate(TEST_SUBTITLES):
        time.sleep(3)
        send_subtitle(line, source='test', confidence=1.0)
    print("[TEST]  All test subtitles sent. Loop restarting...")
    run_test_mode()   # loop

# ── Live mic capture ──────────────────────────────────────
def run_live_mode():
    try:
        import sounddevice as sd
    except ImportError:
        print("[ERROR]  sounddevice not installed. Run:  pip install sounddevice scipy")
        sys.exit(1)

    model = load_whisper()

    SAMPLE_RATE = 16000
    CHUNK_SEC   = args.chunk
    THRESHOLD   = args.threshold
    DEVICE      = args.device

    # Show which device is active
    devices = sd.query_devices()
    if DEVICE is not None:
        dev_name = devices[DEVICE]['name']
    else:
        default_idx = sd.default.device[0]
        dev_name = devices[default_idx]['name'] if default_idx >= 0 else 'System Default'

    print(f"\n[MIC]  Device  : {dev_name} (index={DEVICE if DEVICE is not None else 'default'})", flush=True)
    print(f"[MIC]  Chunk   : {CHUNK_SEC}s at {SAMPLE_RATE} Hz", flush=True)
    print(f"[MIC]  Threshold: RMS > {THRESHOLD}", flush=True)
    print("[MIC]  Speak into the microphone — subtitles will appear on Flutter app", flush=True)
    print("[MIC]  Tip: if you only see silence, run with --listdev and try --device <index>", flush=True)
    print("[MIC]  Press Ctrl+C to stop\n", flush=True)

    chunk_count = 0
    while True:
        try:
            # Record chunk
            audio = sd.rec(
                int(CHUNK_SEC * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype='float32',
                device=DEVICE
            )
            sd.wait()
            audio_mono = audio.flatten()

            # RMS level
            rms = float(np.sqrt(np.mean(audio_mono ** 2)))
            chunk_count += 1

            # Always show RMS every chunk so user knows mic is alive
            bar_len = min(int(rms * 500), 30)
            bar = '#' * bar_len + '.' * (30 - bar_len)
            print(f"[MIC]  RMS={rms:.5f}  [{bar}]  {'<< DETECTED' if rms >= THRESHOLD else 'silence'}", flush=True)

            if rms < THRESHOLD:
                continue

            # --- AUDIO BOOST (Normalization) ---
            # If the audio is very quiet, we boost it so Whisper can hear it clearly.
            # This prevents the "Thank you" hallucination.
            max_val = np.max(np.abs(audio_mono))
            if max_val > 0:
                audio_mono = audio_mono / max_val # Scale to 1.0 max
            
            if rms < 0.005:
                print(f"[WARN] Signal very weak (RMS={rms:.5f}). Subtitles might be inaccurate.", flush=True)

            print(f"[MIC]  Transcribing... (boosted max={np.max(audio_mono):.2f})", flush=True)
            t0   = time.time()
            text = transcribe(model, audio_mono, SAMPLE_RATE)
            dt   = time.time() - t0

            if not text:
                print("[MIC]  (no speech detected by Whisper)", flush=True)
                continue

            print(f"[WHISPER]  {text!r}  ({dt:.2f}s)", flush=True)

            # Script matching
            if script_lines:
                matched, conf = match_script(text)
                print(f"[MATCH]  {matched!r}  (confidence={conf:.2f})", flush=True)
                send_subtitle(matched, source='matched', confidence=conf)
            else:
                send_subtitle(text, source='whisper')

        except KeyboardInterrupt:
            print("\n[MIC]  Stopped by user.", flush=True)
            break
        except Exception as e:
            print(f"[MIC]  Error: {e}", flush=True)
            time.sleep(1)

# ── Main ──────────────────────────────────────────────────
def main():
    print("", flush=True)
    print("+-----------------------------------------------+", flush=True)
    print("|  [MIC] Live Auto Subtitle - Python AI Layer   |", flush=True)
    print(f"|  Model:  {args.model:<10}  Chunk: {args.chunk}s             |", flush=True)
    print(f"|  Server: {args.server:<34} |", flush=True)
    print("+-----------------------------------------------+", flush=True)
    print("", flush=True)

    if not connect_to_server():
        sys.exit(1)

    if args.script:
        load_script(args.script)

    if args.test:
        run_test_mode()
    else:
        run_live_mode()

    sio.disconnect()

if __name__ == '__main__':
    main()
