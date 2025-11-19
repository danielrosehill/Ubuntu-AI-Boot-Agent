"""Main entry point for Ubuntu Boot Monitoring Agent."""

import argparse
import sys
import time
from pathlib import Path

from .gui import main as gui_main
from .log_capture import capture_boot_logs, capture_priority_logs, get_failed_services
from .analyzer import analyze_logs


def cli_main():
    """CLI entry point with options."""
    parser = argparse.ArgumentParser(
        description="Ubuntu Boot Monitoring Agent - AI-powered boot log analysis"
    )

    parser.add_argument(
        "--delay",
        type=int,
        default=0,
        help="Delay in seconds before starting analysis (default: 0, use 180 for autostart)"
    )

    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run in CLI mode without GUI"
    )

    parser.add_argument(
        "--capture-only",
        action="store_true",
        help="Only capture logs, don't analyze"
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Output path for captured logs"
    )

    args = parser.parse_args()

    # Apply delay if specified
    if args.delay > 0:
        print(f"Waiting {args.delay} seconds before analysis...")
        time.sleep(args.delay)

    if args.capture_only:
        # Just capture logs
        log_path = capture_boot_logs(args.output)
        print(f"Boot logs captured to: {log_path}")
        return 0

    if args.no_gui:
        # CLI mode
        import json

        print("Capturing boot logs...")
        log_path = capture_priority_logs()
        log_content = log_path.read_text()
        failed_services = get_failed_services()

        print("Analyzing logs with AI...")
        results = analyze_logs(log_content, failed_services)

        print("\n" + "=" * 60)
        print("BOOT LOG ANALYSIS RESULTS")
        print("=" * 60 + "\n")

        print(f"Summary: {results.get('summary', 'No summary')}\n")

        issues = results.get("issues", [])
        if not issues:
            print("No significant issues detected.")
        else:
            for i, issue in enumerate(issues, 1):
                severity = issue.get("severity", "notice").upper()
                print(f"[{severity}] Issue #{i}: {issue.get('problem', 'Unknown')}")
                if details := issue.get("details"):
                    print(f"  Details: {details}")
                if remediation := issue.get("remediation"):
                    print(f"  Remediation: {remediation}")
                print()

        return 0
    else:
        # GUI mode
        gui_main()
        return 0


def main():
    """Main entry point."""
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
