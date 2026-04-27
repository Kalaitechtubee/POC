// ============================================================
//  Live Auto Subtitle System — Node.js Master Server v2
//  Pipeline: Vosk (partial) -> English UI -> Translate -> UI
// ============================================================

const { createServer } = require('http');
const { Server }       = require('socket.io');
const path             = require('path');
const fs               = require('fs');
const { spawn }        = require('child_process');
const translate        = require('google-translate-api-x');

const PORT          = process.env.PORT || 3000;
const HISTORY_FILE  = path.join(__dirname, 'data', 'history.json');
const PYTHON_SCRIPT = path.join(__dirname, 'transcriber.py');

let targetLang      = 'ta';   // Default: Tamil
let subtitleHistory = [];
let pyProcess       = null;
let isRestarting    = false;
let lastFinal       = "";
let repeatHistory   = [];

let lastTranslatedText = "";
let lastTranslateTime = 0;
let pendingTranslations = 0; // Prevent queue bloat
const TRANSLATE_DEBOUNCE_MS = 1200; 

// ── Load persisted history ──────────────────────────────────
try {
  if (fs.existsSync(HISTORY_FILE)) {
    const raw = fs.readFileSync(HISTORY_FILE, 'utf8');
    subtitleHistory = JSON.parse(raw);
    console.log(`[HISTORY] Loaded ${subtitleHistory.length} entries.`);
  }
} catch (e) {
  console.warn('[HISTORY] File corrupted — starting fresh.');
  subtitleHistory = [];
}

function saveHistory() {
  try {
    fs.writeFileSync(HISTORY_FILE, JSON.stringify(subtitleHistory, null, 2), 'utf8');
  } catch (e) {
    console.warn('[HISTORY] Save failed:', e.message);
  }
}

// ── HTTP Server ─────────────────────────────────────────────
const httpServer = createServer((req, res) => {
  const url = req.url.split('?')[0];

  if (url === '/' || url === '/dashboard') {
    const dashPath = path.join(__dirname, 'dashboard.html');
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    fs.createReadStream(dashPath).pipe(res);
  } else if (url === '/history.json') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(subtitleHistory));
  } else {
    res.writeHead(404);
    res.end('Not found');
  }
});

const io = new Server(httpServer, {
  cors: { origin: '*' },
  pingTimeout:  20000,
  pingInterval: 10000,
});

// ── Translation with retry & timeout ────────────────────────
async function translateText(text, lang, retries = 2) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const result = await Promise.race([
        translate(text, { to: lang, forceTo: true }),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Translation timeout')), 5000)
        ),
      ]);
      return result.text || '';
    } catch (err) {
      const isLast = attempt === retries;
      if (!isLast) {
        const delay = 400 * Math.pow(2, attempt); // 400ms, 800ms
        console.warn(`[TRANS] Attempt ${attempt + 1} failed (${err.message}). Retry in ${delay}ms`);
        await new Promise(r => setTimeout(r, delay));
      } else {
        console.error('[TRANS] All retries exhausted:', err.message);
      }
    }
  }
  return '';
}

// ── Utility: Duplicate & Similarity Filter ──────────────
function isDuplicate(text) {
  return text.trim().toLowerCase() === lastFinal.trim().toLowerCase();
}

function isSimilar(newText, oldText) {
  if (!oldText) return false;
  const n = newText.trim().toLowerCase();
  const o = oldText.trim().toLowerCase();
  return n.startsWith(o) || o.startsWith(n);
}

function isRepeated(text) {
  return repeatHistory.some(t => text.includes(t) || t.includes(text));
}

function addRepeatHistory(text) {
  repeatHistory.push(text);
  if (repeatHistory.length > 20) repeatHistory.shift();
}

// ── NLP: Cleaning & Formatting ────────────────────────────
function sanitizeText(text) {
  let s = text
    .replace(/\bi\b/g, "I")
    .replace(/\s+/g, " ")
    .trim();
  return removeTrailingRepeat(s);
}

function fixSentence(text) {
  return text
    .replace(/\bgave me into\b/gi, "told me about")
    .replace(/\bfinish and\b/gi, "finished")
    .replace(/\btasked\b/gi, "tasks")
    .replace(/\s+/g, " ")
    .trim();
}

function removeTrailingRepeat(text) {
  const words = text.split(" ");
  if (words.length > 2 && words[words.length - 1].toLowerCase() === words[words.length - 2].toLowerCase()) {
    words.pop();
  }
  return words.join(" ");
}

function formatSentence(text) {
  if (!text) return "";
  let s = text.trim();
  // Capitalize first letter
  s = s.charAt(0).toUpperCase() + s.slice(1);
  // Add punctuation if missing
  if (!/[.?!]$/.test(s)) {
    const lower = s.toLowerCase();
    const isQ = lower.startsWith("why") || lower.startsWith("what") || 
                lower.startsWith("how") || lower.startsWith("is ") || 
                lower.startsWith("can ");
    s += isQ ? "?" : ".";
  }
  return s;
}

function isValid(text, confidence) {
  if (confidence < 0.85) return false;
  if (text.length < 5) return false;
  if (text.split(" ").length < 3) return false;
  return true;
}

