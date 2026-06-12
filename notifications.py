import subprocess
import platform


def send_notification(title: str, message: str, sound: bool = True) -> None:
    """
    Send a native macOS notification via osascript.
    Does nothing silently on non-macOS platforms.
    """
    if platform.system() != "Darwin":
        print(f"[notification] {title}: {message}")
        return

    # Escape double quotes to prevent shell injection
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')

    sound_clause = ' sound name "default"' if sound else ""
    script = f'display notification "{safe_message}" with title "{safe_title}"{sound_clause}'

    subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
    )
