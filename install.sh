#!/bin/bash
# Install/Update Ubuntu Boot Monitoring Agent
# This script builds the .deb, installs it, configures the service, and sets up the API key

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="ubuntu-boot-agent"
CONFIG_DIR="$HOME/.config/$APP_NAME"

echo "========================================"
echo "Ubuntu Boot Monitoring Agent Installer"
echo "========================================"
echo ""

# Check if this is an update
if dpkg -l | grep -q "$APP_NAME"; then
    echo "Detected existing installation - will update"
    IS_UPDATE=true
else
    IS_UPDATE=false
fi

# Build the package
echo "Building Debian package..."
./build-deb.sh

# Install the package
echo ""
echo "Installing package (requires sudo)..."
sudo dpkg -i dist/ubuntu-boot-agent_*.deb
sudo apt-get install -f -y

# Update desktop database for menu entry
echo "Updating desktop database..."
sudo update-desktop-database 2>/dev/null || true

# Create config directory
mkdir -p "$CONFIG_DIR"

# Check for existing API key
EXISTING_KEY=""
if [ -f "$CONFIG_DIR/config.json" ]; then
    EXISTING_KEY=$(python3 -c "import json; print(json.load(open('$CONFIG_DIR/config.json')).get('openrouter_api_key', ''))" 2>/dev/null || true)
fi

# API key configuration
echo ""
if [ -n "$EXISTING_KEY" ]; then
    echo "Existing API key found."
    read -p "Update API key? [y/N]: " UPDATE_KEY
    if [[ "$UPDATE_KEY" =~ ^[Yy]$ ]]; then
        read -p "Enter OpenRouter API key: " -s API_KEY
        echo ""
    else
        API_KEY="$EXISTING_KEY"
    fi
else
    echo "No API key configured."
    echo "Get your API key from: https://openrouter.ai/keys"
    read -p "Enter OpenRouter API key (or press Enter to skip): " -s API_KEY
    echo ""
fi

# Save API key if provided
if [ -n "$API_KEY" ]; then
    python3 -c "
import json
from pathlib import Path

config_file = Path('$CONFIG_DIR/config.json')
config = {}
if config_file.exists():
    try:
        config = json.loads(config_file.read_text())
    except:
        pass
config['openrouter_api_key'] = '$API_KEY'
config_file.write_text(json.dumps(config, indent=2))
"
    echo "API key saved to $CONFIG_DIR/config.json"
fi

# Service setup
echo ""
echo "Systemd user service configuration:"
echo "  The service runs 3 minutes after boot to analyze logs."
echo ""

# Check current service status
SERVICE_ENABLED=false
if systemctl --user is-enabled "$APP_NAME.service" &>/dev/null; then
    SERVICE_ENABLED=true
fi

if [ "$SERVICE_ENABLED" = true ]; then
    echo "Service is currently ENABLED"
    read -p "Keep service enabled? [Y/n]: " KEEP_SERVICE
    if [[ "$KEEP_SERVICE" =~ ^[Nn]$ ]]; then
        systemctl --user disable "$APP_NAME.service"
        echo "Service disabled"
    else
        # Reload in case service file was updated
        systemctl --user daemon-reload
        echo "Service remains enabled"
    fi
else
    echo "Service is currently DISABLED"
    read -p "Enable autostart on boot? [y/N]: " ENABLE_SERVICE
    if [[ "$ENABLE_SERVICE" =~ ^[Yy]$ ]]; then
        systemctl --user daemon-reload
        systemctl --user enable "$APP_NAME.service"
        echo "Service enabled - will run 3 minutes after boot"
    fi
fi

echo ""
echo "========================================"
echo "Installation complete!"
echo "========================================"
echo ""
echo "Usage:"
echo "  Run manually:    ubuntu-boot-agent"
echo "  From menu:       Applications > System > Ubuntu Boot Monitoring Agent"
echo ""
echo "Service management:"
echo "  Enable:   systemctl --user enable $APP_NAME.service"
echo "  Disable:  systemctl --user disable $APP_NAME.service"
echo "  Status:   systemctl --user status $APP_NAME.service"
echo ""
echo "Configuration:"
echo "  Config dir: $CONFIG_DIR"
echo "  Settings available in app via Settings button"
echo ""
