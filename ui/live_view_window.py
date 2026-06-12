"""
Live dual-camera view with pose skeleton overlay.

Shows all connected cameras side by side with MediaPipe skeletons drawn on
each feed and the real-time posture score overlaid.  Updates at ~15 fps.
"""

import threading
import time

import cv2
import numpy as np
import objc
from AppKit import (
    NSApp, NSBackingStoreBuffered, NSBitmapImageRep, NSColor,
    NSDeviceRGBColorSpace, NSFloatingWindowLevel, NSFont, NSImage,
    NSImageScaleProportionallyUpOrDown, NSImageView, NSMakeRect, NSMakeSize,
    NSTextField, NSVisualEffectView, NSWindow,
    NSWindowStyleMaskClosable, NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskTitled,
)
from Foundation import NSData, NSObject, NSTimer

from core.pose_detector import PoseDetector
from core.posture_analyzer import PostureAnalyzer

# Skeleton connections drawn on each frame
_CONNECTIONS = [
    (11, 12),           # shoulders
    (11, 13), (13, 15), # left arm
    (12, 14), (14, 16), # right arm
    (11, 23), (12, 24), # torso sides
    (23, 24),           # hips
    (7,  8),            # ear line
    (0,  7), (0,  8),   # nose → ears
    (7, 11), (8, 12),   # ears → shoulders (neck)
]

FEED_W = 320
FEED_H = 240
PAD    = 16


# ── Frame helpers ─────────────────────────────────────────────────────────────

def _to_nsimage(bgr: np.ndarray) -> NSImage:
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    h, w = rgb.shape[:2]
    raw  = rgb.tobytes()
    rep  = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, w, h, 8, 3, False, False, NSDeviceRGBColorSpace, w * 3, 24
    )
    rep.bitmapData()[:len(raw)] = raw
    img = NSImage.alloc().initWithSize_(NSMakeSize(w, h))
    img.addRepresentation_(rep)
    return img


def _draw_skeleton(frame: np.ndarray, landmarks) -> np.ndarray:
    h, w = frame.shape[:2]
    for a, b in _CONNECTIONS:
        la, lb = landmarks[a], landmarks[b]
        if la.visibility > 0.4 and lb.visibility > 0.4:
            pa = (int(la.x * w), int(la.y * h))
            pb = (int(lb.x * w), int(lb.y * h))
            cv2.line(frame, pa, pb, (0, 200, 255), 2, cv2.LINE_AA)
    for lm in landmarks:
        if lm.visibility > 0.4:
            cv2.circle(frame, (int(lm.x * w), int(lm.y * h)), 4, (0, 255, 100), -1, cv2.LINE_AA)
    return frame


def _annotate_score(frame: np.ndarray, score: int, cam_label: str) -> np.ndarray:
    color = (0, 220, 80) if score >= 80 else (0, 200, 255) if score >= 60 else (40, 40, 255)
    cv2.putText(frame, f"{cam_label}  {score}/100",
                (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(frame, f"{cam_label}  {score}/100",
                (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color,    2, cv2.LINE_AA)
    return frame


# ── Controller (NSObject for timer/delegate callbacks) ────────────────────────

class _LiveCtrl(NSObject):

    @objc.python_method
    def setup(self, shared, image_views):
        self._shared      = shared
        self._image_views = image_views
        self._timer       = None

    def startTimer_(self, _):
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.067, self, "tick:", None, True
        )

    def tick_(self, _):
        with self._shared["lock"]:
            frames = list(self._shared["frames"])
        for frame, view in zip(frames, self._image_views):
            if frame is not None:
                view.setImage_(_to_nsimage(frame))

    def windowWillClose_(self, _):
        if self._timer:
            self._timer.invalidate()
        self._shared["running"] = False
        LiveViewWindow._instance = None


# ── Public singleton ──────────────────────────────────────────────────────────

class LiveViewWindow:
    _instance = None

    @classmethod
    def open(cls, cameras: list, analyzer: PostureAnalyzer):
        if cls._instance:
            try:
                cls._instance._window.makeKeyAndOrderFront_(None)
                NSApp.activateIgnoringOtherApps_(True)
                return
            except Exception:
                cls._instance = None

        n   = max(len(cameras), 1)
        win_w = PAD + n * (FEED_W + PAD)
        win_h = FEED_H + 48 + PAD

        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskFullSizeContentView
        )
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, win_w, win_h), style, NSBackingStoreBuffered, False
        )
        win.setTitle_("PostureGuard — Live View")
        win.setTitlebarAppearsTransparent_(True)
        win.setLevel_(NSFloatingWindowLevel)
        win.center()
        win.setReleasedWhenClosed_(False)

        vfx = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, win_w, win_h))
        vfx.setMaterial_(12)
        vfx.setBlendingMode_(0)
        vfx.setState_(0)
        win.setContentView_(vfx)

        shared = {"frames": [None] * n, "lock": threading.Lock(), "running": True}
        image_views = []

        for i, (cv_idx, label) in enumerate(cameras):
            x = PAD + i * (FEED_W + PAD)
            # Camera label
            lf = NSTextField.labelWithString_(label)
            lf.setFrame_(NSMakeRect(x, FEED_H + PAD + 4, FEED_W, 20))
            lf.setFont_(NSFont.boldSystemFontOfSize_(11))
            lf.setAlignment_(1)  # center
            vfx.addSubview_(lf)
            # Image view
            iv = NSImageView.alloc().initWithFrame_(NSMakeRect(x, PAD, FEED_W, FEED_H))
            iv.setImageScaling_(NSImageScaleProportionallyUpOrDown)
            iv.setWantsLayer_(True)
            iv.layer().setCornerRadius_(8)
            iv.layer().setMasksToBounds_(True)
            vfx.addSubview_(iv)
            image_views.append(iv)

        ctrl = _LiveCtrl.alloc().init()
        ctrl.setup(shared, image_views)
        win.setDelegate_(ctrl)

        threading.Thread(
            target=_capture_loop,
            args=(cameras, analyzer, shared),
            daemon=True,
        ).start()

        inst          = cls.__new__(cls)
        inst._window  = win
        inst._ctrl    = ctrl
        cls._instance = inst

        win.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        ctrl.performSelector_withObject_afterDelay_("startTimer:", None, 0.1)


# ── Capture thread ────────────────────────────────────────────────────────────

def _capture_loop(cameras, analyzer, shared):
    caps      = []
    detectors = []
    for cv_idx, _ in cameras:
        cap = cv2.VideoCapture(cv_idx)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FEED_W * 2)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FEED_H * 2)
        caps.append(cap)
        detectors.append(PoseDetector())

    while shared.get("running", True):
        frames = []
        for i, (cap, (_, label)) in enumerate(zip(caps, cameras)):
            if not cap.isOpened():
                frames.append(None)
                continue
            ret, frame = cap.read()
            if not ret:
                frames.append(None)
                continue
            frame = cv2.flip(frame, 1)
            frame = cv2.resize(frame, (FEED_W, FEED_H))
            lm, _ = detectors[i].process(frame.copy())
            if lm:
                frame = _draw_skeleton(frame, lm)
                if analyzer.baseline:
                    score, _ = analyzer.analyze(lm)
                    frame = _annotate_score(frame, score, label.split()[0])
            frames.append(frame)

        with shared["lock"]:
            shared["frames"] = frames
        time.sleep(0.067)

    for cap in caps:
        cap.release()
    for det in detectors:
        det.close()
