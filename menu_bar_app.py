"""
PostureGuard — Phase 2 (bonus)
Native macOS menu bar app using rumps.

The app lives in the menu bar (no dock icon).
The menu updates every 3 seconds to reflect the current monitoring state.

Run:
    pip install rumps
    python menu_bar_app.py

Package as a standalone .app:
    pip install py2app
    python setup.py py2app
    open dist/PostureGuard.app
"""

import threading
import time
from collections import deque

import cv2
import rumps

from ai.coach import get_coaching_tip
from core.alert_manager import AlertManager
from core.pose_detector import PoseDetector
from core.posture_analyzer import PostureAnalyzer

# ── Constants ──────────────────────────────────────────────────────────────────

CALIBRATION_FRAMES = 60
SMOOTH_WINDOW      = 8


# ── App ────────────────────────────────────────────────────────────────────────

class PostureGuard(rumps.App):
    """
    macOS menu bar app that monitors posture in a background thread.

    State machine
    -------------
    idle       → user has not calibrated yet
    calibrating → collecting baseline frames
    monitoring  → live posture scoring is active
    paused      → camera loop is sleeping; no analysis or alerts
    """

    def __init__(self):
        super().__init__("🧍", quit_button=None)

        # ── Shared state (accessed by both main thread and camera thread) ──
        self._lock            = threading.Lock()
        self._score           = 100
        self._alerts          = []
        self._calibrated      = False
        self._calibrating     = False
        self._paused          = False
        self._alert_count     = 0
        self._session_start   = time.time()
        self._last_tip        = ""

        # Build the initial menu for the "not calibrated" state
        self._rebuild_menu()

        # Start background threads
        threading.Thread(target=self._camera_loop, daemon=True).start()
        rumps.Timer(self._on_tick, 3).start()

    # ── Menu actions ──────────────────────────────────────────────────────────

    def _do_calibrate(self, _=None):
        with self._lock:
            if self._calibrating:
                rumps.alert(
                    title="Already calibrating",
                    message="Sit still and hold your best posture — calibration completes in a moment.",
                )
                return
            self._calibrating = True
            self._calibrated  = False

        self.title = "📐"
        self._rebuild_menu()
        rumps.notification(
            title="PostureGuard — Calibrating",
            subtitle="",
            message="Hold your best upright posture for 2 seconds.",
        )

    def _do_pause_toggle(self, _=None):
        with self._lock:
            self._paused = not self._paused
            paused = self._paused

        self.title = "⏸" if paused else self._title_for_score()
        self._rebuild_menu()

    def _do_show_summary(self, _=None):
        with self._lock:
            score         = self._score
            alerts        = list(self._alerts)
            alert_count   = self._alert_count
            mins          = round((time.time() - self._session_start) / 60, 1)
            last_tip      = self._last_tip
            calibrated    = self._calibrated

        if not calibrated:
            rumps.alert(title="PostureGuard",
                        message="Not calibrated yet — click Calibrate to start monitoring.")
            return

        active_issues = (
            "\n".join(f"  • {a['msg']}" for a in alerts)
            or "  ✓ None right now"
        )
        tip_section = f"\n\nLast coach tip:\n  {last_tip}" if last_tip else ""

        rumps.alert(
            title=f"Score: {score} / 100",
            message=(
                f"Session length:  {mins} min\n"
                f"Alerts fired:    {alert_count}\n\n"
                f"Active issues:\n{active_issues}"
                f"{tip_section}"
            ),
        )

    def _do_quit(self, _=None):
        rumps.quit_application()

    # ── Dynamic menu ──────────────────────────────────────────────────────────

    def _rebuild_menu(self):
        """
        Reconstruct the menu to match the current app state.
        Called on every tick and whenever state changes (calibrate, pause, etc.).

        Menu structure by state
        -----------------------
        Not calibrated:
            ⚪  Not calibrated yet
            ─────
            🎯  Calibrate
            ─────
            Quit PostureGuard

        Calibrating:
            📐  Calibrating — sit upright…
            ─────
            Quit PostureGuard

        Monitoring (normal):
            ✅  Score: 92 / 100       (or ⚠️ / 🔴 depending on score)
            ⏱  12.5 min · 2 alerts
               ↳ Head dropping forward    (shown only when alerts are active)
            ─────
            🎯  Re-calibrate
            ⏸  Pause monitoring
            ─────
            📊  Session Summary
            ─────
            Quit PostureGuard

        Paused:
            ⏸  Monitoring paused
            ─────
            ▶  Resume monitoring
            📊  Session Summary
            ─────
            Quit PostureGuard
        """
        with self._lock:
            calibrated  = self._calibrated
            calibrating = self._calibrating
            paused      = self._paused
            score       = self._score
            alerts      = list(self._alerts)
            count       = self._alert_count
            mins        = round((time.time() - self._session_start) / 60, 1)

        items = []

        # ── Not calibrated ────────────────────────────────────────────────────
        if calibrating:
            items += [
                rumps.MenuItem("📐  Calibrating — sit upright…"),
                None,
            ]

        elif not calibrated:
            items += [
                rumps.MenuItem("⚪  Not calibrated yet"),
                None,
                rumps.MenuItem("🎯  Calibrate", callback=self._do_calibrate),
                None,
            ]

        # ── Paused ────────────────────────────────────────────────────────────
        elif paused:
            items += [
                rumps.MenuItem("⏸  Monitoring paused"),
                None,
                rumps.MenuItem("▶  Resume monitoring", callback=self._do_pause_toggle),
                rumps.MenuItem("📊  Session Summary",   callback=self._do_show_summary),
                None,
            ]

        # ── Active monitoring ─────────────────────────────────────────────────
        else:
            score_icon = "✅" if score >= 80 else "⚠️" if score >= 60 else "🔴"
            items.append(rumps.MenuItem(f"{score_icon}  Score: {score} / 100"))
            items.append(rumps.MenuItem(f"⏱  {mins} min  ·  {count} alert(s)"))

            for alert in alerts[:3]:  # show up to 3 active issues
                items.append(rumps.MenuItem(f"   ↳ {alert['msg']}"))

            items += [
                None,
                rumps.MenuItem("🎯  Re-calibrate",      callback=self._do_calibrate),
                rumps.MenuItem("⏸  Pause monitoring",   callback=self._do_pause_toggle),
                None,
                rumps.MenuItem("📊  Session Summary",    callback=self._do_show_summary),
                None,
            ]

        items.append(rumps.MenuItem("Quit PostureGuard", callback=self._do_quit))

        self.menu.clear()
        self.menu = items

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _on_tick(self, _):
        """Update the menu bar title and rebuild the menu every 3 seconds."""
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
        """Return the menu bar title string based on the current score."""
        with self._lock:
            score = self._score
        icon = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
        return f"{icon} {score}"

    # ── Camera loop ───────────────────────────────────────────────────────────

    def _camera_loop(self):
        """Daemon thread: reads frames, runs pose detection, updates state."""
        detector  = PoseDetector()
        analyzer  = PostureAnalyzer()
        alert_mgr = AlertManager()

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            rumps.notification(
                "PostureGuard", "Camera Error",
                "Cannot open camera. Grant camera access and restart."
            )
            return

        smooth_buf = deque(maxlen=SMOOTH_WINDOW)
        cal_count  = 0

        while True:
            with self._lock:
                paused     = self._paused
                calibrating = self._calibrating
                calibrated  = self._calibrated

            if paused:
                time.sleep(0.5)
                continue

            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            frame = cv2.flip(frame, 1)
            landmarks, _ = detector.process(frame)

            if not landmarks:
                time.sleep(0.033)
                continue

            if calibrating:
                cal_count = self._calibrate_frame(analyzer, landmarks, cal_count)
            elif calibrated:
                self._analyse_frame(analyzer, alert_mgr, smooth_buf, landmarks)

            time.sleep(0.033)

        cap.release()
        detector.close()

    def _calibrate_frame(self, analyzer, landmarks, cal_count: int) -> int:
        """Feed one frame into the calibration buffer. Finalises when count reaches target."""
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
        """Run posture analysis and fire notifications if needed."""
        score, alerts = analyzer.analyze(landmarks)
        smooth_buf.append(score)
        smoothed = int(sum(smooth_buf) / len(smooth_buf))

        with self._lock:
            self._score  = smoothed
            self._alerts = alerts

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
                subtitle="Posture restored",
                message="Good job — back on track! 💪",
            )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    PostureGuard().run()
