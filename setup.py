"""
py2app build script for PostureGuard menu bar app.

Usage:
    .venv/bin/pip install py2app
    .venv/bin/python setup.py py2app
    open dist/PostureGuard.app
"""

import os
from setuptools import setup

# Use $VERSION env var set by the release workflow, else fall back to pyproject version
version = os.environ.get("VERSION", "1.0.0").lstrip("v")

APP = ["menu_bar_app.py"]
OPTIONS = {
    "argv_emulation": False,
    "packages": [
        "cv2",
        "mediapipe",
        "rumps",
        "numpy",
        "requests",
        "core",
        "ai",
    ],
    "plist": {
        "CFBundleName": "PostureGuard",
        "CFBundleDisplayName": "PostureGuard",
        "CFBundleVersion": version,
        "CFBundleShortVersionString": version,
        "LSUIElement": True,  # hides dock icon — menu-bar-only app
        "NSCameraUsageDescription": (
            "PostureGuard needs camera access to monitor your posture in real time."
        ),
    },
}

setup(
    name="PostureGuard",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
