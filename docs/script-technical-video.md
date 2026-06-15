# PostureGuard — Technical Explanation Video Script

**Target length:** ~5–7 minutes  
**Format:** Code walkthrough + diagrams in your head / whiteboard sketch  
**Tone:** Explain to someone technical — a fellow student or professor  
**Focus:** AI components only (MediaPipe, calibration algorithm, Ollama, HuggingFace)

---

## [0:00 – 0:30] Problem statement

> "The core challenge is this: how do you tell someone their posture is bad without attaching sensors to their body? The approach I took is to use a standard webcam and a pose estimation model to track body landmarks in real time, then compare those landmarks against the person's own baseline rather than against a fixed standard."

---

## [0:30 – 1:15] MediaPipe Pose — the foundation

> "The pose estimation layer is MediaPipe Pose, a model from Google. It runs on a single RGB frame and returns 33 body landmarks — each one is an (x, y, z, visibility) coordinate normalised to the image dimensions."

*If showing code: open `core/pose_detector.py`*

> "I'm using model complexity 1, which is the middle tier — more accurate than complexity 0 but still fast enough for 30fps on a MacBook. I also enable `smooth_landmarks=True`, which applies a temporal filter across frames to reduce jitter."

> "The key landmarks I actually use are nose, left and right ear, and left and right shoulder — five points. Everything else MediaPipe gives me is ignored for posture analysis."

*Optionally show a diagram: skeleton with only those 5 points highlighted.*

---

## [1:15 – 2:15] Feature extraction & normalisation

> "From those five landmarks I extract six features. Let me walk through each one."

*Open `core/posture_analyzer.py`, show `_features()` method.*

> "The first is `head_y` — the vertical position of the nose relative to the midpoint between the two shoulders, divided by shoulder width. Dividing by shoulder width is important: it makes the feature invariant to how far the person is sitting from the camera. If you lean forward, both the nose and shoulders get closer, so the raw pixel positions change — but the ratio stays the same."

> "The second is `sh_tilt` — the vertical difference between the left and right shoulder, again normalised. Zero means perfectly level shoulders."

> "The third is `sh_width` — the raw shoulder width in normalised image coordinates. This one DOES change with distance, and that's intentional: if you lean toward the camera, your shoulders appear wider. So this feature captures forward lean."

> "The fourth and fifth are `ear_tilt` — the angle of the line between the two ear landmarks, in degrees. This captures head tilt. And `ears_visible`, a boolean flag stored as a float, which I'll explain in a moment."

---

## [2:15 – 3:00] Personal calibration

> "Here's the key design decision: every threshold is personal. When the user clicks Calibrate, the app collects 60 frames — about two seconds — and computes the mean of each feature across those frames. That mean becomes the baseline."

*Show `commit_calibration()` in posture_analyzer.py.*

> "So if you naturally sit with one shoulder slightly lower, that's captured in your baseline `sh_tilt`, and the system won't alert you for it. If you naturally sit further from the monitor than average, your `sh_width` reflects that."

> "After calibration, the baseline is saved to disk as JSON. On the next launch, it's loaded automatically — so the user calibrates once per desk setup, not every session."

---

## [3:00 – 3:45] Scoring algorithm

> "Scoring is done by comparing the current frame's features to the baseline. For each of the four signals, I compute the deviation from baseline and check it against a threshold. If it exceeds the threshold, a severity score is computed."

*Show `analyze()` method — specifically the severity formula.*

> "The severity formula is: `(deviation - threshold) / threshold + 0.5`, clamped between 0.5 and 1.0. So the moment you cross the threshold you're at 0.5 severity, and you reach maximum severity when the deviation is twice the threshold. The score deduction is then the per-signal maximum deduction multiplied by severity."

> "This gives a smooth gradient — minor slouches get small penalties, severe ones get large penalties. The weights are: head drop 35 points, forward lean 25, shoulder tilt 20, and head tilt 10. Head tilt gets the lowest weight because it's the noisiest signal — more on that in a moment."

> "The live score is averaged over a rolling window of 8 frames to smooth out frame-to-frame noise."

---

## [3:45 – 4:15] Challenges I solved

> "Two posture signals caused problems that required specific fixes."

> "**Head tilt false positives.** The ear landmarks in MediaPipe are placed on the outer ear. When hair covers the ears, or the person is at a slight angle, MediaPipe returns a low visibility score — but still returns a position, and that position drifts. At the original threshold of 8 degrees, this was triggering false alerts constantly. I added a visibility guard: the head-tilt check is completely skipped when either ear has a visibility score below 0.5. I also raised the threshold to 12 degrees and reduced the deduction to 10 points."

> "**Multi-camera angle problem.** I have an external webcam mounted on top of my monitor and a MacBook camera at laptop level. When I look at the laptop, my head appears to drop from the monitor camera's perspective — triggering a head-drop alert even in perfect posture. The fix: every frame, I read all cameras, run pose estimation on each, and if I'm calibrated I score each result and pick the camera with the highest score. The most generous reading wins. If any camera sees you sitting straight, you are sitting straight."

---

## [4:15 – 5:00] Ollama coaching tips

> "When the score stays below 70 for 30 consecutive seconds, a notification fires. The notification message is generated by a local language model running through Ollama."

*Show `ai/coach.py`.*

> "The prompt is built from the active alert types and the duration. For example: 'You've been sitting with head dropping forward and leaning too close to screen for 45 seconds. Write one specific, actionable, encouraging tip in 1–2 sentences.'"

> "I chose Ollama over a cloud API because everything runs locally — no data about the user's posture leaves their machine. If Ollama isn't running, the system falls back to a curated static tip per alert type."

---

## [5:00 – 5:40] HuggingFace session classification

> "At the session level, I use a HuggingFace zero-shot classifier to categorise how the overall session went."

*Show `ai/session_report.py`.*

> "The model is `facebook/bart-large-mnli`, a BART model fine-tuned for natural language inference. Zero-shot classification works by framing the task as entailment: 'Does this text entail this label?' — no additional training needed."

> "I build a short text summary of the session — average score, percentage of time below 70, total alerts — and run it against four candidate labels: 'excellent posture session', 'good posture with occasional alerts', 'frequent slouching detected', 'neck strain risk'. The label with the highest entailment score is shown on the web dashboard."

---

## [5:40 – 6:10] Phone detection

> "There's one additional heuristic signal: phone detection. A much larger head-drop deviation than normal — more than 0.28 shoulder-widths below the baseline — likely means the user is looking down at their phone rather than slouching. If this persists for a configurable number of minutes, a separate notification fires."

> "This is a heuristic, not a trained model — but it's effective because looking at a phone is a very distinct head drop pattern, much larger than the forward slouch a desk worker typically has."

---

## [6:10 – 6:30] Calibration Studio — building a personal dataset

> "The last AI-adjacent feature is the Calibration Studio. Every 2 minutes, if the posture score has been stable for at least 15 seconds, the app saves a snapshot: the current score, the active alerts, the raw feature values, and a JPEG of the camera frame."

> "The user can then label these snapshots as good or bad posture. Once there are 10 or more labeled examples, the app computes suggested threshold adjustments — essentially checking whether the user's labeled 'good' poses frequently exceed the default thresholds, and loosening them if so. This is the groundwork for a proper personalised model."

---

## [6:30 – 6:50] Close

> "To summarise the AI stack: MediaPipe Pose for real-time landmark detection, a custom personal-baseline calibration and deviation scoring algorithm, Ollama with a local LLM for coaching tips, and HuggingFace BART for session classification. All running locally, on a single webcam, in a lightweight menu bar process."

> "The full source code and engineering decisions log are in the repository."
