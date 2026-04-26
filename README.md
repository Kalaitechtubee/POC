# 🎙️ Live Auto Subtitle System — PRO Version

A high-performance, real-time subtitle pipeline combining **Vosk** for instantaneous "live typing" and **Faster-Whisper** for premium accuracy.

---

## 🌟 Overview

This project is a high-performance **Live Subtitle System**. It solves the "latency vs. accuracy" trade-off by using two AI models simultaneously:
1.  **Vosk (Live Typing)**: Provides ultra-low latency text (sub-100ms) for an immediate "typing" effect.
2.  **Faster-Whisper (Accuracy)**: Corrects the live text every few seconds with industry-leading accuracy (99+ languages).

### 🏗️ Architecture & Flow
1.  **Audio Input**: Captured via `sounddevice` in Python.
2.  **Dual AI Engine**:
    *   **Vosk** processes the raw byte stream for immediate partial results.
    *   **Faster-Whisper** processes accumulated 3-4 second chunks for a high-quality "final" sentence.
3.  **WebSocket Hub**: A **Node.js (Socket.io)** server relays both "live" and "final" subtitles to all clients.
4.  **Flutter Frontend**: A premium UI that displays live typing (blue) and auto-corrects to the final version (green) with smooth animations.

---

## 📁 Project Structure

```text
project/
├── python-ai/
│   ├── dual_mode_transcriber.py  ← NEW: Combined Vosk + Faster-Whisper engine
│   ├── whisper_live.py           ← Original Whisper implementation
│   ├── vosk-model-small-en-us/   ← Vosk local model for speed
│   ├── requirements.txt          ← Python packages: faster-whisper, vosk, etc.
│   └── script.txt                ← Pre-defined script for matching (optional)
│
├── server/
│   ├── server.js                 ← Node.js hub with live/final event support
│   ├── dashboard.html            ← Web monitoring dashboard
│   └── package.json              ← Node.js packages: socket.io, express
│
└── flutter_app/
    ├── lib/main.dart             ← Flutter app with dual-subtitle state logic
    └── pubspec.yaml              ← Flutter packages: socket_io_client
```

---

## 🚀 Getting Started

### 1️⃣ Start the Hub (Node.js Server)
```powershell
cd project/server
npm install
npm run dev
```

### 2️⃣ Start the UI (Flutter App)
```powershell
cd project/flutter_app
flutter pub get
flutter run -d chrome
```

### 3️⃣ Start the PRO AI Engine (Python)
This engine handles the dual-model processing.
```powershell
cd project/python-ai
# Ensure dependencies are installed
pip install -r requirements.txt
# Run the dual-mode transcriber
python dual_mode_transcriber.py --model base --chunk 4
```

---

## 🛠️ Tech Stack & Packages

### **Python AI Layer**
- `faster-whisper`: High-speed CTranslate2 implementation of OpenAI's Whisper.
- `vosk`: Offline open-source speech recognition (Kaldi-based).
- `sounddevice` & `numpy`: High-performance audio capture and processing.
- `python-socketio[client]`: Real-time communication.

### **Node.js Middleware**
- `socket.io`: Bidirectional WebSocket communication.
- `express`: Minimalist web framework for the dashboard.
- `nodemon`: Development auto-restart.

### **Flutter Frontend**
- `socket_io_client`: Mobile/Web WebSocket client.
- `ticker_provider`: For smooth subtitle flash animations.

---

## 🧩 Logic Workflow

1.  **Voice Detected**: Microphones starts capturing data.
2.  **Live Path**: Vosk emits `live_subtitle` → Node.js → Flutter (Shows **blue** text instantly).
3.  **Final Path**: Every 4 seconds, the buffer is sent to Faster-Whisper → `final_subtitle` → Node.js → Flutter (Replaces text with **green** high-accuracy version).
4.  **History**: The final version is saved to the history sidebar for later review.

---

## 🔧 Windows Troubleshooting

1.  **EADDRINUSE (Port 3000)**: If the server fails to start, another process is using port 3000. Run `taskkill /F /IM node.exe` or use a different port.
2.  **Unicode Errors**: If you see characters like `✅` crashing the terminal, the script includes a `sys.stdout.reconfigure` fix. Use a modern terminal like Windows Terminal or VS Code integrated terminal.
3.  **CUDA/GPU**: By default, Faster-Whisper runs on CPU. If you have an NVIDIA GPU, change `device="cpu"` to `device="cuda"` in `dual_mode_transcriber.py` for 10x more speed.
