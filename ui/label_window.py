"""
Native macOS pose-labeling window for PostureGuard Calibration Studio.

Shows the actual camera frame captured at each snapshot so you can see
exactly what you were doing and label it Good / Bad / Skip.
"""

import os

import objc
from AppKit import (
    NSApp, NSBackingStoreBuffered, NSButton, NSColor, NSFont,
    NSFloatingWindowLevel, NSImage, NSImageScaleProportionallyUpOrDown,
    NSImageView, NSMakeRect, NSMakeSize, NSTextField,
    NSVisualEffectView, NSWindow,
    NSWindowStyleMaskClosable, NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskTitled,
)
from Foundation import NSObject

import core.snapshot_store as _store
from core.posture_analyzer import ALERT_LABELS

_W      = 400
_IMG_H  = 260
_PAD    = 20


class _LabelCtrl(NSObject):

    @objc.python_method
    def setup(self, entries, on_complete, stats_label, progress_label, image_view):
        self._entries       = entries      # [(global_idx, entry_dict), ...]
        self._on_complete   = on_complete
        self._stats_label   = stats_label
        self._progress_label = progress_label
        self._image_view    = image_view
        self._idx           = 0
        self._labeled       = 0
        self._update()

    # ── Obj-C button actions ──────────────────────────────────────────────────

    def goodPressed_(self, sender):
        self._commit("good")

    def badPressed_(self, sender):
        self._commit("bad")

    def skipPressed_(self, sender):
        self._advance()

    def windowWillClose_(self, notification):
        LabelWindow._instance = None
        if self._on_complete:
            self._on_complete(self._labeled)

    # ── Internal ──────────────────────────────────────────────────────────────

    @objc.python_method
    def _commit(self, label: str):
        global_idx, _ = self._entries[self._idx]
        _store.set_label(global_idx, label)
        self._labeled += 1
        self._advance()

    @objc.python_method
    def _advance(self):
        self._idx += 1
        if self._idx >= len(self._entries):
            LabelWindow._close_current()
        else:
            self._update()

    @objc.python_method
    def _update(self):
        if self._idx >= len(self._entries):
            return
        _, entry = self._entries[self._idx]

        # Image
        img_path = entry.get("image")
        if img_path and os.path.exists(img_path):
            img = NSImage.alloc().initWithContentsOfFile_(img_path)
        else:
            img = None
        self._image_view.setImage_(img)

        # Stats text
        lines = [f"Score: {entry['score']} / 100"]
        alerts = entry.get("alerts", [])
        if alerts:
            lines.append("Active signals:")
            for a in alerts:
                lines.append(f"  • {ALERT_LABELS.get(a, a)}")
        else:
            lines.append("No posture signals triggered.")
        feats = entry.get("features", {})
        if feats:
            lines += [
                "",
                f"Head drop:      {feats.get('head_y', 0):+.3f}",
                f"Forward lean:   {feats.get('sh_width', 0):.3f}",
                f"Shoulder tilt:  {feats.get('sh_tilt', 0):+.3f}",
                f"Head tilt:      {feats.get('ear_tilt', 0):+.1f}°",
            ]
        self._stats_label.setStringValue_("\n".join(lines))

        # Progress
        total = len(self._entries)
        self._progress_label.setStringValue_(f"Pose {self._idx + 1} of {total}")


# ── Public singleton ──────────────────────────────────────────────────────────

class LabelWindow:
    _instance = None

    @classmethod
    def open(cls, entries, on_complete=None):
        """
        entries    : [(global_idx, entry_dict), ...]
        on_complete: callable(labeled_count) called when done or window closed
        """
        if not entries:
            return

        if cls._instance:
            try:
                cls._instance._window.makeKeyAndOrderFront_(None)
                NSApp.activateIgnoringOtherApps_(True)
                return
            except Exception:
                cls._instance = None

        stats_h   = 140
        progress_h = 20
        btns_h    = 40
        H = _PAD + _IMG_H + _PAD + stats_h + _PAD + progress_h + _PAD + btns_h + _PAD

        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, _W, H),
            (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
             | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskFullSizeContentView),
            NSBackingStoreBuffered, False,
        )
        win.setTitle_("Calibration Studio — Label Pose")
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

        y = H - 44   # below title bar

        # ── Image view ────────────────────────────────────────────────────────
        img_view = NSImageView.alloc().initWithFrame_(
            NSMakeRect(_PAD, y - _IMG_H, _W - 2*_PAD, _IMG_H)
        )
        img_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        img_view.setWantsLayer_(True)
        img_view.layer().setCornerRadius_(10)
        img_view.layer().setMasksToBounds_(True)
        vfx.addSubview_(img_view)
        y -= _IMG_H + _PAD

        # ── Stats text ────────────────────────────────────────────────────────
        stats_lbl = NSTextField.labelWithString_("")
        stats_lbl.setFrame_(NSMakeRect(_PAD, y - stats_h, _W - 2*_PAD, stats_h))
        stats_lbl.setFont_(NSFont.systemFontOfSize_(12))
        stats_lbl.cell().setWraps_(True)
        stats_lbl.setTextColor_(NSColor.labelColor())
        vfx.addSubview_(stats_lbl)
        y -= stats_h + _PAD

        # ── Progress ──────────────────────────────────────────────────────────
        prog_lbl = NSTextField.labelWithString_("")
        prog_lbl.setFrame_(NSMakeRect(_PAD, y - progress_h, _W - 2*_PAD, progress_h))
        prog_lbl.setFont_(NSFont.systemFontOfSize_(11))
        prog_lbl.setTextColor_(NSColor.secondaryLabelColor())
        vfx.addSubview_(prog_lbl)
        y -= progress_h + _PAD

        # ── Buttons ───────────────────────────────────────────────────────────
        bw = (_W - 2*_PAD - 16) // 3
        for i, (title, sel) in enumerate([
            ("✅  Good posture", "goodPressed:"),
            ("⏭  Skip",         "skipPressed:"),
            ("❌  Bad posture",  "badPressed:"),
        ]):
            btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(_PAD + i * (bw + 8), y - btns_h, bw, btns_h - 4)
            )
            btn.setTitle_(title)
            btn.setBezelStyle_(1)
            vfx.addSubview_(btn)
            # Target set after ctrl is created below

        # ── Controller ────────────────────────────────────────────────────────
        ctrl = _LabelCtrl.alloc().init()
        ctrl.setup(entries, on_complete, stats_lbl, prog_lbl, img_view)
        win.setDelegate_(ctrl)

        # Wire button targets now that ctrl exists
        for sub in vfx.subviews():
            if isinstance(sub, NSButton):
                sub.setTarget_(ctrl)
                title = sub.title()
                if "Good" in title:
                    sub.setAction_("goodPressed:")
                elif "Skip" in title:
                    sub.setAction_("skipPressed:")
                elif "Bad" in title:
                    sub.setAction_("badPressed:")

        inst          = cls.__new__(cls)
        inst._window  = win
        inst._ctrl    = ctrl
        cls._instance = inst

        win.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    @classmethod
    def _close_current(cls):
        if cls._instance:
            cls._instance._window.orderOut_(None)
            cls._instance = None
