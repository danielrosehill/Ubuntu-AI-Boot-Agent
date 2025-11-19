"""Boot log capture module using journalctl."""

import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


def get_boot_id() -> str:
    """Get the current boot ID."""
    result = subprocess.run(
        ["journalctl", "--list-boots", "-o", "json"],
        capture_output=True,
        text=True
    )
    # Get current boot (index 0)
    result = subprocess.run(
        ["journalctl", "--boot", "0", "-o", "short", "-n", "1", "--output-fields=_BOOT_ID"],
        capture_output=True,
        text=True
    )
    # Alternative: just use -b 0 for current boot
    return "0"


def capture_boot_logs(output_path: Path | None = None) -> Path:
    """
    Capture boot logs from current boot session.

    Uses journalctl to get logs from boot start until now.
    Saves to a temporary file that won't persist across reboots.

    Args:
        output_path: Optional path to save logs. If None, uses /tmp.

    Returns:
        Path to the captured log file.
    """
    if output_path is None:
        # Use /tmp which is typically tmpfs and cleared on reboot
        output_path = Path(tempfile.gettempdir()) / f"boot_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    # Capture journal logs from current boot
    # -b 0 = current boot
    # --no-pager = don't paginate
    # -p 0..4 = emerg, alert, crit, err, warning (skip info/debug for analysis)
    # Also get priority 5 (notice) and 6 (info) for context
    result = subprocess.run(
        [
            "journalctl",
            "-b", "0",           # Current boot only
            "--no-pager",
            "-o", "short-iso",   # Timestamp format
        ],
        capture_output=True,
        text=True
    )

    # Write to file
    output_path.write_text(result.stdout)

    return output_path


def capture_priority_logs(output_path: Path | None = None, max_priority: int = 4) -> Path:
    """
    Capture only warning/error level logs from current boot.

    Args:
        output_path: Optional path to save logs.
        max_priority: Maximum priority level (0=emerg, 4=warning, 6=info).

    Returns:
        Path to the captured log file.
    """
    if output_path is None:
        output_path = Path(tempfile.gettempdir()) / f"boot_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    result = subprocess.run(
        [
            "journalctl",
            "-b", "0",
            "--no-pager",
            "-p", f"0..{max_priority}",  # Only warnings and above
            "-o", "short-iso",
        ],
        capture_output=True,
        text=True
    )

    output_path.write_text(result.stdout)
    return output_path


def get_dmesg_logs() -> str:
    """Get kernel ring buffer logs."""
    result = subprocess.run(
        ["dmesg", "--time-format=iso", "--nopager"],
        capture_output=True,
        text=True
    )
    return result.stdout


def get_failed_services() -> str:
    """Get list of failed systemd services."""
    result = subprocess.run(
        ["systemctl", "--failed", "--no-pager"],
        capture_output=True,
        text=True
    )
    return result.stdout


if __name__ == "__main__":
    # Test log capture
    log_path = capture_boot_logs()
    print(f"Boot logs captured to: {log_path}")
    print(f"File size: {log_path.stat().st_size} bytes")

    error_path = capture_priority_logs()
    print(f"Error logs captured to: {error_path}")
    print(f"File size: {error_path.stat().st_size} bytes")
