import json
from pathlib import Path

import numpy as np

_BASELINE_PATH = Path.home() / ".config" / "postureguard" / "baseline.json"

# Landmark indices (mediapipe.solutions.pose.PoseLandmark values)
_NOSE = 0
_LEFT_EAR = 7
_RIGHT_EAR = 8
_LEFT_SHOULDER = 11
_RIGHT_SHOULDER = 12

# Deviation thresholds (all normalised relative to shoulder width unless noted)
HEAD_DROP_THRESHOLD = 0.12
SHOULDER_TILT_THRESHOLD = 0.06
EAR_TILT_THRESHOLD_DEG = 12.0  # raised from 8° — ear landmarks are noisy when hair covers ears
FORWARD_LEAN_THRESHOLD = 0.07

# Score deduction per fully-triggered alert
_DEDUCTIONS = {
    "head_drop": 35,
    "forward_lean": 25,
    "shoulder_tilt": 20,
    "head_tilt": 10,  # reduced — head tilt detection is inherently noisier than other signals
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
        Returns
        -------
        score : int  (0–100)
        alerts : list of dicts  {'type': str, 'msg': str, 'severity': float}
        """
        if self.baseline is None:
            return 100, []

        curr = self._features(landmarks)
        if curr is None:
            return 100, []

        alerts = []
        score = 100

        # 1. Head drop — nose descends toward shoulder line
        head_y_dev = curr["head_y"] - self.baseline["head_y"]
        if head_y_dev > HEAD_DROP_THRESHOLD:
            sev = min((head_y_dev - HEAD_DROP_THRESHOLD) / HEAD_DROP_THRESHOLD + 0.5, 1.0)
            alerts.append({"type": "head_drop", "msg": ALERT_LABELS["head_drop"], "severity": round(sev, 2)})
            score -= int(_DEDUCTIONS["head_drop"] * sev)

        # 2. Shoulder asymmetry — one shoulder higher than the other
        sh_dev = abs(curr["sh_tilt"] - self.baseline["sh_tilt"])
        if sh_dev > SHOULDER_TILT_THRESHOLD:
            sev = min((sh_dev - SHOULDER_TILT_THRESHOLD) / SHOULDER_TILT_THRESHOLD + 0.5, 1.0)
            alerts.append({"type": "shoulder_tilt", "msg": ALERT_LABELS["shoulder_tilt"], "severity": round(sev, 2)})
            score -= int(_DEDUCTIONS["shoulder_tilt"] * sev)

        # 3. Head tilt — only when both ears were clearly visible in this frame
        tilt_dev = abs(curr["ear_tilt"] - self.baseline["ear_tilt"])
        if curr["ears_visible"] and tilt_dev > EAR_TILT_THRESHOLD_DEG:
            sev = min((tilt_dev - EAR_TILT_THRESHOLD_DEG) / EAR_TILT_THRESHOLD_DEG + 0.5, 1.0)
            alerts.append({"type": "head_tilt", "msg": ALERT_LABELS["head_tilt"], "severity": round(sev, 2)})
            score -= int(_DEDUCTIONS["head_tilt"] * sev)

        # 4. Forward lean — shoulder width increases as person leans toward camera
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
        Extract 5 normalised posture features from a landmark list.
        Returns None if key landmarks have low visibility.
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
            sh_width = 0.01

        # Only compute ear tilt when both ears are clearly visible.
        # Hair, low light, or side-on angles push visibility below 0.5
        # and cause noisy/false head-tilt readings.
        ears_visible = l_ear.visibility >= 0.5 and r_ear.visibility >= 0.5
        ear_tilt = float(
            np.degrees(np.arctan2(r_ear.y - l_ear.y, r_ear.x - l_ear.x))
        ) if ears_visible else 0.0

        return {
            # Positive = nose is below shoulder midpoint (bad); normally negative
            "head_y":       (nose.y - sh_mid_y) / sh_width,
            # Signed tilt: left_sh.y - right_sh.y, normalised
            "sh_tilt":      (l_sh.y - r_sh.y) / sh_width,
            # Ear line angle in degrees relative to horizontal (0 when ears not visible)
            "ear_tilt":     ear_tilt,
            # Flag so the analyzer can skip the check when ears weren't detected
            "ears_visible": float(ears_visible),
            # Shoulder width in normalised image coordinates (larger = closer to camera)
            "sh_width":     sh_width,
            # Horizontal head centering (not alerted on, but stored for future use)
            "head_x":       (nose.x - sh_mid_x) / sh_width,
        }
