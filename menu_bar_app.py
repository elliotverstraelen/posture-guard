"""
PostureGuard — native macOS menu bar app.

Run (dev):
    .venv/bin/python menu_bar_app.py

Install via Homebrew:
    brew tap elliotverstraelen/postureguard && brew install postureguard
"""

import json
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import rumps

from ai.coach import get_coaching_tip
from core.alert_manager import AlertManager
from core.pose_detector import PoseDetector
from core.posture_analyzer import PostureAnalyzer
import core.snapshot_store as snapshots
from ui.settings_window import SettingsWindow
from ui.live_view_window import LiveViewWindow
from ui.label_window import LabelWindow

VERSION = "1.4.0"
DASHBOARD_URL = "http://127.0.0.1:5000"
CALIBRATION_FRAMES = 60
SMOOTH_WINDOW = 8
SNAPSHOT_MIN_INTERVAL = 120   # minimum gap between snapshots (seconds)
SNAPSHOT_STABLE_SECS  = 15    # pose must be held this long before saving

# A head-drop deviation this large (vs. baseline) signals phone-looking posture
PHONE_HEAD_DROP_THRESHOLD = 0.28


# ── Settings ──────────────────────────────────────────────────────────────────

_SETTINGS_PATH = Path.home() / ".config" / "postureguard" / "settings.json"
_DEFAULTS: dict = {
    "camera_index":             0,
    "use_all_cameras":          False,
    "phone_detection_enabled":  False,
    "phone_alert_minutes":      10,
    "alert_threshold_seconds":  30,
}


class Settings:
    """Persistent preferences stored in ~/.config/postureguard/settings.json."""

    def __init__(self):
        self._data = dict(_DEFAULTS)
        if _SETTINGS_PATH.exists():
            try:
                with open(_SETTINGS_PATH) as f:
                    saved = json.load(f)
                self._data.update({k: saved[k] for k in _DEFAULTS if k in saved})
            except Exception:
                pass

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(name)

    def set(self, key: str, value):
        self._data[key] = value
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_SETTINGS_PATH, "w") as f:
            json.dump(self._data, f, indent=2)


# ── Camera enumeration ────────────────────────────────────────────────────────

def _detect_cameras() -> list:
    """Return [(cv_index, label), ...] for every camera that can be opened."""
    names = []
    try:
        raw = subprocess.check_output(
            ["system_profiler", "SPCameraDataType"], text=True, timeout=5
        )
        skip_prefixes = ("Unique ID", "Model ID", "Serial", "Revision",
                         "Location", "Speed", "Cameras", "Camera Data")
        for line in raw.splitlines():
            s = line.strip()
            if s.endswith(":") and not any(s.startswith(p) for p in skip_prefixes):
                names.append(s[:-1])
    except Exception:
        pass

    result, name_idx = [], 0
    for i in range(6):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cap.release()
            label = names[name_idx] if name_idx < len(names) else f"Camera {i}"
            result.append((i, label))
            name_idx += 1
    return result


# ── Camera pre-flight ─────────────────────────────────────────────────────────

def _preflight_camera(index: int = 0) -> bool:
    """Open & immediately close the camera on the main thread to trigger the macOS permission dialog."""
    cap = cv2.VideoCapture(index)
    ok = cap.isOpened()
    cap.release()
    if not ok:
        rumps.alert(
            title="Camera not accessible",
            message=(
                "PostureGuard needs camera access.\n\n"
                "Go to  System Settings → Privacy & Security → Camera\n"
                "and enable PostureGuard (or Terminal), then restart."
            ),
        )
    return ok


# ── App ───────────────────────────────────────────────────────────────────────