// ── Main subtitle handler ────────────────────────────────────
async function handleSubtitle(text, isFinal, confidence) {
  const cleanText = text.trim();
  if (!cleanText) return;

  if (isFinal) {
    // ── Pro-Level Validation & NLP ──
    if (!isValid(cleanText, confidence)) return;
    if (isDuplicate(cleanText) || isSimilar(cleanText, lastFinal) || isRepeated(cleanText)) {
      lastFinal = cleanText;
      return;
    }
    
    lastFinal = cleanText;
    addRepeatHistory(cleanText);

    const sanitized = sanitizeText(cleanText);
    const corrected = fixSentence(sanitized);
    const formatted = formatSentence(corrected);

    // ── Step 1: Broadcast English immediately (no waiting) ──
    const entry = {
      text:       formatted,
      translated: '',
      is_final:   true,
      confidence: confidence || 1.0,
      id:         Date.now(),
      timestamp:  new Date().toISOString(),
    };

    subtitleHistory.push(entry);
    if (subtitleHistory.length > 100) subtitleHistory.shift();
    saveHistory();

    io.emit('final_subtitle', entry);
    console.log(`[ENG ✓] ${formatted} (conf: ${entry.confidence})`);

    // ── Step 2: Translate async — emit when ready ───────────
    pendingTranslations++;
    translateText(formatted, targetLang).then(translated => {
      pendingTranslations--;
      if (!translated) return;

      // Update history entry
      const hist = subtitleHistory.find(h => h.id === entry.id);
      if (hist) {
        hist.translated = translated;
        saveHistory();
      }

      io.emit('translation_ready', {
        id:         entry.id,
        text:       formatted,
        translated,
      });

      console.log(`[TRN ✓] ${formatted} → ${translated}`);
    });

  } else {
    // ── Partial: send English immediately ───────────────────
    io.emit('live_subtitle', { text: cleanText, translated: '', is_final: false });
    // console.log(`[LIVE] ${cleanText}`); // Removed to prevent terminal bottlenecks

    // Debounced translation for partials
    const wordCount = cleanText.split(' ').length;
    const now = Date.now();
    const isNewEnough = (wordCount >= 5 && Math.abs(wordCount - lastTranslatedText.split(' ').length) >= 3);
    const isTimeReady = (now - lastTranslateTime > TRANSLATE_DEBOUNCE_MS);

    if (wordCount >= 5 && (isNewEnough || isTimeReady) && pendingTranslations < 3) {
      lastTranslatedText = cleanText;
      lastTranslateTime = now;
      
      pendingTranslations++;
      translateText(cleanText, targetLang).then(translated => {
        pendingTranslations--;
        if (translated) {
          io.emit('live_subtitle', { text: cleanText, translated, is_final: false });
        }
      });
    }
  }
}

// ── Python Transcriber Process ───────────────────────────────
function startTranscriber() {
  if (isRestarting) return;

  console.log('[AI] Starting transcription engine...');
  pyProcess = spawn('python', ['-u', PYTHON_SCRIPT], {
    cwd: __dirname,
  });

  let buffer = '';

  pyProcess.stdout.on('data', (chunk) => {
    buffer += chunk.toString();
    const lines = buffer.split('\n');
    buffer = lines.pop(); // keep incomplete last line

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const msg = JSON.parse(trimmed);

        if (msg.status) {
          console.log('[AI STATUS]', msg.status);
          io.emit('engine_status', { status: msg.status });
        } else if (msg.error) {
          console.error('[AI ERROR]', msg.error);
          io.emit('engine_status', { status: 'error', message: msg.error });
        } else if (msg.final) {
          handleSubtitle(msg.final, true, msg.confidence);
        } else if (msg.partial) {
          handleSubtitle(msg.partial, false, null);
        }
      } catch (e) {
        // Non-JSON line (Python print debug etc.) — ignore
      }
    }
  });

  pyProcess.stderr.on('data', (data) => {
    const msg = data.toString().trim();
    if (msg) console.warn('[AI STDERR]', msg);
  });

  pyProcess.on('close', (code) => {
    console.log(`[AI] Engine exited (code ${code}). Restarting in 3s...`);
    io.emit('session_restart', { message: 'Engine restarted' });
    isRestarting = true;
    setTimeout(() => {
      isRestarting = false;
      startTranscriber();
    }, 3000);
  });
}

// ── Socket.IO connections ────────────────────────────────────
io.on('connection', (socket) => {
  const clientType = socket.handshake.query.type || 'web';
  console.log(`[+] ${clientType.toUpperCase()} connected  (${socket.id})`);

  // Send full history on connect
  socket.emit('history', subtitleHistory);

  socket.on('config_update', (config) => {
    if (config.target_lang && typeof config.target_lang === 'string') {
      targetLang = config.target_lang.slice(0, 5); // safety: max 5 chars
      console.log(`[CONFIG] Language → ${targetLang}`);
      // Acknowledge back
      socket.emit('config_ack', { target_lang: targetLang });
    }
  });

  socket.on('clear_history', () => {
    subtitleHistory = [];
    saveHistory();
    io.emit('history', []);
    console.log('[HISTORY] Cleared by client');
  });

  socket.on('disconnect', (reason) => {
    console.log(`[-] ${clientType.toUpperCase()} disconnected (${reason})`);
  });
});

// ── Start ────────────────────────────────────────────────────
httpServer.listen(PORT, '0.0.0.0', () => {
  console.log(`🚀  Dashboard  →  http://localhost:${PORT}`);
  console.log(`📁  History    →  ${HISTORY_FILE}`);
  startTranscriber();
});

// ── Graceful shutdown ────────────────────────────────────────
process.on('SIGINT', () => {
  console.log('\n[SYSTEM] Shutting down...');
  if (pyProcess) pyProcess.kill();
  httpServer.close(() => process.exit(0));
});