"""
Demo server for screenshots and UI testing — no camera required.

Injects a realistic fake posture state so the dashboard renders fully.

Run:
    python scripts/mock_server.py
Then open http://127.0.0.1:5000
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
import threading
import math
import numpy as np
import cv2

# Patch the camera before importing app
import unittest.mock as mock

def _fake_camera_loop():
    """Replace the real camera loop with one that writes a fake annotated frame."""
    import app as a

    # Seed a plausible score history (last 5 min)
    now = time.time()
    for i in range(100, -1, -1):
        t = now - i * 3
        score = int(80 + 15 * math.sin(i / 10) - 5 * (i % 7 == 0))
        score = max(0, min(100, score))
        with a.state.lock:
            a.state.history.append({
                "time": round(t, 1),
                "score": score,
                "alerts": [] if score >= 70 else ["head_drop"],
            })

    with a.state.lock:
        a.state.calibrated = True
        a.state.score = 87
        a.state.alerts = []
        a.state.alert_count = 3
        a.state.last_tip = "Great posture right now! Keep your chin level and shoulders relaxed."
        a.state.ollama_ok = True

    # Produce a placeholder frame with pose skeleton drawn
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (30, 25, 20)   # dark background

    # Draw fake skeleton lines (shoulders, neck, head)
    cx, cy = 320, 240
    pts = {
        "nose":    (cx,      cy - 120),
        "l_ear":   (cx - 35, cy - 110),
        "r_ear":   (cx + 35, cy - 110),
        "l_sh":    (cx - 90, cy - 10),
        "r_sh":    (cx + 90, cy - 10),
        "l_hip":   (cx - 70, cy + 120),
        "r_hip":   (cx + 70, cy + 120),
    }
    connections = [
        ("l_ear", "r_ear"), ("l_ear", "nose"), ("r_ear", "nose"),
        ("l_sh", "r_sh"), ("l_sh", "l_ear"), ("r_sh", "r_ear"),
        ("l_sh", "l_hip"), ("r_sh", "r_hip"),
    ]
    for a_key, b_key in connections:
        cv2.line(frame, pts[a_key], pts[b_key], (0, 180, 255), 2)
    for pt in pts.values():
        cv2.circle(frame, pt, 5, (0, 255, 100), -1)

    cv2.rectangle(frame, (0, 0), (190, 56), (0, 0, 0), -1)
    cv2.putText(frame, "Score  87", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 200, 80), 2)

    with a.state.lock:
        a.state.current_frame = frame

    # Keep the frame alive
    while True:
        time.sleep(5)

if __name__ == "__main__":
    import app
    threading.Thread(target=_fake_camera_loop, daemon=True).start()
    print("Mock PostureGuard running → http://127.0.0.1:5000")
    app.app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
