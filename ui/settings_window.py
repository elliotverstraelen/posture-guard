"""
Native macOS settings panel for PostureGuard.
Frosted-glass NSWindow.  Settings save the moment you change them.
"""

import subprocess

import objc
from AppKit import (
    NSApp, NSBackingStoreBuffered, NSBox, NSButton, NSColor,
    NSFloatingWindowLevel, NSFont, NSMakeRect, NSOffState, NSOnState,
    NSPopUpButton, NSTextField, NSVisualEffectView, NSWindow,
    NSWindowStyleMaskClosable, NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskTitled,
)
from Foundation import NSObject

import core.snapshot_store as _snapshot_store

_W   = 440
_PAD = 24
_ROW = 26   # standard row height
_MIN_LABELS = 10   # labels required before "Improve model" is enabled


class _SettingsCtrl(NSObject):

    @objc.python_method
    def setup(self, settings, cameras, on_camera_change,
              label_poses_fn, apply_labels_fn, stats_fn):
        self._s                = settings
        self._cameras          = cameras
        self._on_cam_change    = on_camera_change
        self._label_poses_fn   = label_poses_fn
        self._apply_labels_fn  = apply_labels_fn
        self._stats_fn         = stats_fn
        self._phone_field      = None
        self._alert_field      = None

    # ── Obj-C actions (no @python_method — must be real selectors) ────────────

    def openCameraPermissions_(self, sender):
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",
        ])

    def cameraChanged_(self, sender):
        idx = sender.indexOfSelectedItem()
        if 0 <= idx < len(self._cameras):
            cv_idx, _ = self._cameras[idx]
            self._s.set("camera_index", cv_idx)
            if self._on_cam_change:
                self._on_cam_change()

    def allCamerasToggled_(self, sender):
        self._s.set("use_all_cameras", sender.state() == NSOnState)
        if self._on_cam_change:
            self._on_cam_change()

    def phoneToggled_(self, sender):
        self._s.set("phone_detection_enabled", sender.state() == NSOnState)

    def labelPoses_(self, sender):
        if self._label_poses_fn:
            self._label_poses_fn()

    def applyLabels_(self, sender):
        if self._apply_labels_fn:
            self._apply_labels_fn()

    def showStats_(self, sender):
        if self._stats_fn:
            self._stats_fn()

    def done_(self, sender):
        self._flush()
        SettingsWindow._close_current()

    def windowWillClose_(self, notification):
        self._flush()
        SettingsWindow._instance = None

    @objc.python_method
    def _flush(self):
        if self._phone_field:
            v = self._phone_field.stringValue().strip()
            if v.isdigit():
                self._s.set("phone_alert_minutes", int(v))
        if self._alert_field:
            v = self._alert_field.stringValue().strip()
            if v.isdigit():
                self._s.set("alert_threshold_seconds", int(v))


class SettingsWindow:
    _instance = None

    @classmethod
    def open(cls, settings, cameras,
             on_camera_change=None,
             label_poses_fn=None,
             apply_labels_fn=None,
             stats_fn=None):
        if cls._instance:
            try:
                cls._instance._window.makeKeyAndOrderFront_(None)
                NSApp.activateIgnoringOtherApps_(True)
                return
            except Exception:
                cls._instance = None

        inst       = cls.__new__(cls)
        inst._ctrl = _SettingsCtrl.alloc().init()
        inst._ctrl.setup(settings, cameras, on_camera_change,
                         label_poses_fn, apply_labels_fn, stats_fn)
        inst._window = _build(inst._ctrl, settings, cameras)
        inst._window.setDelegate_(inst._ctrl)
        cls._instance = inst
        inst._window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    @classmethod
    def _close_current(cls):
        if cls._instance:
            cls._instance._window.orderOut_(None)
            cls._instance = None


