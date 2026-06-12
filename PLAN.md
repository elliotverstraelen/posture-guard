# PostureGuard — Project Plan

## What it is
A real-time posture monitor for macOS that uses the MacBook's built-in front-facing webcam,
MediaPipe Pose for landmark detection, Ollama for coaching tips, osascript for native
macOS notifications, and Flask for a live web dashboard.

---

## Phase 1 — Flask Web App (core submission)

### Graded technologies used
| Module | Usage |
|--------|-------|
| MediaPipe Pose | 33-landmark pose detection, upper-body posture signals |
| Ollama | Generates personalised coaching tips when bad posture is detected |
| HuggingFace | Zero-shot classification of each session's posture profile into categories; sentiment check on Ollama tips |
| Flask | Live web dashboard — video feed, score, history chart |
| osascript | Native macOS notification on posture alert |

### Detection signals (front camera only — no side view needed)

All four signals are compared to a **calibrated baseline** so the system adapts to any
person, desk height, or camera position.

| Signal | Feature | Direction of bad posture |
|--------|---------|--------------------------|
| Head drop | `(nose.y − shoulder_mid.y) / shoulder_width` | increases (nose closer to shoulders) |
| Shoulder asymmetry | `(left_sh.y − right_sh.y) / shoulder_width` | absolute deviation from baseline |
| Head tilt | `arctan2(right_ear.y − left_ear.y, dx)` in degrees | absolute deviation from baseline |
| Forward lean | `abs(left_sh.x − right_sh.x)` (normalised shoulder width) | increases (shoulders appear wider = closer to camera) |

### Scoring algorithm
- Start at 100
- Each triggered alert deducts: head_drop −35, forward_lean −25, shoulder_tilt −20, head_tilt −20
- Severity is partial (0.5–1.0 scale), so deductions are proportional
- Score is smoothed over a rolling 8-frame window (~0.25 s at 30 fps)

### Alert logic
- **Trigger:** score < 70 for ≥ 30 consecutive seconds
- **Cooldown:** 120 s minimum between alerts
- **Notification:** osascript native macOS notification with Ollama-generated tip
- **Fallback:** if Ollama is offline, a static per-signal tip is used

### Calibration
- User clicks "Calibrate", sits in good posture
- System averages 60 frames (~2 s) of landmarks
- Stores baseline feature vector; all subsequent readings are deviations from it

### File structure
```
posture-guard/
├── app.py                   # Flask app + background camera loop
├── notifications.py         # osascript wrapper
├── requirements.txt
├── core/
│   ├── pose_detector.py     # MediaPipe Pose wrapper
│   ├── posture_analyzer.py  # Feature extraction, scoring
│   └── alert_manager.py     # 30-s timer + cooldown
├── ai/
│   ├── coach.py             # Ollama tip generation
│   └── session_report.py    # HuggingFace zero-shot session categorisation
├── templates/
│   └── index.html           # Dashboard UI
└── static/
    └── js/
        └── dashboard.js     # Polling + Chart.js history graph
```

### Run command
```bash
pip install -r requirements.txt
python app.py
# Open http://127.0.0.1:5000
```

---

## Phase 2 — Native Menu Bar App (bonus)

### Additional tech
| Tech | Usage |
|------|-------|
| rumps | macOS menu bar app (status bar icon, menu, notification) |
| py2app | Packages the script as a standalone `.app` bundle |

### Architecture change
- `menu_bar_app.py` subclasses `rumps.App`
- Camera loop runs in a `daemon` background thread
- Menu items: Calibrate / Pause / Show Score / Quit
- Clicking Show Score opens a `rumps.alert()` dialog with current score + session stats
- `py2app` with `LSUIElement: True` hides the dock icon (true background app)

### Build command
```bash
pip install py2app
python setup.py py2app
# Output: dist/PostureGuard.app
```

---

## HuggingFace integration detail

At the end of each session (or every 10 minutes), the session is categorised using
`facebook/bart-large-mnli` zero-shot classification:

```
Posture session data → summary text → ZSC →
  labels: ["good posture session", "frequent slouching", "occasional alerts", "neck strain risk"]
→ best label shown on dashboard / in session report
```

Additionally, every Ollama-generated tip is passed through a sentiment classifier to
ensure it is positive/encouraging before displaying it. If the tip sentiment is NEGATIVE,
a fallback tip is used instead.

---

## Thresholds (tunable in posture_analyzer.py)

| Parameter | Default | Notes |
|-----------|---------|-------|
| HEAD_DROP_THRESHOLD | 0.12 | ratio of shoulder width |
| SHOULDER_TILT_THRESHOLD | 0.06 | ratio of shoulder width |
| EAR_TILT_THRESHOLD_DEG | 8.0 | degrees |
| FORWARD_LEAN_THRESHOLD | 0.07 | absolute shoulder-width increase |
| BAD_POSTURE_SCORE | 70 | below this = bad posture |
| ALERT_TRIGGER_SECONDS | 30 | continuous bad posture before alert |
| ALERT_COOLDOWN_SECONDS | 120 | minimum gap between alerts |
| CALIBRATION_FRAMES | 60 | frames averaged for baseline |
