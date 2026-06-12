# PostureGuard — Engineering Decisions & Problem Log

A running record of every non-obvious technical decision made while building PostureGuard, including the problem it solved and why the chosen approach was the right one. Written to support the explanation video.

---

## 1. Why rumps nested submenus stopped working (Settings)

**Problem:** The macOS menu bar app uses the `rumps` Python framework. Settings were initially nested as submenu items (camera picker, toggles, etc.). Every 3 seconds the menu was rebuilt to reflect new data — but all nested submenu callbacks showed as greyed out / non-interactive.

**Root cause:** PyObjC — the bridge rumps uses to talk to macOS — silently drops Objective-C action targets when a menu item is recreated dynamically and the Python object backing it goes out of scope.

**Decision:** Throw away the nested submenu approach entirely. A single "⚙️ Settings…" menu item opens a proper native `NSWindow` (built with AppKit directly, not rumps). All controls — camera picker, toggles, number fields — are laid out manually as AppKit widgets. Their Obj-C action methods live on an `NSObject` subclass that persists for the lifetime of the window.

**Why it works:** Native AppKit windows have a stable object graph; the target/action pair never gets recreated, so callbacks always fire.

---

## 2. PyObjC class name collision between ui modules

**Problem:** After splitting the settings window and the live-view window into separate Python files, the app crashed on startup with:

```
objc.error: _Ctrl is overriding existing Objective-C class
```

**Root cause:** PyObjC registers Objective-C class names in a global process-wide table. Both `settings_window.py` and `live_view_window.py` defined a class called `_Ctrl(NSObject)`. The second import overwrote the first's Obj-C registration, corrupting both.

**Decision:** Rename each controller class to a unique name: `_SettingsCtrl`, `_LiveCtrl`, `_LabelCtrl`. This naming convention is enforced across all `ui/` modules.

**Rule:** Every `NSObject` subclass in this codebase must have a globally unique name. Adding the window's purpose as a prefix is sufficient.

---

## 3. Displaying a numpy camera frame inside NSImageView

**Problem:** The Live View window needs to show real-time camera frames (numpy BGR arrays from OpenCV) inside a native `NSImageView`.

**First attempt — ctypes memmove:**
```python
ctypes.memmove(rep.bitmapData(), rgb.ctypes.data_as(ctypes.c_void_p), rgb.nbytes)
# → ctypes.ArgumentError: argument 1: TypeError: wrong type
```
`bitmapData()` returns a PyObjC buffer object, not a raw pointer. ctypes can't copy into it directly.

**Decision:** Use Python slice assignment instead:
```python
raw = rgb.tobytes()
rep.bitmapData()[:len(raw)] = raw
```
PyObjC exposes `bitmapData()` as a mutable buffer that supports the Python buffer protocol, so slice assignment works natively without any C-level pointer casting.

---

## 4. Head-tilt false positives

**Problem:** The app frequently reported "Head tilted sideways" even when the user was sitting straight. The score dropped to ~80 for no reason.

**Root cause (two parts):**
1. The original threshold was 8°. MediaPipe's ear landmarks (`LEFT_EAR`, `RIGHT_EAR`) are placed on the outer ear, not the centre of the head. Hair, slight head rotation, or low lighting push the visibility score down and cause the landmark coordinates to drift noisily.
2. The score deduction for head tilt was 20 points — the same as shoulder asymmetry — which made even a minor false positive noticeable.

**Decision:**
- Raise the threshold from 8° to 12°.
- Add an `ears_visible` guard: skip the head-tilt check entirely when either ear landmark has `visibility < 0.5`.
- Reduce the deduction from 20 to 10 points (head-tilt detection is inherently noisier than the shoulder/head-drop signals, so it should contribute less to the final score).

---

## 5. External camera giving wrong scores due to viewing angle

**Problem:** The user has an external webcam mounted on top of a monitor and a MacBook camera at laptop level. When sitting with perfect posture looking at the laptop screen, the external camera (looking slightly down) scored 37/100 while the MacBook scored 76/100.

**Root cause:** The camera loop always picked the *first* camera that returned valid MediaPipe landmarks. The external camera's landmarks reflected a "head-down" angle (relative to its mounting position), triggering a head-drop alert even in a normal working position.

**Decision:** Read *all* available cameras every frame. When a calibration baseline exists and there are multiple candidates, run a quick `analyze()` call on each and keep the one with the **highest score** (most favourable posture reading). For calibration frames (before a baseline exists) the first valid camera is still used for consistency.

**Why "highest score"?** If any camera sees good posture it means you are in good posture. The problematic camera is the one mounted at a bad angle — choosing the most generous reading is the correct behaviour because it reflects what your body is actually doing, not an artefact of camera placement.