def _build(ctrl, settings, cameras) -> NSWindow:
    H = 574
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, _W, H),
        (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
         | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskFullSizeContentView),
        NSBackingStoreBuffered, False,
    )
    win.setTitle_("PostureGuard — Settings")
    win.setTitlebarAppearsTransparent_(True)
    win.setMovableByWindowBackground_(True)
    win.setLevel_(NSFloatingWindowLevel)
    win.center()
    win.setReleasedWhenClosed_(False)

    vfx = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, H))
    vfx.setMaterial_(12)
    vfx.setBlendingMode_(0)
    vfx.setState_(0)
    win.setContentView_(vfx)
    cv = vfx

    y = H - 52  # top of content area (below title bar)

    # ── Camera ────────────────────────────────────────────────────────────────
    y = _heading(cv, "📷  Camera", y)

    popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
        NSMakeRect(_PAD, y - 28, _W - 2*_PAD, 26), False
    )
    for _, label in cameras:
        popup.addItemWithTitle_(label)
    sel = next((i for i, (ci, _) in enumerate(cameras)
                if ci == settings.camera_index), 0)
    popup.selectItemAtIndex_(sel)
    popup.setTarget_(ctrl)
    popup.setAction_("cameraChanged:")
    cv.addSubview_(popup)
    y -= 36

    cb_all = _checkbox(cv, "Use all cameras simultaneously (best coverage)",
                       y=y, checked=settings.use_all_cameras)
    cb_all.setTarget_(ctrl)
    cb_all.setAction_("allCamerasToggled:")
    y -= 30

    perm_btn = _btn(cv, "🔒  Camera Permissions…", _PAD, y - 24, 180, 22)
    perm_btn.setBezelStyle_(2)   # rounded rect — smaller than the default push button
    perm_btn.setFont_(NSFont.systemFontOfSize_(11))
    perm_btn.setTarget_(ctrl)
    perm_btn.setAction_("openCameraPermissions:")
    y -= 34

    _sep(cv, y - 6)
    y -= 20

    # ── Notifications ─────────────────────────────────────────────────────────
    y = _heading(cv, "🔔  Notifications", y)

    cb_phone = _checkbox(cv, "Phone detection  —  alert when looking down too long",
                         y=y, checked=settings.phone_detection_enabled)
    cb_phone.setTarget_(ctrl)
    cb_phone.setAction_("phoneToggled:")
    y -= 30

    # "Alert after  [10]  minutes"  — indented, all on one tidy row
    INDENT = _PAD + 20
    _label_r(cv, "Alert after",  INDENT,             y - 20, 78)
    phone_f = _numfield(cv, str(settings.phone_alert_minutes), INDENT + 82, y - 22, 42)
    _label_r(cv, "minutes",      INDENT + 130,        y - 20, 60)
    ctrl._phone_field = phone_f
    y -= 32

    _sep(cv, y - 6)
    y -= 20

    # ── Alert timing ──────────────────────────────────────────────────────────
    y = _heading(cv, "⏱  Posture Alert Delay", y)

    _label_r(cv, "Alert after",  _PAD,             y - 20, 78)
    alert_f = _numfield(cv, str(settings.alert_threshold_seconds), _PAD + 82, y - 22, 42)
    _label_r(cv, "seconds of bad posture", _PAD + 130, y - 20, 180)
    ctrl._alert_field = alert_f
    y -= 36

    _sep(cv, y - 6)
    y -= 20

    # ── Calibration Studio ────────────────────────────────────────────────────
    y = _heading(cv, "🎓  Calibration Studio", y)

    counts  = _snapshot_store.labeled_counts()
    n_labeled = counts.get("good", 0) + counts.get("bad", 0) + counts.get("unsure", 0)
    n_unlabeled = counts.get("unlabeled", 0)
    n_total = n_labeled + n_unlabeled
    remaining = max(0, _MIN_LABELS - n_labeled)

    if n_total == 0:
        note_text = ("No snapshots yet. Hold a pose for 15+ seconds and "
                     "PostureGuard will save it for labeling.")
    elif remaining > 0:
        note_text = (f"{n_labeled} pose{'s' if n_labeled != 1 else ''} labeled "
                     f"({n_unlabeled} unlabeled) — "
                     f"{remaining} more label{'s' if remaining != 1 else ''} needed "
                     f"to improve the model.")
    else:
        note_text = (f"{n_labeled} poses labeled ({n_unlabeled} unlabeled). "
                     "Model can be improved with your data.")

    note = NSTextField.labelWithString_(note_text)
    note.setFrame_(NSMakeRect(_PAD, y - 40, _W - 2*_PAD, 36))
    note.setFont_(NSFont.systemFontOfSize_(11))
    note.setTextColor_(NSColor.secondaryLabelColor())
    note.cell().setWraps_(True)
    cv.addSubview_(note)
    y -= 52

    bw = (_W - 2*_PAD - 16) // 3
    for i, (title, sel_str, enabled) in enumerate([
        ("🏷  Label poses",   "labelPoses:",  n_unlabeled > 0 or n_total == 0),
        ("🔬  Improve model", "applyLabels:", n_labeled >= _MIN_LABELS),
        ("📊  Statistics",    "showStats:",   True),
    ]):
        btn = _btn(cv, title, _PAD + i * (bw + 8), y - 30, bw, 28)
        btn.setTarget_(ctrl)
        btn.setAction_(sel_str)
        btn.setEnabled_(enabled)
    y -= 42

    # ── Done button ───────────────────────────────────────────────────────────
    done_btn = _btn(cv, "Done", _W - _PAD - 72, 16, 72, 30)
    done_btn.setKeyEquivalent_("\r")
    done_btn.setTarget_(ctrl)
    done_btn.setAction_("done:")

    return win


# ── UI helpers ────────────────────────────────────────────────────────────────

def _heading(parent, text, y) -> int:
    f = NSTextField.labelWithString_(text)
    f.setFrame_(NSMakeRect(_PAD, y - 20, _W - 2*_PAD, 18))
    f.setFont_(NSFont.boldSystemFontOfSize_(13))
    parent.addSubview_(f)
    return y - 28


def _label_r(parent, text, x, y, width) -> NSTextField:
    """Right-aligned label for use beside a number field."""
    f = NSTextField.labelWithString_(text)
    f.setFrame_(NSMakeRect(x, y, width, 20))
    f.setFont_(NSFont.systemFontOfSize_(12))
    f.setAlignment_(2)   # right-align so it butts up against the field
    parent.addSubview_(f)
    return f


def _numfield(parent, value, x, y, width) -> NSTextField:
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, 22))
    f.setStringValue_(value)
    f.setFont_(NSFont.systemFontOfSize_(12))
    f.setAlignment_(2)   # center
    parent.addSubview_(f)
    return f


def _checkbox(parent, text, y, checked=False) -> NSButton:
    cb = NSButton.checkboxWithTitle_target_action_(text, None, None)
    cb.setFrame_(NSMakeRect(_PAD, y - 22, _W - 2*_PAD, 20))
    cb.setState_(NSOnState if checked else NSOffState)
    cb.setFont_(NSFont.systemFontOfSize_(12))
    parent.addSubview_(cb)
    return cb


def _btn(parent, title, x, y, w, h) -> NSButton:
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    btn.setTitle_(title)
    btn.setBezelStyle_(1)
    parent.addSubview_(btn)
    return btn


def _sep(parent, y):
    box = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, y, _W - 2*_PAD, 1))
    box.setBoxType_(2)
    parent.addSubview_(box)
