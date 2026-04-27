import sys
import json
import os
import re
import sounddevice as sd
from vosk import Model, KaldiRecognizer

# ── Config ─────────────────────────────────────────────────────
MODEL_PATH  = "model"
SAMPLE_RATE = 16000
BLOCK_SIZE  = 3200   # ~200ms chunks — faster real-time feedback

# Minimum word count to emit a final segment
MIN_FINAL_WORDS = 3

# ── Junk / hallucination patterns ──────────────────────────────
JUNK_PATTERNS = [
    r'^(uh+|um+|hm+|hmm+|ah+|oh+|eh+)$',         # filler sounds
    r'^(the|a|an|and|or|but|so|is|it|i|he|she|we|you|they|can|do|did|was|were|be|been|has|have|had|will|would|could|should|shall)$',  # lone stop words
    r'(thank you|thanks|subscribe|watching|amara\.org|subtitl)',  # common hallucinations
    r'^(.)\1{3,}$',                                 # repeated char: "aaaa"
    r'^(\w+)( \1){2,}$',                            # repeated word: "the the the"
]
JUNK_RE = [re.compile(p, re.IGNORECASE) for p in JUNK_PATTERNS]

def is_junk(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    words = t.split()
    if len(words) < MIN_FINAL_WORDS:
        # Allow very short if none of the junk patterns match
        for pattern in JUNK_RE:
            if pattern.search(t):
                return True
        # Still discard 1-word finals unless clearly meaningful
        if len(words) == 1:
            return True
    for pattern in JUNK_RE:
        if pattern.search(t):
            return True
    return False

def emit(obj: dict):
    """Write JSON line to stdout and flush immediately so Node.js receives it."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)

# ── Model Load ──────────────────────────────────────────────────
if not os.path.exists(MODEL_PATH):
    emit({"error": f"Model not found at '{MODEL_PATH}'. Download vosk-model-small-en-us-0.15 and rename to 'model'."})
    sys.exit(1)

emit({"status": "loading_model"})
model = Model(MODEL_PATH)
rec   = KaldiRecognizer(model, SAMPLE_RATE)
rec.SetWords(True)       # enables per-word confidence
emit({"status": "ready"})

# ── Audio Callback ──────────────────────────────────────────────
last_partial = ""

def callback(indata, frames, time_info, status):
    global last_partial

    raw = bytes(indata)
    if not raw:
        return

    if rec.AcceptWaveform(raw):
        # ── FINAL result ───────────────────────────────────────
        result = json.loads(rec.Result())
        text   = result.get("text", "").strip()

        if not text or is_junk(text):
            last_partial = ""
            return

        # Confidence from word-level results
        words = result.get("result", [])
        if words:
            avg_conf = sum(w.get("conf", 1.0) for w in words) / len(words)
            if avg_conf < 0.8:          # low confidence — skip
                last_partial = ""
                return
            emit({"final": text, "confidence": round(avg_conf, 3)})
        else:
            emit({"final": text, "confidence": 1.0})

        last_partial = ""

    else:
        # ── PARTIAL result ─────────────────────────────────────
        partial = json.loads(rec.PartialResult()).get("partial", "").strip()

        # Only emit if partial has actually changed
        if partial and partial != last_partial:
            last_partial = partial
            emit({"partial": partial})

# ── Start Stream ────────────────────────────────────────────────
try:
    with sd.RawInputStream(
        samplerate  = SAMPLE_RATE,
        blocksize   = BLOCK_SIZE,
        dtype       = 'int16',
        channels    = 1,
        callback    = callback
    ):
        emit({"status": "streaming"})
        while True:
            sd.sleep(100)

except KeyboardInterrupt:
    emit({"status": "stopped"})
except Exception as e:
    emit({"error": str(e)})
    sys.exit(1)