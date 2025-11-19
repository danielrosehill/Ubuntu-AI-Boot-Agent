#!/bin/bash
# Run script for Ubuntu Boot Monitoring Agent

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check for .env
if [ ! -f ".env" ]; then
    echo "Warning: No .env file found. Create one with OPENROUTER_API_KEY=your-key"
fi

# Run the application
exec uv run python -m app.ubuntu_boot_agent "$@"