class PostureGuard(rumps.App):
    """
    macOS menu bar app.  State machine: idle → calibrating → monitoring ⇄ paused
    """

    def __init__(self):
        super().__init__("🧍", quit_button=None)

        self._settings = Settings()
        self._cameras  = _detect_cameras()

        _preflight_camera(self._settings.camera_index)

        # ── Shared state (main thread + camera thread) ────────────────────────
        self._lock              = threading.Lock()
        self._score             = 100
        self._alerts            = []
        self._calibrated        = False
        self._calibrating       = False
        self._paused            = False
        self._alert_count       = 0
        self._session_start     = time.time()
        self._last_tip          = ""
        self._camera_restart    = False
        self._analyzer          = None   # set by camera loop; shared with live view

        # Phone detection (camera thread only — no lock needed)
        self._phone_bow_since   = None
        self._phone_alerted     = False

        self._rebuild_menu()
        threading.Thread(target=self._camera_loop, daemon=True).start()
        rumps.Timer(self._on_tick, 3).start()

    # ── Posture actions ───────────────────────────────────────────────────────

    def _do_calibrate(self, _=None):
        with self._lock:
            if self._calibrating:
                return
            self._calibrating = True
            self._calibrated  = False
        self.title = "📐"
        self._rebuild_menu()
        rumps.notification(
            title="PostureGuard — Calibrating",
            subtitle="",
            message=(
                "Sit in your normal working position and hold still.\n"
                "Look at the screen you actually work on — not the camera."
            ),
        )

    def _do_pause_toggle(self, _=None):
        with self._lock:
            self._paused = not self._paused
            paused = self._paused
        self.title = "⏸" if paused else self._title_for_score()
        self._rebuild_menu()

    def _do_show_summary(self, _=None):
        with self._lock:
            score       = self._score
            alerts      = list(self._alerts)
            count       = self._alert_count
            mins        = round((time.time() - self._session_start) / 60, 1)
            last_tip    = self._last_tip
            calibrated  = self._calibrated

        if not calibrated:
            rumps.alert(title="PostureGuard",
                        message="Calibrate first — click '🎯 Calibrate now'.")
            return

        issues = "\n".join(f"  • {a['msg']}" for a in alerts) or "  ✓ None right now"
        tip    = f"\n\nLast coaching tip:\n  {last_tip}" if last_tip else ""
        rumps.alert(
            title=f"Score: {score} / 100",
            message=(
                f"Session:      {mins} min\n"
                f"Alerts fired: {count}\n\n"
                f"Active issues:\n{issues}{tip}"
            ),
        )

    def _do_open_dashboard(self, _=None):
        subprocess.Popen(["open", DASHBOARD_URL])

    def _do_quit(self, _=None):
        rumps.quit_application()

    def _do_open_live_view(self, _=None):
        LiveViewWindow.open(self._cameras, self._analyzer or PostureAnalyzer())

    def _do_open_settings(self, _=None):
        def on_camera_change():
            with self._lock:
                self._camera_restart = True
        SettingsWindow.open(
            self._settings,
            self._cameras,
            on_camera_change    = on_camera_change,
            label_poses_fn      = self._do_label_poses,
            apply_labels_fn     = self._do_apply_labels,
            stats_fn            = self._do_show_label_stats,
        )

    # ── Calibration Studio (called from the Settings window) ──────────────────

    def _do_label_poses(self, _=None):
        all_entries = snapshots.all_entries()
        unlabeled   = [(i, e) for i, e in enumerate(all_entries) if e["label"] is None]

        if not unlabeled:
            rumps.alert(
                title="Calibration Studio",
                message=(
                    "No unlabeled snapshots yet.\n\n"
                    "PostureGuard saves a snapshot when you hold a pose for "
                    f"{SNAPSHOT_STABLE_SECS}+ seconds. Come back after a session."
                ),
            )
            return

        def on_complete(labeled_count):
            if labeled_count:
                rumps.notification(
                    title="Calibration Studio",
                    subtitle="",
                    message=f"Labeled {labeled_count} pose(s). Use '🔬 Improve model' when you have 10+.",
                )

        LabelWindow.open(unlabeled[-10:], on_complete=on_complete)

    def _do_apply_labels(self, _=None):
        counts        = snapshots.labeled_counts()
        total_labeled = counts["good"] + counts["bad"]

        if total_labeled < 10:
            rumps.alert(
                title="Not enough data yet",
                message=f"You have {total_labeled} labeled pose(s). Label at least 10 first.",
            )
            return

        adjustments = snapshots.compute_threshold_adjustments()
        if not adjustments:
            rumps.alert(title="No adjustments needed",
                        message="The current thresholds already fit your labeled poses well.")
            return

        from core.posture_analyzer import (
            HEAD_DROP_THRESHOLD, SHOULDER_TILT_THRESHOLD,
            EAR_TILT_THRESHOLD_DEG, FORWARD_LEAN_THRESHOLD,
        )
        baseline = {
            "head_drop": HEAD_DROP_THRESHOLD, "forward_lean": FORWARD_LEAN_THRESHOLD,
            "shoulder_tilt": SHOULDER_TILT_THRESHOLD, "head_tilt": EAR_TILT_THRESHOLD_DEG,
        }
        lines = ["Suggested threshold changes:\n"]
        for k, mult in adjustments.items():
            old = baseline.get(k)
            if old:
                new = round(old * mult, 4)
                lines.append(f"  {k}: {old} → {new}  ({'looser ↑' if mult > 1 else 'stricter ↓'})")
        lines += ["", f"Based on {total_labeled} labeled poses.", "", "Apply?"]

        if rumps.alert(title="Apply label adjustments",
                       message="\n".join(lines), ok="Apply", cancel="Cancel") == 1:
            self._settings.set("threshold_multipliers", adjustments)
            rumps.alert(title="Applied ✓",
                        message="Saved. Re-calibrate for them to take effect.")

    def _do_show_label_stats(self, _=None):
        c = snapshots.labeled_counts()
        rumps.alert(
            title="Pose label statistics",
            message=(
                f"Total snapshots:  {sum(c.values())}\n"
                f"  ✅ Good:         {c['good']}\n"
                f"  ❌ Bad:          {c['bad']}\n"
                f"  ❓ Unsure:       {c['unsure']}\n"
                f"  ○  Unlabeled:   {c['unlabeled']}"
            ),
        )

    def _rebuild_menu(self):
        """Reconstruct menu to match current state. Called every 3 s by the timer."""
        with self._lock:
            calibrated  = self._calibrated
            calibrating = self._calibrating
            paused      = self._paused
            score       = self._score
            alerts      = list(self._alerts)
            count       = self._alert_count
            mins        = int((time.time() - self._session_start) / 60)

        items = []

        # ── Header ────────────────────────────────────────────────────────────
        items += [rumps.MenuItem(f"PostureGuard  v{VERSION}"), None]

        # ── State section ─────────────────────────────────────────────────────
        if calibrating:
            items += [
                rumps.MenuItem("📐  Calibrating…  sit upright & stay still"),
                None,
            ]

        elif not calibrated:
            items += [
                rumps.MenuItem("⚪  Not calibrated yet"),
                rumps.MenuItem("    Sit upright and click Calibrate to start."),
                None,
                rumps.MenuItem("🎯  Calibrate now", callback=self._do_calibrate),
                None,
            ]

        elif paused:
            items += [
                rumps.MenuItem("⏸  Monitoring paused"),
                rumps.MenuItem(f"    Session: {mins} min  ·  {count} alert(s)"),
                None,
                rumps.MenuItem("▶  Resume monitoring",  callback=self._do_pause_toggle),
                None,
                rumps.MenuItem("📋  Session Summary",   callback=self._do_show_summary),
                rumps.MenuItem("📷  Live View",         callback=self._do_open_live_view),
                rumps.MenuItem("🌐  Open Dashboard",    callback=self._do_open_dashboard),
                None,
            ]

        else:
            icon  = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
            label = "Good posture" if score >= 80 else "Slouching a bit" if score >= 60 else "Poor posture"
            items += [
                rumps.MenuItem(f"{icon}  {label}  —  {score} / 100"),
                rumps.MenuItem(f"    Session: {mins} min  ·  {count} alert(s)"),
            ]
            if alerts:
                items.append(None)
                for a in alerts[:3]:
                    items.append(rumps.MenuItem(f"   ⚠  {a['msg']}"))
            items += [
                None,
                rumps.MenuItem("🎯  Re-calibrate",     callback=self._do_calibrate),
                rumps.MenuItem("⏸  Pause monitoring",  callback=self._do_pause_toggle),
                None,
                rumps.MenuItem("📋  Session Summary",  callback=self._do_show_summary),
                rumps.MenuItem("📷  Live View",        callback=self._do_open_live_view),
                rumps.MenuItem("🌐  Open Dashboard",   callback=self._do_open_dashboard),
                None,
            ]

        # ── Settings + Quit ───────────────────────────────────────────────────
        items.append(rumps.MenuItem("⚙️  Settings…", callback=self._do_open_settings))
        items.append(None)
        items.append(rumps.MenuItem("✕  Quit PostureGuard", callback=self._do_quit))

        self.menu.clear()
        self.menu = items

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _on_tick(self, _):
        with self._lock:
            calibrating = self._calibrating
            calibrated  = self._calibrated
            paused      = self._paused
        if calibrating:
            self.title = "📐"
        elif paused:
            self.title = "⏸"
        elif calibrated:
            self.title = self._title_for_score()
        else:
            self.title = "🧍"
        self._rebuild_menu()

    def _title_for_score(self) -> str:
        with self._lock:
            score = self._score
        icon = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
        return f"{icon} {score}"

    # ── Camera loop ───────────────────────────────────────────────────────────

    def _open_cameras(self) -> list:
        s = self._settings
        indices = [s.camera_index]
        if s.use_all_cameras:
            indices = list({s.camera_index} | {cv_idx for cv_idx, _ in self._cameras})
        caps = []
        for i in sorted(set(indices)):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                caps.append(cap)
        return caps

    def _camera_loop(self):
        """Background thread: reads frames, runs pose detection, updates shared state."""
        detector   = PoseDetector()
        analyzer   = PostureAnalyzer()
        self._analyzer = analyzer

        # If a saved baseline exists, restore calibrated state immediately
        if analyzer.baseline:
            with self._lock:
                self._calibrated = True
        alert_mgr  = AlertManager(
            trigger_seconds=self._settings.alert_threshold_seconds
        )
        smooth_buf         = deque(maxlen=SMOOTH_WINDOW)
        cal_count          = 0
        last_snapshot      = time.time()
        stable_score_ref   = 100      # score when current stable window started
        stable_since       = None     # time when score became stable

        caps = self._open_cameras()
        if not caps:
            rumps.notification("PostureGuard", "Camera Error",
                               "Cannot open camera. Grant access and restart.")
            return

        while True:
            # Reload cameras if settings changed
            with self._lock:
                do_restart = self._camera_restart
            if do_restart:
                for c in caps:
                    c.release()
                with self._lock:
                    self._camera_restart = False
                    # Also recreate alert manager with updated threshold
                    alert_mgr = AlertManager(
                        trigger_seconds=self._settings.alert_threshold_seconds
                    )
                caps = self._open_cameras()
                if not caps:
                    time.sleep(1)
                    continue

            with self._lock:
                paused      = self._paused
                calibrating = self._calibrating
                calibrated  = self._calibrated

            if paused:
                time.sleep(0.5)
                continue

            # Read all cameras; if calibrated pick the one with the highest
            # posture score so a badly-angled camera doesn't drag the reading down
            candidates = []
            for cap in caps:
                ret, frame = cap.read()
                if not ret:
                    continue
                frame = cv2.flip(frame, 1)
                lm, _ = detector.process(frame)
                if lm:
                    candidates.append((lm, frame))

            if not candidates:
                time.sleep(0.033)
                continue

            if calibrated and analyzer.baseline and len(candidates) > 1:
                landmarks, current_frame = max(
                    candidates, key=lambda c: analyzer.analyze(c[0])[0]
                )
            else:
                landmarks, current_frame = candidates[0]

            if not landmarks:
                time.sleep(0.033)
                continue

            if calibrating:
                cal_count = self._calibrate_frame(analyzer, landmarks, cal_count)
            elif calibrated:
                self._analyse_frame(analyzer, alert_mgr, smooth_buf, landmarks)

                # Stable-pose snapshot for Calibration Studio:
                # only save when score hasn't jumped more than 8 pts for 15+ seconds
                now = time.time()
                with self._lock:
                    cur_score  = self._score
                    cur_alerts = list(self._alerts)

                if abs(cur_score - stable_score_ref) > 8:
                    stable_score_ref = cur_score
                    stable_since     = now
                elif stable_since is None:
                    stable_since = now

                stable_secs = now - stable_since if stable_since else 0
                if (stable_secs >= SNAPSHOT_STABLE_SECS
                        and now - last_snapshot >= SNAPSHOT_MIN_INTERVAL):
                    feats = analyzer._features(landmarks)
                    if feats:
                        snapshots.save_snapshot(cur_score, cur_alerts, feats,
                                                frame=current_frame)
                    last_snapshot = now

            time.sleep(0.033)

        for c in caps:
            c.release()
        detector.close()

    def _calibrate_frame(self, analyzer, landmarks, cal_count: int) -> int:
        analyzer.add_calibration_frame(landmarks)
        cal_count += 1
        if cal_count >= CALIBRATION_FRAMES:
            analyzer.commit_calibration()
            with self._lock:
                self._calibrating = False
                self._calibrated  = True
            rumps.notification(
                title="PostureGuard",
                subtitle="Calibration complete ✓",
                message="Baseline saved. I'll alert you when you slouch.",
            )
            return 0
        return cal_count

    def _analyse_frame(self, analyzer, alert_mgr, smooth_buf, landmarks):
        score, alerts = analyzer.analyze(landmarks)
        smooth_buf.append(score)
        smoothed = int(sum(smooth_buf) / len(smooth_buf))

        with self._lock:
            self._score  = smoothed
            self._alerts = alerts

        # Posture alerts
        result = alert_mgr.update(smoothed, alerts)
        if result.warn:
            tip = get_coaching_tip(alerts, result.duration)
            with self._lock:
                self._last_tip     = tip
                self._alert_count += 1
            rumps.notification(
                title="PostureGuard 🧍",
                subtitle="Posture check",
                message=tip,
            )
        elif result.restored:
            rumps.notification(
                title="PostureGuard 🧍",
                subtitle="Posture restored ✓",
                message="Good job — back on track! 💪",
            )

        # Phone posture detection
        if self._settings.phone_detection_enabled:
            self._check_phone_posture(analyzer, landmarks)

    def _check_phone_posture(self, analyzer, landmarks):
        if analyzer.baseline is None:
            return
        feats = analyzer._features(landmarks)
        if feats is None:
            self._phone_bow_since = None
            self._phone_alerted   = False
            return

        head_dev = feats["head_y"] - analyzer.baseline["head_y"]

        if head_dev > PHONE_HEAD_DROP_THRESHOLD:
            if self._phone_bow_since is None:
                self._phone_bow_since = time.time()
                self._phone_alerted   = False

            elapsed_min = (time.time() - self._phone_bow_since) / 60
            if elapsed_min >= self._settings.phone_alert_minutes and not self._phone_alerted:
                self._phone_alerted = True
                rumps.notification(
                    title="PostureGuard 📱",
                    subtitle="Phone check",
                    message=(
                        f"You've been looking down for {int(elapsed_min)} min. "
                        "Put the phone down and sit up! 🙏"
                    ),
                )
        else:
            self._phone_bow_since = None
            self._phone_alerted   = False


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    PostureGuard().run()


if __name__ == "__main__":
    main()
