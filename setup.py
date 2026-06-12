"""
py2app build script for PostureGuard menu bar app.

Usage:
    pip install py2app
    python setup.py py2app
    open dist/PostureGuard.app
"""

from setuptools import setup

APP = ["menu_bar_app.py"]
DATA_FILES = [
    ("templates", ["templates/index.html"]),
    ("static/js", ["static/js/dashboard.js"]),
]
OPTIONS = {
    "argv_emulation": False,
    "packages": [
        "cv2",
        "mediapipe",
        "rumps",
        "numpy",
        "requests",
        "flask",
        "transformers",
        "core",
        "ai",
    ],
    "includes": ["notifications"],
    "plist": {
        "CFBundleName": "PostureGuard",
        "CFBundleDisplayName": "PostureGuard",
        "CFBundleVersion": "1.0.0",
        "LSUIElement": True,  # hides dock icon — true background/menu-bar app
        "NSCameraUsageDescription": (
            "PostureGuard needs camera access to monitor your posture in real time."
        ),
    },
}

setup(
    name="PostureGuard",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
