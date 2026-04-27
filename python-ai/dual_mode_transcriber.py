#!/usr/bin/env python3
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
from deep_translator import GoogleTranslator

# --- Fix Windows stdout encoding (cp1252 -> utf-8) ---
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass

## --- Configuration ---
parser = argparse.ArgumentParser(description='Dual-Mode Live Subtitle (Vosk + Faster-Whisper + Translation)')
parser.add_argument('--server',     default='http://localhost:3000', help='Server URL')
parser.add_argument('--model',      default='tiny',                 help='Faster-Whisper model size (tiny, base, small)')
parser.add_argument('--vosk-model', default='vosk-model-en-us-0.22', help='Vosk model directory')
parser.add_argument('--device',     type=int, default=None,         help='Mic device index')
parser.add_argument('--chunk',      type=float, default=1.0,        help='Whisper chunk size in seconds (0.8-1.5 recommended)')
parser.add_argument('--listdev',    action='store_true',              help='List all audio devices and exit')
parser.add_argument('--threshold',  type=float, default=0.005,        help='Silence threshold (RMS)')
parser.add_argument('--lang',       default='en',                   help='Source language (e.g. en)')
parser.add_argument('--translate',  action='store_true',            help='Enable real-time translation')
parser.add_argument('--target-lang', default='ta',                  help='Target language (ta, te, kn, ml)')
args = parser.parse_args()

if args.vosk_model == 'vosk-model-en-us-0.22' and not Path(args.vosk_model).exists():
    # Fallback to small model if 0.22 is not downloaded yet
    if Path('vosk-model-small-en-us-0.15').exists():
        args.vosk_model = 'vosk-model-small-en-us-0.15'

if args.listdev:
    print("\nAvailable audio INPUT devices:")
    print("-" * 50)
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            marker = " <-- DEFAULT" if i == sd.default.device[0] else ""
            print(f"  [{i}] {d['name']}{marker}")
    print("-" * 50)
    sys.exit(0)

# --- Socket.io Setup ---
sio = socketio.Client()

# --- Socket Event Handlers ---
@sio.on('connect')
def on_connect():
    safe_print("[WS]  Connected to server")

@sio.on('disconnect')
def on_disconnect():
    safe_print("[WS]  Disconnected")

@sio.on('config_update')
def on_config(data):
    if 'target_lang' in data:
        args.target_lang = data['target_lang']
        safe_print(f"[CONFIG] Target language changed to: {args.target_lang}")

def connect_to_server():
    try:
        url = f"{args.server}?type=python"
        sio.connect(url)
        return True
    except Exception as e:
        print(f"[WS]  Connection failed: {e}")
        return False

# --- Helper: Translation ---
def translate_text(text, target='ta'):
    if not text.strip(): return ""
    try:
        translated = GoogleTranslator(source='auto', target=target).translate(text)
        return translated
    except Exception as e:
        safe_print(f"[TRANS] Error: {e}")
        return ""

# --- Helper: Text Cleaning ---
def clean_text(text):
    """Clean and format text."""
    text = text.strip()
    if not text: return ""
    # Remove Whisper's common repetitive symbols
    text = text.replace('...', '').replace('..', '')
    if not text: return ""
    # Capitalize first letter
    text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()
    return text

# --- Globals ---
print_lock = threading.Lock()
last_vosk_text = ""
transcription_history = []

def safe_print(*args, **kwargs):
    with print_lock:
        print(*args, flush=True, **kwargs)

# --- Model Loading ---
safe_print(f"[VOSK]  Loading model from {args.vosk_model}...")
if not Path(args.vosk_model).exists():
    safe_print(f"[ERROR] Vosk model directory not found: {args.vosk_model}")
    safe_print("[TIP]   Download 'vosk-model-en-us-0.22' for pro accuracy.")
    sys.exit(1)
vosk_model = Model(args.vosk_model)
rec = KaldiRecognizer(vosk_model, 16000)

safe_print(f"[WHISPER] Loading Faster-Whisper '{args.model}' (int8)...")
whisper_model = WhisperModel(args.model, device="cpu", compute_type="int8")
safe_print("[SYSTEM]  Models ready")

# --- Audio Handling ---
audio_q = queue.Queue()
whisper_q = queue.Queue()

def audio_callback(indata, frames, time, status):
    if status:
        safe_print(f"[AUDIO] {status}", file=sys.stderr)
    audio_q.put(bytes(indata))

def is_valid_correction(whisper_text, vosk_text, info, target_lang):
    """Pro Filter Logic: Only correct if Whisper result is high quality."""
    if not whisper_text or len(whisper_text.strip()) <= 1:
        return False
    
    # 1. Expand Hallucination phrases (Whisper's common defaults on noise/silence)
    hallucinations = [
        "thank you", "subscribe", "watching", "amara.org", "subtitle",
        "see you in the next", "next video", "thanks for", "you guys",
        "please like", "god bless", "i pray to god", "thank you very much",
        "see you next time", "i'll see you tomorrow", "bye for now", "i'm out"
    ]
    low_text = whisper_text.lower()
    # If a short sentence ( < 8 words) contains any of these, it's almost certainly a hallucination
    if any(h in low_text for h in hallucinations) and len(whisper_text.split()) < 8:
        return False
        
    # 2. Language sanity check: If Whisper is very sure it's another language
    if target_lang and info.language != target_lang and info.language_probability > 0.9:
        return False
    
    # 3. Density/Length check: 
    # If Whisper result is much shorter than what Vosk already got, it might be dropping info
    vosk_words = len(vosk_text.split())
    whisp_words = len(whisper_text.split())
    if vosk_words > 4 and whisp_words < (vosk_words / 2):
        return False
        
    # 4. Repetition check
    if len(whisper_text) > 15 and len(set(whisper_text)) / len(whisper_text) < 0.15:
        return False

    return True

