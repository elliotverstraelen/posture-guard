# Changelog

## [Unreleased]

## [1.0.0] — 2026-06-12

### Added
- MediaPipe Pose baseline calibration — learns your personal good-posture reference
- Four posture signals from front camera: head drop, forward lean, shoulder tilt, head tilt
- 30-second bad-posture timer with 2-minute cooldown between notifications
- Native macOS notifications via osascript
- Ollama LLM coaching tips with static fallbacks when Ollama is offline
- "Good job" notification when posture is restored after an alert
- Flask web dashboard with live MJPEG camera feed, posture score ring, history chart
- HuggingFace zero-shot session quality classification (`facebook/bart-large-mnli`)
- rumps menu bar app (Phase 2) — no dock icon, live score in menu bar
- py2app packaging with `NSCameraUsageDescription` plist entry
- Camera permission error banner in the web dashboard
- Mock server for screenshots and UI testing without a camera
