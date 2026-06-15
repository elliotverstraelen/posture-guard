"""
Posture analysis: feature extraction, personal calibration, and deviation scoring.

Flow: extract 5 geometric features from MediaPipe landmarks → compare against a
personal baseline built during calibration → compute a 0-100 score based on how
far each feature deviates from that baseline.

All positional features are normalised by shoulder width so the readings don't
shift when the user sits closer or further from the camera.
"""

import json
from pathlib import Path

import numpy as np

_BASELINE_PATH = Path.home() / ".config" / "postureguard" / "baseline.json"

# MediaPipe Pose landmark indices (from mediapipe.solutions.pose.PoseLandmark)
_NOSE = 0
_LEFT_EAR = 7
_RIGHT_EAR = 8
_LEFT_SHOULDER = 11
_RIGHT_SHOULDER = 12

# Deviation thresholds — all normalised relative to shoulder width except ear_tilt (degrees)
HEAD_DROP_THRESHOLD     = 0.12   # nose descends toward shoulder midpoint
SHOULDER_TILT_THRESHOLD = 0.06   # vertical asymmetry between left and right shoulder
EAR_TILT_THRESHOLD_DEG  = 12.0   # angle of the ear line vs horizontal; raised from 8° because
                                  # hair and low-visibility frames make ear landmarks noisy
FORWARD_LEAN_THRESHOLD  = 0.07   # shoulder width increases as user leans toward camera

# Score deductions per fully-triggered alert (scaled by severity 0.5–1.0)
_DEDUCTIONS = {
    "head_drop":     35,
    "forward_lean":  25,
    "shoulder_tilt": 20,
    "head_tilt":     10,  # lower weight — ear-landmark noise makes this signal less reliable
}

# Human-readable labels for the UI / coach
ALERT_LABELS = {
    "head_drop": "Head dropping forward",
    "forward_lean": "Leaning too close to screen",
    "shoulder_tilt": "Uneven shoulders",
    "head_tilt": "Head tilted sideways",
}


