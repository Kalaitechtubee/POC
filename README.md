# 🎙️ Live Auto Subtitle System — POC

A real-time, cross-platform pipeline that transforms live speech into synchronized subtitles across mobile, web, and desktop clients.

---

## 🌟 Overview

This project is a Proof of Concept (POC) for a **Live Subtitle Display System**. It captures live audio from a microphone, transcribes it using advanced AI models, and broadcasts the text instantly to multiple connected devices.

### 🏗️ Architecture
1.  **Python AI Layer**: Uses **OpenAI Whisper** for high-accuracy speech-to-text. It captures audio chunks via the microphone, processes them with AI, and streams results via WebSockets.
2.  **Node.js Middleware**: A **Socket.io** server acting as a real-time hub. It bridges the AI layer with end-user applications and provides a central monitoring dashboard.
3.  **Flutter Dashboard**: A premium, dark-themed mobile/web/desktop app that displays the live subtitle stream with smooth animations and history tracking.

---

## 📁 Project Structure

```text
project/
├── python-ai/
│   ├── whisper_live.py       ← AI transcription + mic capture + WebSocket client
│   ├── requirements.txt      ← Python dependencies (Whisper, Socket.io, etc.)
│   └── script.txt            ← (Optional) Pre-defined script for matching
│
├── server/
│   ├── server.js             ← Node.js WebSocket hub (Socket.io)
│   ├── dashboard.html        ← Central monitoring dashboard (Web)
│   └── package.json          ← Node.js dependencies
│
└── flutter_app/
    ├── lib/main.dart         ← Flutter frontend application
    └── pubspec.yaml          ← Flutter dependencies
```

---

## 🚀 Getting Started

### 1️⃣ Start the Hub (Node.js Server)
The server must be running first to receive subtitles.
```powershell
cd project/server
npm install
npm run dev
```
🔗 **Monitor Dashboard**: [http://localhost:3000](http://localhost:3000)

---

### 2️⃣ Start the UI (Flutter App)
Run the application on your target device (Chrome, Android, iOS, or Desktop).
```powershell
cd project/flutter_app
flutter pub get
flutter run -d chrome
```

---

### 3️⃣ Start the AI (Python Layer)
This is the engine that listens to your voice.

#### **Option A: Test Mode (No Mic Needed)**
Sends pre-written sentences to test the connection.
```powershell
cd project/python-ai
$env:PYTHONUNBUFFERED="1"; py -3 whisper_live.py --test
```

#### **Option B: Live Microphone Mode**
Captures your real voice and transcribes it in real-time.
```powershell
$env:PYTHONUNBUFFERED="1"; py -3 whisper_live.py --model base --chunk 4 --lang en
```

---

## 🛠️ CLI Configuration (Python)

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `base` | Model size (`tiny`, `base`, `small`, `medium`, `large`). |
| `--chunk` | `5` | Audio chunk size in seconds (lower = faster, higher = accurate). |
| `--device` | `None` | Mic device index (run with `--listdev` to see all mics). |
| `--threshold`| `0.001` | Silence threshold RMS. |
| `--lang` | `auto` | Force language code (e.g., `en`, `ta`, `hi`). |
| `--listdev` | - | Lists all available microphone devices. |

---

## 🧩 Key Features

- **Real-time AI Transcription**: Powered by OpenAI Whisper.
- **Smart Silence Detection**: Automatically skips quiet periods to save processing power.
- **Script Matching**: (Optional) Aligns noisy transcriptions with a predefined script for 100% accuracy in controlled environments.
- **Multi-Client Broadcast**: One AI engine can stream to hundreds of devices simultaneously.
- **Cross-Platform**: Works on Web, Android, iOS, Windows, macOS, and Linux.

---

## 🔧 Windows Troubleshooting

If you encounter issues on Windows, ensure the following:
1. **Python Path**: Use `py -3` instead of `python` if the environment is not set.
2. **Encoding**: The script is optimized to handle UTF-8 symbols in the Windows terminal.
3. **FFmpeg**: If file-based transcription fails, ensure FFmpeg is installed and added to your PATH.
4. **Buffering**: Always use `$env:PYTHONUNBUFFERED="1"` to see real-time logs in PowerShell.
