# PostureGuard

Real-time posture monitor for macOS. Lives in your menu bar, watches your cameras, and nudges you before your back gives out.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)
![Release](https://img.shields.io/github/v/release/elliotverstraelen/posture-guard)

---

## Install

```bash
brew tap elliotverstraelen/postureguard
brew install postureguard
postureguard
```

macOS will ask for camera access on first launch — click OK.

---

## Features

| | |
|---|---|
| **Menu bar indicator** | 🟢 🟡 🔴 + live score; no dock icon |
| **Personal calibration** | Sit normally for 2 s; all thresholds are relative to *your* body, not hardcoded angles |
| **Persistent calibration** | Calibrate once — baseline is saved and restored every launch, survives reboots |
| **4 posture signals** | Head drop · Forward lean · Shoulder asymmetry · Head tilt |
| **Smart notifications** | Alert after 30 s of sustained bad posture; "Good job!" when you recover |
| **Best-camera selection** | When multiple cameras are active, PostureGuard picks the one with the highest score each frame — a poorly-angled camera never drags the reading down |
| **Phone detection** | Optional alert when you've been looking down for more than X minutes (configurable) |
| **Live View** | Floating window showing all camera feeds side-by-side with MediaPipe skeleton overlay and live score |
| **Calibration Studio** | Label your common poses as good / bad using actual camera photos — personalise detection over time |
| **AI coaching tips** | Personalised advice via Ollama (optional); falls back to curated static tips |
| **Flask dashboard** | Optional web UI with live video, score gauge, and session history chart |

---

## How it works

PostureGuard runs **MediaPipe Pose** (33 body landmarks) on every camera frame. During calibration it averages ~60 frames into a personal baseline. Every subsequent frame is scored by deviation from that baseline — so someone who naturally leans slightly left still gets a fair score.

When the score stays below 70 for 30 continuous seconds, a macOS notification fires. With **Ollama** running locally, the tip is generated from the active alert types. Without it, a curated static tip is shown.

The **best-camera selection** logic reads all active cameras each frame and picks whichever returns the highest posture score. This prevents a camera mounted at an awkward angle (e.g. on top of a tall monitor) from falsely penalising you when your MacBook camera sees you sitting straight.

---

## Calibration tip

Calibrate while looking at the **screen you actually work on** — not the camera. If your main monitor is above your laptop, look at the monitor during calibration so that gaze angle becomes your "good posture" baseline.

You only need to calibrate once. If you move to a different desk or add a new camera, use **Recalibrate** from the menu bar.

---

## Settings

Open the Settings panel from the menu bar (⚙️ Settings…):

- **Camera** — pick a specific camera or enable all cameras simultaneously
- **Phone detection** — toggle on/off; set how many minutes before an alert fires
- **Posture alert delay** — how many seconds of bad posture before a notification
- **Calibration Studio** — label saved pose snapshots as good or bad using real camera photos; once you have 10+ labeled poses the "Improve model" button becomes available to personalise your thresholds

---

## Optional: Ollama AI coaching

```bash
brew install ollama
ollama serve
ollama pull qwen3:8b
```

PostureGuard auto-detects Ollama. If it isn't running, static tips are used instead.

---

## Optional: web dashboard

```bash
git clone https://github.com/elliotverstraelen/posture-guard
cd posture-guard
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
# → http://127.0.0.1:5000
```

---

## Development

```bash
git clone https://github.com/elliotverstraelen/posture-guard
cd posture-guard
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-menubar.txt
python menu_bar_app.py
```

**Releasing** — push a version tag and CI does the rest:

```bash
git tag v1.3.0 && git push --tags
```

GitHub Actions builds the `.app` with py2app, creates a GitHub Release with the zip, and updates the Homebrew formula SHA256 automatically.

---

## Technical decisions

See [`docs/engineering-decisions.md`](docs/engineering-decisions.md) for a full log of non-obvious design choices — why rumps submenus were replaced with native NSWindows, how the multi-camera best-score selection works, why head-tilt detection has a visibility guard, and more.