def whisper_processor():
    """Background thread for smart correction."""
    global last_vosk_text
    while True:
        # Latency Management
        if whisper_q.qsize() > 2:
            while whisper_q.qsize() > 1:
                try: whisper_q.get_nowait(); whisper_q.task_done()
                except: break
        
        audio_chunk = whisper_q.get()
        if audio_chunk is None: break
        
        audio_np = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        
        # VAD
        rms = np.sqrt(np.mean(audio_np**2))
        if rms < args.threshold:
            whisper_q.task_done()
            continue

        # Normalize
        max_val = np.max(np.abs(audio_np))
        if max_val > 0.01:
            audio_np = audio_np / max_val

        t0 = time.time()
        # Transcribe with beam_size=3 (faster than 5)
        segments, info = whisper_model.transcribe(audio_np, beam_size=3, language=args.lang)
        
        full_text = "".join([s.text for s in segments])
        full_text = clean_text(full_text)
        
        # Smart Replace Logic
        if is_valid_correction(full_text, last_vosk_text, info, args.lang):
            dt = time.time() - t0
            
            translated = ""
            if args.translate:
                translated = translate_text(full_text, args.target_lang)
                safe_print(f"[WHISPER] Correction: \"{full_text}\" -> {translated} ({dt:.2f}s)")
            else:
                safe_print(f"[WHISPER] Correction: \"{full_text}\" ({dt:.2f}s)")
            
            # Emit dual-language payload
            sio.emit("final_subtitle", {"text": full_text, "translated": translated})
            # If Whisper is very different, update Vosk's baseline to prevent rapid switching
            last_vosk_text = full_text
        
        whisper_q.task_done()

def run_dual_mode():
    global last_vosk_text
    SAMPLE_RATE = 16000
    CHUNK_SIZE  = int(SAMPLE_RATE * args.chunk)
    OVERLAP_SIZE = int(SAMPLE_RATE * 0.5) # 0.5s overlap for sliding window
    
    threading.Thread(target=whisper_processor, daemon=True).start()
    
    safe_print(f"\n[MIC]  Capture: {args.device if args.device is not None else 'Default'}")
    safe_print(f"[MIC]  Mode: Live (Vosk) + Smart Correction (Whisper Tiny) {'+ Translation ('+args.target_lang+')' if args.translate else ''}")
    safe_print(f"[MIC]  Chunk: {args.chunk}s | Lang: {args.lang}\n")

    current_chunk_buffer = bytearray()
    
    try:
        # blocksize=1000 is ~60ms @ 16kHz - very responsive
        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=1000, device=args.device,
                                dtype='int16', channels=1, callback=audio_callback):
            while True:
                data = audio_q.get()
                current_chunk_buffer.extend(data)
                
                # 1. Vosk Live (Aggressive Streaming)
                if rec.AcceptWaveform(data):
                    res = json.loads(rec.Result())
                    text = res.get("text", "").strip()
                    if text:
                        last_vosk_text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()
                        
                        translated = ""
                        if args.translate:
                            translated = translate_text(last_vosk_text, args.target_lang)
                            # safe_print(f"Vosk: {last_vosk_text} -> {translated}")
                            
                        sio.emit("live_subtitle", {"text": last_vosk_text, "translated": translated, "is_final": True})
                else:
                    res = json.loads(rec.PartialResult())
                    partial = res.get("partial", "").strip()
                    if partial:
                        formatted_partial = partial[0].upper() + partial[1:] if len(partial) > 1 else partial.upper()
                        
                        translated = ""
                        # Aggressive Translation for Live Typing
                        if args.translate and len(partial.split()) >= 3: 
                            # Only translate if we have at least 3 words to avoid flickering/nonsense
                            translated = translate_text(formatted_partial, args.target_lang)
                        
                        sio.emit("live_subtitle", {"text": formatted_partial, "translated": translated, "is_final": False})

                # 2. Whisper Sliding Window (0.8s for faster feedback)
                if len(current_chunk_buffer) >= (int(SAMPLE_RATE * 0.8) * 2):
                    whisper_q.put(bytes(current_chunk_buffer))
                    # Keep overlap
                    overlap_data = current_chunk_buffer[-(OVERLAP_SIZE * 2):]
                    current_chunk_buffer = bytearray(overlap_data)

    except KeyboardInterrupt:
        safe_print("\n[SYSTEM] Stopping...")
    except Exception as e:
        safe_print(f"[ERROR] {e}")

if __name__ == '__main__':
    if connect_to_server():
        run_dual_mode()
    else:
        safe_print("[ERROR] Could not connect to server.")