class PostureAnalyzer:
    def __init__(self):
        self._cal_buffer = []
        self.baseline    = self._load_baseline()   # restore saved calibration if it exists

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def add_calibration_frame(self, landmarks):
        feats = self._features(landmarks)
        if feats is not None:
            self._cal_buffer.append(feats)

    def commit_calibration(self):
        if not self._cal_buffer:
            return False
        keys = self._cal_buffer[0].keys()
        self.baseline = {
            k: float(np.mean([f[k] for f in self._cal_buffer])) for k in keys
        }
        self._cal_buffer = []
        self._save_baseline()
        return True

    def calibrated(self):
        return self.baseline is not None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_baseline(self):
        _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_BASELINE_PATH, "w") as f:
            json.dump(self.baseline, f, indent=2)

    @staticmethod
    def _load_baseline():
        if _BASELINE_PATH.exists():
            try:
                with open(_BASELINE_PATH) as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze(self, landmarks):
        """
        Score the current frame against the personal baseline.

        Severity formula: clamp((deviation - threshold) / threshold + 0.5, 0.5, 1.0)
        Crossing the threshold = 0.5 severity; double the threshold = 1.0.
        This gives a smooth gradient so minor deviations score lightly.

        Returns (score: int 0-100, alerts: list of dicts)
        """
        if self.baseline is None:
            return 100, []

        curr = self._features(landmarks)
        if curr is None:
            return 100, []

        alerts = []
        score = 100

        # 1. Head drop — nose descends toward shoulder line (bad posture = positive delta)
        head_y_dev = curr["head_y"] - self.baseline["head_y"]
        if head_y_dev > HEAD_DROP_THRESHOLD:
            sev = min((head_y_dev - HEAD_DROP_THRESHOLD) / HEAD_DROP_THRESHOLD + 0.5, 1.0)
            alerts.append({"type": "head_drop", "msg": ALERT_LABELS["head_drop"], "severity": round(sev, 2)})
            score -= int(_DEDUCTIONS["head_drop"] * sev)

        # 2. Shoulder asymmetry — absolute difference so either shoulder can be higher
        sh_dev = abs(curr["sh_tilt"] - self.baseline["sh_tilt"])
        if sh_dev > SHOULDER_TILT_THRESHOLD:
            sev = min((sh_dev - SHOULDER_TILT_THRESHOLD) / SHOULDER_TILT_THRESHOLD + 0.5, 1.0)
            alerts.append({"type": "shoulder_tilt", "msg": ALERT_LABELS["shoulder_tilt"], "severity": round(sev, 2)})
            score -= int(_DEDUCTIONS["shoulder_tilt"] * sev)

        # 3. Head tilt — skipped when ears aren't clearly visible (hair/angle noise)
        tilt_dev = abs(curr["ear_tilt"] - self.baseline["ear_tilt"])
        if curr["ears_visible"] and tilt_dev > EAR_TILT_THRESHOLD_DEG:
            sev = min((tilt_dev - EAR_TILT_THRESHOLD_DEG) / EAR_TILT_THRESHOLD_DEG + 0.5, 1.0)
            alerts.append({"type": "head_tilt", "msg": ALERT_LABELS["head_tilt"], "severity": round(sev, 2)})
            score -= int(_DEDUCTIONS["head_tilt"] * sev)

        # 4. Forward lean — shoulders appear wider when user moves closer to the camera
        lean_dev = curr["sh_width"] - self.baseline["sh_width"]
        if lean_dev > FORWARD_LEAN_THRESHOLD:
            sev = min((lean_dev - FORWARD_LEAN_THRESHOLD) / FORWARD_LEAN_THRESHOLD + 0.5, 1.0)
            alerts.append({"type": "forward_lean", "msg": ALERT_LABELS["forward_lean"], "severity": round(sev, 2)})
            score -= int(_DEDUCTIONS["forward_lean"] * sev)

        return max(0, score), alerts

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------

    def _features(self, lm):
        """
        Extract six posture features from a MediaPipe landmark list.
        Returns None if shoulder landmarks have low visibility (person out of frame).
        """
        l_sh = lm[_LEFT_SHOULDER]
        r_sh = lm[_RIGHT_SHOULDER]

        if l_sh.visibility < 0.5 or r_sh.visibility < 0.5:
            return None

        nose  = lm[_NOSE]
        l_ear = lm[_LEFT_EAR]
        r_ear = lm[_RIGHT_EAR]

        sh_mid_x = (l_sh.x + r_sh.x) / 2
        sh_mid_y = (l_sh.y + r_sh.y) / 2
        sh_width = abs(l_sh.x - r_sh.x)
        if sh_width < 0.01:
            sh_width = 0.01   # guard against near-zero when user is side-on

        # Ear tilt is only meaningful when both ears are clearly visible.
        # Hair and lateral head rotation push the visibility score below 0.5,
        # causing the landmark coordinates to drift — giving false head-tilt readings.
        ears_visible = l_ear.visibility >= 0.5 and r_ear.visibility >= 0.5
        ear_tilt = float(
            np.degrees(np.arctan2(r_ear.y - l_ear.y, r_ear.x - l_ear.x))
        ) if ears_visible else 0.0

        return {
            # positive = nose below shoulder midpoint (head dropping forward)
            "head_y":       (nose.y - sh_mid_y) / sh_width,
            # non-zero = one shoulder higher than the other
            "sh_tilt":      (l_sh.y - r_sh.y) / sh_width,
            # angle of the ear-to-ear line in degrees; 0 = level
            "ear_tilt":     ear_tilt,
            # float so it can be averaged across calibration frames
            "ears_visible": float(ears_visible),
            # increases when user leans toward camera
            "sh_width":     sh_width,
            # lateral head offset; stored for future use, not alerted on yet
            "head_x":       (nose.x - sh_mid_x) / sh_width,
        }
