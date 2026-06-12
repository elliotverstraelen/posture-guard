"""
PostureGuard — Phase 1
Flask web app with a background camera / detection loop.

Run:
    python app.py
Then open http://127.0.0.1:5000
"""

import threading
import time
from collections import deque

import cv2
from flask import Flask, Response, jsonify, render_template

from ai.coach import check_ollama_available, get_coaching_tip
from ai.session_report import classify_session
from core.alert_manager import AlertManager
from core.pose_detector import PoseDetector
from core.posture_analyzer import PostureAnalyzer
from notifications import send_notification

# ── Constants ──────────────────────────────────────────────────────────────────

CALIBRATION_FRAMES = 60    # frames averaged to build the good-posture baseline (~2 s)
SMOOTH_WINDOW      = 8     # frames averaged when reporting the live posture score
HISTORY_INTERVAL   = 2.0   # seconds between entries in the history chart
HISTORY_MAXLEN     = 150   # entries kept (~5 min of history)

# ── Flask app ──────────────────────────────────────────────────────────────────

app = Flask(__name__)

# ── Shared state ───────────────────────────────────────────────────────────────

class AppState:
    """
    All mutable data shared between the camera thread and Flask routes.
    Every access must hold `self.lock`.
    """
    def __init__(self):
        self.lock          = threading.Lock()
        self.score         = 100
        self.alerts        = []
        self.calibrated    = False
        self.calibrating   = False
        self.cal_remaining = 0
        self.history       = deque(maxlen=HISTORY_MAXLEN)
        self.current_frame = None
        self.last_tip      = ""
        self.alert_count   = 0
        self.session_start = time.time()
        self.camera_error  = ""   # non-empty string = camera failed to open
        self.ollama_ok     = False
        self.session_label = ""
        self.running       = True


state = AppState()


# ── Camera loop ────────────────────────────────────────────────────────────────

def _camera_loop():
    """
    Runs in a daemon thread.
    Reads frames → runs pose detection → updates `state`.
    """
    detector  = PoseDetector()
    analyzer  = PostureAnalyzer()
    alert_mgr = AlertManager()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        msg = (
            "Camera permission denied or no camera found.\n"
            "Fix: run  tccutil reset Camera com.apple.Terminal  then restart."
        )
        print(f"[PostureGuard] ERROR: {msg}")
        with state.lock:
            state.camera_error = msg
        return

    smooth_buf    = deque(maxlen=SMOOTH_WINDOW)
    last_history  = 0.0
    cal_count     = 0

    with state.lock:
        state.ollama_ok = check_ollama_available()

    while state.running:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        frame = cv2.flip(frame, 1)          # mirror so left/right feel natural
        landmarks, annotated = detector.process(frame)

        # Read volatile flags once under lock to avoid torn reads
        with state.lock:
            calibrating = state.calibrating
            calibrated  = state.calibrated

        if landmarks:
            if calibrating:
                annotated, cal_count = _do_calibration(
                    landmarks, annotated, analyzer, cal_count
                )
            elif calibrated:
                annotated, last_history = _do_monitoring(
                    landmarks, annotated, analyzer, alert_mgr,
                    smooth_buf, last_history
                )
            else:
                _draw_text(annotated, "Click  Calibrate  to begin", (255, 220, 0))
        else:
            _draw_text(annotated, "No pose detected — check lighting", (80, 80, 255))

        with state.lock:
            state.current_frame = annotated

        time.sleep(0.033)  # ~30 fps

    cap.release()
    detector.close()


def _do_calibration(landmarks, annotated, analyzer, cal_count):
    """Collect one calibration frame. Commits baseline when enough frames are gathered."""
    analyzer.add_calibration_frame(landmarks)
    cal_count += 1
    remaining = max(0, CALIBRATION_FRAMES - cal_count)

    with state.lock:
        state.cal_remaining = remaining

    _draw_calibration_overlay(annotated, remaining)

    if cal_count >= CALIBRATION_FRAMES:
        analyzer.commit_calibration()
        with state.lock:
            state.calibrating   = False
            state.calibrated    = True
            state.cal_remaining = 0
        cal_count = 0

    return annotated, cal_count


