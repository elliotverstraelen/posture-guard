# PostureGuard 🧍

> Real-time posture monitor for macOS — uses your MacBook's front camera, MediaPipe Pose, and a local Ollama LLM to coach you back into shape.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

---

## How it works

PostureGuard watches your posture through the MacBook webcam using MediaPipe Pose (33 body landmarks). It detects four signals entirely from the front camera — no side view needed:

| Signal | What it detects |
|--------|----------------|
| Head drop | Nose descending toward the shoulder line |
| Forward lean | Shoulders appearing wider = you moved closer to the screen |
| Shoulder asymmetry | One shoulder higher than the other |
| Head tilt | Ear-to-ear line not horizontal |

When you first run the app you **calibrate** by sitting in your natural good posture for 2 seconds. Every reading after that is compared against your personal baseline — so the thresholds adapt to your body and setup, not hardcoded angles.

If your posture stays below 70/100 for 30 continuous seconds, a native macOS notification fires with an Ollama-generated coaching tip. When you correct yourself, you get a "Good job!" notification. The web dashboard shows a live score, active alerts, and a 5-minute history chart.

---

## Screenshots

| Good posture | Poor posture alert |
|---|---|
| ![Dashboard — good posture](docs/screenshots/dashboard.png) | ![Dashboard — alert state](docs/screenshots/alert-state.png) |

---

## Requirements

- macOS 12 or later
- Python 3.9
- [Ollama](https://ollama.ai) (optional — static fallback tips used if offline)

---

## Installation

### Option 1 — Homebrew tap (recommended)

```bash
brew tap elliotverstraelen/postureguard
brew install postureguard
postureguard
```

### Option 2 — pipx

```bash
pipx install git+https://github.com/elliotverstraelen/posture-guard.git
postureguard
```

### Option 3 — Manual

```bash
git clone https://github.com/elliotverstraelen/posture-guard.git
cd posture-guard
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

---

## Camera permission (macOS)

The first time you run the app, macOS will ask for camera access. If the webcam light never turns on:

**1. Reset the permission so macOS asks again:**
```bash
tccutil reset Camera com.apple.Terminal
```

**2. Restart the app.** A permission dialog will appear — click **OK**.

**If the dialog still doesn't appear:**  
Go to `System Settings → Privacy & Security → Camera` and enable **Terminal** manually.

> **Note for py2app bundle (.app):** The app has `NSCameraUsageDescription` set in its plist so macOS will prompt automatically on first launch.

---

## Ollama setup (for AI coaching tips)

Install Ollama and pull the model used by default:

```bash
brew install ollama
ollama serve          # start the Ollama daemon
ollama pull qwen3:8b  # ~5 GB download
```

To use a different model:
```bash
export OLLAMA_MODEL=llama3.2
python app.py
```

If Ollama is offline the app still works — it falls back to a set of static tips per alert type.

---

## Usage

### Web dashboard (Phase 1)

```bash
python app.py
# → http://127.0.0.1:5000
```

1. Open the dashboard in your browser
2. Click **🎯 Calibrate** and sit in your best upright posture for 2 seconds
3. The live score appears — the app monitors in the background and sends native notifications

### Menu bar app (Phase 2 — macOS only)

```bash
pip install rumps
python menu_bar_app.py
```

The app lives in the menu bar with no dock icon. Click the icon to see live score, re-calibrate, pause, or view a session summary.

### Package as a standalone .app

```bash
pip install py2app
python setup.py py2app
open dist/PostureGuard.app
```

---

## Configuration

All thresholds live in `core/posture_analyzer.py` and `core/alert_manager.py`. The most useful ones to tune:

| File | Variable | Default | What it controls |
|------|----------|---------|-----------------|
| `posture_analyzer.py` | `HEAD_DROP_THRESHOLD` | `0.12` | How far the head must drop before triggering (ratio of shoulder width) |
| `posture_analyzer.py` | `FORWARD_LEAN_THRESHOLD` | `0.07` | How much the apparent shoulder width must increase |
| `posture_analyzer.py` | `EAR_TILT_THRESHOLD_DEG` | `8.0` | Head tilt tolerance in degrees |
| `alert_manager.py` | `ALERT_TRIGGER_SECONDS` | `30` | Continuous bad posture before a notification |
| `alert_manager.py` | `ALERT_COOLDOWN_SECONDS` | `120` | Minimum gap between notifications |

You can also set environment variables:
```bash
export OLLAMA_URL=http://localhost:11434
export OLLAMA_MODEL=qwen3:8b
```

---

## Project structure

```
posture-guard/
├── app.py                   # Flask app + background camera loop (Phase 1 entry point)
├── menu_bar_app.py          # rumps menu bar app (Phase 2 entry point)
├── setup.py                 # py2app packaging
├── notifications.py         # macOS osascript notification wrapper
├── requirements.txt
├── core/
│   ├── pose_detector.py     # MediaPipe Pose wrapper
│   ├── posture_analyzer.py  # Feature extraction, deviation scoring, calibration
│   └── alert_manager.py     # 30-second timer + cooldown logic
├── ai/
│   ├── coach.py             # Ollama tip generation + static fallbacks
│   └── session_report.py    # HuggingFace zero-shot session categorisation
├── templates/
│   └── index.html           # Dashboard UI
├── static/js/
│   └── dashboard.js         # Polling + Chart.js history graph
└── scripts/
    └── mock_server.py       # Demo server (no camera needed — for screenshots/testing)
```

---

## Tech stack

| Module | Role |
|--------|------|
| **MediaPipe Pose** | 33-landmark pose detection, baseline calibration |
| **Ollama** | Local LLM for personalised coaching tips |
| **HuggingFace** (`facebook/bart-large-mnli`) | Zero-shot session quality classification |
| **Flask** | Web dashboard with MJPEG video stream |
| **osascript** | Native macOS notifications |
| **rumps** | Menu bar app (Phase 2) |
| **py2app** | Standalone `.app` packaging (Phase 2) |

---

## License

MIT — see [LICENSE](LICENSE).