---

## 6. Persistent calibration (survives reboots)

**Problem:** Every time the app launched it started uncalibrated. The user had to redo the 3-second calibration ritual every session.

**Decision:** After `commit_calibration()` computes the baseline from 60 frames of MediaPipe landmarks, write it as JSON to `~/.config/postureguard/baseline.json`. On `PostureAnalyzer.__init__()` call `_load_baseline()` to restore it. If the file is present and valid, `analyzer.baseline` is set and `self._calibrated = True` is set in the shared app state, so the menu bar shows the monitoring UI immediately without asking the user to calibrate again.

**Re-calibration** is still available via the menu bar at any time (e.g. if you move to a different desk or camera position).

---

## 7. Snapshot quality — only stable poses

**Problem:** The score chart showed frequent transient dips (e.g. reaching for a cup briefly triggers a head-drop alert). If snapshots were saved on a fixed timer they'd capture those transient bad postures, which aren't representative of sustained habits.

**Decision:** Track `stable_since` (the time the score last changed by more than ±8 points). A snapshot is only saved when the score has been stable for **15+ seconds** AND at least 2 minutes have passed since the last snapshot. This means only *sustained* postures — the flat plateaus visible in the history chart — are ever captured for labeling.

---

## 8. "Improve model" button requires 10 labeled poses

**Problem:** The "🔬 Improve model" button was always enabled even when there was zero or insufficient labeling data. Clicking it with 2 labels would silently produce meaningless threshold adjustments.

**Decision:** Compute the labeled-pose count when the Settings window opens. The button is disabled (greyed out) until the user has labeled at least 10 poses. The descriptive note below the section heading shows the exact count and how many more are needed, e.g. "3 poses labeled — 7 more labels needed to improve the model."

---

## 9. NSTimer for Live View frame updates

**Problem:** The Live View window needs to refresh camera frames at ~15fps in a native macOS window. `rumps`'s timer can't drive AppKit UI updates because rumps runs on a secondary thread and AppKit requires UI updates on the main thread.

**Decision:** Use `NSTimer` scheduled on the main run loop via `performSelector_withObject_afterDelay_`. The `_LiveCtrl` controller creates the timer in `startTimer_` (called via the deferred selector so it runs on the main thread) and stops it in `windowWillClose_`. Frame data is written by the camera thread into a shared dictionary under a lock; the timer's `tick_` method reads it and calls `setImage_` on the `NSImageView`s.

---

## 10. Image display in Calibration Studio label dialog

**Problem:** The original label dialog showed only text stats (score, feature numbers). The user couldn't tell what posture they were in just from numbers — the whole point of labeling is to see what you looked like.

**Decision:** When `save_snapshot()` runs, save the raw OpenCV frame as a JPEG alongside the feature JSON (`~/.config/postureguard/snapshots/pose_{ts}.jpg`). The `LabelWindow` loads this file via `NSImage.alloc().initWithContentsOfFile_()` and displays it in an `NSImageView` with rounded corners at the top of the window. If no image file is found (snapshots taken before this feature) the image area is left blank and the stats text is still shown.

---

## 11. Multi-camera support and camera restarts

**Problem:** Users may have multiple cameras (MacBook FaceTime, Logitech webcam, iPhone Continuity Camera). Single-camera selection meant they had to know which index their camera was.

**Decision:** Probe `cv2.VideoCapture` indices 0–5 at startup. Keep all that successfully open and return valid frames. In "use all cameras" mode, poll all of them each frame. Camera index is also user-configurable in Settings for single-camera mode.

A `_camera_restart` flag allows the Settings window to signal the camera thread to release and re-open all cameras after the user changes the camera selection, without restarting the whole app.

---

## 12. Release automation (GitHub Actions + Homebrew)

**Problem:** Manual releases would require building a `.app` with py2app, zipping it, computing the SHA256, creating a GitHub Release, and updating the Homebrew formula — error-prone and easy to forget a step.

**Decision:** `.github/workflows/release.yml` triggers on `v*` tags. It:
1. Builds `PostureGuard.app` with py2app (passing `VERSION` as env var)
2. Zips the `.app` and uploads it as a GitHub Release asset
3. Computes the SHA256 of the source tarball
4. Clones the `elliotverstraelen/homebrew-postureguard` tap repo using a `HOMEBREW_TAP_TOKEN` secret, updates the formula's `url` and `sha256` lines with `sed`, and pushes

The workflow requires `permissions: contents: write` on the job (the default `GITHUB_TOKEN` lacks this — it caused 403 failures on early runs until the permission was added).
