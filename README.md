# 🎤 LiveScript Pro (v2) — Live Auto Subtitle & Translation

A professional-grade, ultra-low latency transcription and translation engine designed for high-stakes presentations, broadcasts, and accessibility.

## 🚀 Key Features (v2 Upgrades)

*   **⚡ Async Non-Blocking Pipeline**: English subtitles are broadcast **instantly**. Translations follow asynchronously, ensuring zero lag in the primary transcript.
*   **🌍 Intelligent Neural Translation**: Real-time translation to Tamil and other regional languages with automatic retry logic.
*   **🎬 Real Streaming Word Engine (v2.5)**: A true typewriter-style engine that appends words incrementally as they are spoken. Unlike standard systems that "jump" between sentences, LiveScript Pro tracks the word stream and extracts only new content for a 100% stable visual flow.
*   **🛡️ Drift-Resistant Logic**: Advanced comparison logic ensures that if the acoustic engine corrects itself mid-sentence, the UI handles it gracefully without duplicating words or breaking the "word flow."
*   **📖 Cinematic Dual-Panel Feed**: Independent scrollable panels for English and Translation, featuring a live blinking cursor, session markers, and smart auto-scroll.
*   **🧠 Intelligent NLP Layer**: Automatic sentence formatting (capitalization, punctuation), grammar cleanup (e.g., "i" to "I"), and context-aware replacement of common acoustic mis-transcriptions.
*   **🎯 Latest Sentence Highlight**: The UI dynamically highlights the active speech area with a distinct blue glow and a focused typing cursor.

## 🏗️ System Architecture

1.  **AI Engine (`transcriber.py`)**: 
    *   Vosk-powered local transcription (16kHz).
    *   Confidence-based filtering and junk pattern rejection.
    *   Real-time JSON status reporting.
2.  **Relay Server (`server.js`)**: 
    *   Node.js Socket.io hub for multi-client synchronization.
    *   Asynchronous translation worker with exponential backoff retries.
    *   Automatic file-based history persistence.
3.  **Pro Dashboard (`dashboard.html`)**: 
    *   Premium UI with Noto Sans Tamil typography.
    *   Independent scroll-tracking and "Jump to Bottom" intelligence.
    *   Real-time word count and system health telemetry.

## 🛠️ Quick Start

### 1. Requirements
*   Python 3.10+
*   Node.js 18+
*   Vosk Model (English) in `server/model/`

### 2. Launch the System
```bash
cd server
npm install
npm run dev
```

### 3. Access
*   **Web Dashboard**: `http://localhost:3000`
*   **History Data**: `http://localhost:3000/history.json`

## ⌨️ Console Observability
The server terminal provides real-time feedback on the processing pipeline:
*   `[AI STATUS]` — Reports engine state (loading, ready, streaming).
*   `[LIVE]` — Real-time partial word stream (as you speak).
*   `[ENG ✓]` — Completed English sentence (finalized).
*   `[TRN ✓]` — Asynchronous translation successfully synced to UI.
*   `[HISTORY]` — Database activity (loading/saving session state).

---
*Built for BerrybeansTech POC — LiveScript Pro Edition.*
