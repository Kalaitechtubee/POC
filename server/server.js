// ============================================================
//  Live Auto Subtitle System — Node.js WebSocket Server
//  Technology: socket.io on port 3000
//  Role: Relay subtitles from Python → all connected Flutter clients
// ============================================================

const { createServer } = require('http');
const { Server }       = require('socket.io');
const path             = require('path');
const fs               = require('fs');

// ── Config ────────────────────────────────────────────────
const PORT            = process.env.PORT || 3000;
const SUBTITLE_HISTORY = 50; // keep last N subtitles in memory

// ── State ─────────────────────────────────────────────────
let subtitleHistory   = [];
let connectedClients  = { python: [], flutter: [], web: [] };
let stats             = { totalSent: 0, startTime: Date.now() };

// ── HTTP Server (serves the web dashboard on GET /) ───────
const httpServer = createServer((req, res) => {
  const dashboardPath = path.join(__dirname, 'dashboard.html');

  if (req.url === '/' || req.url === '/dashboard') {
    if (fs.existsSync(dashboardPath)) {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      fs.createReadStream(dashboardPath).pipe(res);
    } else {
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end('Live Subtitle WebSocket Server is running. Connect your Flutter app.');
    }
  } else if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      status:        'ok',
      uptime_sec:    Math.floor((Date.now() - stats.startTime) / 1000),
      total_sent:    stats.totalSent,
      connected:     {
        python:  connectedClients.python.length,
        flutter: connectedClients.flutter.length,
        web:     connectedClients.web.length,
      },
      history_count: subtitleHistory.length,
    }));
  } else if (req.url === '/history') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ subtitles: subtitleHistory }));
  } else {
    res.writeHead(404);
    res.end('Not found');
  }
});

// ── Socket.io ─────────────────────────────────────────────
const io = new Server(httpServer, {
  cors: {
    origin:  '*',
    methods: ['GET', 'POST'],
  },
});

// ── Connection Handler ────────────────────────────────────
io.on('connection', (socket) => {
  const clientType = socket.handshake.query.type || 'unknown';
  const clientIP   = socket.handshake.address;

  console.log(`[+] ${clientType.toUpperCase()} connected — ID: ${socket.id}  IP: ${clientIP}`);

  // Register by type
  if (connectedClients[clientType]) {
    connectedClients[clientType].push(socket.id);
  }

  // Send existing history to newly connected display clients
  if (clientType === 'flutter' || clientType === 'web') {
    socket.emit('history', subtitleHistory);
  }

  // Broadcast updated connection stats to all clients
  broadcastStats();

  // ── Receive subtitle from Python ──────────────────────
  socket.on('subtitle', (payload) => {
    const text      = typeof payload === 'string' ? payload : payload?.text || '';
    const confidence = typeof payload === 'object' ? payload?.confidence : null;
    const source     = typeof payload === 'object' ? payload?.source    : 'whisper';

    if (!text.trim()) return; // skip empty

    const entry = {
      id:         stats.totalSent + 1,
      text:       text.trim(),
      source:     source || 'whisper',
      confidence: confidence,
      timestamp:  new Date().toISOString(),
    };

    // Store in rolling history
    subtitleHistory.push(entry);
    if (subtitleHistory.length > SUBTITLE_HISTORY) subtitleHistory.shift();

    stats.totalSent++;

    console.log(`[SUB #${entry.id}] "${entry.text}"  (source: ${entry.source})`);

    // Broadcast to ALL connected clients (flutter + web monitors)
    io.emit('subtitle', entry);
    broadcastStats();
  });

  // ── Receive LIVE subtitle from Python (Vosk) ────────────────
  socket.on('live_subtitle', (text) => {
    if (!text.trim()) return;
    // We don't store live subtitles in history usually, just broadcast for immediate display
    io.emit('live_subtitle', text);
  });

  // ── Receive FINAL subtitle from Python (Faster-Whisper) ──────
  socket.on('final_subtitle', (text) => {
    if (!text.trim()) return;
    
    const entry = {
      id:         stats.totalSent + 1,
      text:       text.trim(),
      source:     'faster-whisper',
      timestamp:  new Date().toISOString(),
    };

    subtitleHistory.push(entry);
    if (subtitleHistory.length > SUBTITLE_HISTORY) subtitleHistory.shift();
    stats.totalSent++;

    console.log(`[FINAL] "${entry.text}"`);
    io.emit('final_subtitle', text); // User wants just text for final_subtitle event
    io.emit('subtitle', entry);      // Also send as standard subtitle for history compatibility
    broadcastStats();
  });

  // ── Script upload from Python (optional) ─────────────
  socket.on('script_loaded', (data) => {
    console.log(`[SCRIPT] Script loaded: ${data?.line_count} lines`);
    io.emit('script_loaded', data);
  });

  // ── Ping / keep-alive ─────────────────────────────────
  socket.on('ping_server', () => {
    socket.emit('pong_server', { time: Date.now() });
  });

  // ── Disconnect ────────────────────────────────────────
  socket.on('disconnect', (reason) => {
    console.log(`[-] ${clientType.toUpperCase()} disconnected — ID: ${socket.id}  reason: ${reason}`);

    // Remove from tracking
    Object.keys(connectedClients).forEach((type) => {
      connectedClients[type] = connectedClients[type].filter(id => id !== socket.id);
    });

    broadcastStats();
  });
});

// ── Helper: broadcast stats ───────────────────────────────
function broadcastStats() {
  io.emit('server_stats', {
    connected:   {
      python:  connectedClients.python.length,
      flutter: connectedClients.flutter.length,
      web:     connectedClients.web.length,
    },
    total_sent:  stats.totalSent,
    uptime_sec:  Math.floor((Date.now() - stats.startTime) / 1000),
  });
}

// ── Start ─────────────────────────────────────────────────
httpServer.listen(PORT, '0.0.0.0', () => {
  console.log('');
  console.log('╔═══════════════════════════════════════════════╗');
  console.log('║   🎤  Live Auto Subtitle — WebSocket Server   ║');
  console.log(`║   Listening on  http://0.0.0.0:${PORT}            ║`);
  console.log('║   Dashboard →   http://localhost:' + PORT + '/       ║');
  console.log('║   Health    →   http://localhost:' + PORT + '/health  ║');
  console.log('╚═══════════════════════════════════════════════╝');
  console.log('');
  console.log('Waiting for Python AI and Flutter clients to connect...');
});