def _do_monitoring(landmarks, annotated, analyzer, alert_mgr, smooth_buf, last_history):
    """Analyse posture, update state, fire notifications when needed."""
    score, alerts = analyzer.analyze(landmarks)
    smooth_buf.append(score)
    smoothed = int(sum(smooth_buf) / len(smooth_buf))

    with state.lock:
        state.score  = smoothed
        state.alerts = alerts

    # Append one history entry every HISTORY_INTERVAL seconds
    now = time.time()
    if now - last_history >= HISTORY_INTERVAL:
        with state.lock:
            state.history.append({
                "time":   round(now, 1),
                "score":  smoothed,
                "alerts": [a["type"] for a in alerts],
            })
        last_history = now

    # Notifications
    result = alert_mgr.update(smoothed, alerts)
    if result.warn:
        tip = get_coaching_tip(alerts, result.duration)
        send_notification("PostureGuard 🧍", tip)
        with state.lock:
            state.last_tip    = tip
            state.alert_count += 1
    elif result.restored:
        send_notification("PostureGuard 🧍", "Good job — posture back on track! 💪")

    _draw_score_overlay(annotated, smoothed, alerts)
    return annotated, last_history


# ── Frame drawing helpers ──────────────────────────────────────────────────────

def _draw_text(frame, text, color):
    cv2.putText(frame, text, (12, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)


def _draw_calibration_overlay(frame, remaining):
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], 80), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    cv2.putText(frame, f"Calibrating… {remaining} frames left",
                (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cv2.putText(frame, "Sit in your best upright posture",
                (12, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 200), 1)


def _draw_score_overlay(frame, score, alerts):
    color = (0, 200, 80) if score >= 80 else (0, 165, 255) if score >= 60 else (0, 60, 220)
    cv2.rectangle(frame, (0, 0), (190, 56), (0, 0, 0), -1)
    cv2.putText(frame, f"Score  {score}", (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
    y = 78
    for alert in alerts:
        cv2.putText(frame, f"  {alert['msg']}", (8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (80, 120, 255), 1)
        y += 20


# ── MJPEG stream ───────────────────────────────────────────────────────────────

def _generate_frames():
    while True:
        with state.lock:
            frame = state.current_frame
        if frame is None:
            time.sleep(0.05)
            continue
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 78])
        if ok:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
        time.sleep(0.033)


# ── Flask routes ───────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/video_feed")
def video_feed():
    return Response(
        _generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/status")
def api_status():
    with state.lock:
        return jsonify({
            "score":           state.score,
            "calibrated":      state.calibrated,
            "calibrating":     state.calibrating,
            "cal_remaining":   state.cal_remaining,
            "alerts":          [{"type": a["type"], "msg": a["msg"]} for a in state.alerts],
            "last_tip":        state.last_tip,
            "alert_count":     state.alert_count,
            "session_minutes": round((time.time() - state.session_start) / 60, 1),
            "ollama_ok":       state.ollama_ok,
            "session_label":   state.session_label,
            "camera_error":    state.camera_error,
        })


@app.post("/api/calibrate")
def api_calibrate():
    with state.lock:
        if state.calibrating:
            return jsonify({"error": "Already calibrating"}), 400
        state.calibrating   = True
        state.calibrated    = False
        state.cal_remaining = CALIBRATION_FRAMES
    return jsonify({"ok": True})


@app.get("/api/history")
def api_history():
    with state.lock:
        return jsonify(list(state.history))


@app.post("/api/session_report")
def api_session_report():
    """Trigger HuggingFace session classification asynchronously."""
    with state.lock:
        history_snapshot = list(state.history)

    def _run():
        report = classify_session(history_snapshot)
        with state.lock:
            state.session_label = report["label"]

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


# ── Camera permission pre-flight ───────────────────────────────────────────────

def _preflight_camera() -> bool:
    """
    macOS requires the camera permission dialog to appear on the main thread.
    Open and immediately release the camera here (before the background thread
    starts) so the system shows the 'Terminal wants to use the camera' dialog.

    Returns True if the camera is accessible, False if permission was denied.
    """
    import platform
    if platform.system() != "Darwin":
        return True

    cap = cv2.VideoCapture(0)
    ok = cap.isOpened()
    cap.release()

    if not ok:
        print(
            "\n[PostureGuard] Camera not accessible.\n"
            "  1. Go to  System Settings → Privacy & Security → Camera\n"
            "  2. Enable  Terminal  (or your Python app)\n"
            "  3. Restart the app.\n"
            "  Or run:  tccutil reset Camera com.apple.Terminal\n"
        )
    return ok


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _preflight_camera()   # must happen on the main thread to trigger macOS permission dialog
    threading.Thread(target=_camera_loop, daemon=True).start()
    print("PostureGuard running → http://127.0.0.1:5000")
    # use_reloader=False is required — Flask's reloader would start a second camera thread
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
