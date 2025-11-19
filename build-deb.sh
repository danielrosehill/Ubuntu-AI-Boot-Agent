#!/bin/bash
# Build Debian package for Ubuntu Boot Monitoring Agent

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="ubuntu-boot-agent"
VERSION="0.1.0"
ARCH="amd64"
PKG_DIR="$SCRIPT_DIR/build/${APP_NAME}_${VERSION}_${ARCH}"

echo "Building Debian package for $APP_NAME v$VERSION"
echo "================================================"

# Clean previous builds
rm -rf "$SCRIPT_DIR/build"
mkdir -p "$PKG_DIR"

# Create directory structure
mkdir -p "$PKG_DIR/DEBIAN"
mkdir -p "$PKG_DIR/opt/$APP_NAME"
mkdir -p "$PKG_DIR/usr/bin"
mkdir -p "$PKG_DIR/usr/share/applications"
mkdir -p "$PKG_DIR/usr/lib/systemd/user"

# Build the application with uv
echo "Building Python package..."
uv build --wheel

# Extract wheel to opt directory
echo "Extracting wheel..."
WHEEL=$(ls dist/*.whl | head -1)
unzip -q "$WHEEL" -d "$PKG_DIR/opt/$APP_NAME"

# Copy source files needed for running
cp -r app "$PKG_DIR/opt/$APP_NAME/"
cp pyproject.toml "$PKG_DIR/opt/$APP_NAME/"
cp .python-version "$PKG_DIR/opt/$APP_NAME/" 2>/dev/null || true

# Create launcher script
cat > "$PKG_DIR/usr/bin/$APP_NAME" << 'EOF'
#!/bin/bash
# Ubuntu Boot Monitoring Agent launcher

APP_DIR="/opt/ubuntu-boot-agent"
CONFIG_DIR="$HOME/.config/ubuntu-boot-agent"

# Ensure config directory exists
mkdir -p "$CONFIG_DIR"

# Check for API key in config or environment
if [ -z "$OPENROUTER_API_KEY" ] && [ -f "$CONFIG_DIR/.env" ]; then
    export $(grep -v '^#' "$CONFIG_DIR/.env" | xargs)
fi

# Run with system Python
cd "$APP_DIR"
exec python3 -m app.ubuntu_boot_agent "$@"
EOF

chmod +x "$PKG_DIR/usr/bin/$APP_NAME"

# Create desktop entry
cat > "$PKG_DIR/usr/share/applications/$APP_NAME.desktop" << EOF
[Desktop Entry]
Name=Ubuntu Boot Monitoring Agent
Comment=AI-powered boot log analysis
Exec=$APP_NAME
Icon=utilities-system-monitor
Terminal=false
Type=Application
Categories=System;Utility;
Keywords=boot;logs;monitoring;ai;
EOF

# Create systemd user service
cat > "$PKG_DIR/usr/lib/systemd/user/$APP_NAME.service" << EOF
[Unit]
Description=Ubuntu Boot Monitoring Agent
Documentation=https://github.com/danielrosehill/Ubuntu-AI-Boot-Agent
After=graphical-session.target
Wants=graphical-session.target

[Service]
Type=simple
ExecStartPre=/bin/sleep 180
ExecStart=/usr/bin/$APP_NAME
Restart=no

[Install]
WantedBy=graphical-session.target
EOF

# Create control file
cat > "$PKG_DIR/DEBIAN/control" << EOF
Package: $APP_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.12), python3-pyqt6, python3-httpx, python3-dotenv
Maintainer: Daniel Rosehill <public@danielrosehill.com>
Description: AI-powered boot log analysis for Ubuntu
 Ubuntu Boot Monitoring Agent analyzes system boot logs using AI
 to identify issues and suggest remediations. It runs automatically
 after boot and presents a GUI with actionable recommendations.
Homepage: https://github.com/danielrosehill/Ubuntu-AI-Boot-Agent
EOF

# Create postinst script
cat > "$PKG_DIR/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e

# Create config directory for users
echo "Ubuntu Boot Monitoring Agent installed."
echo ""
echo "To configure:"
echo "  1. Create ~/.config/ubuntu-boot-agent/.env"
echo "  2. Add: OPENROUTER_API_KEY=your-key-here"
echo ""
echo "To enable autostart:"
echo "  systemctl --user enable ubuntu-boot-agent.service"
echo ""
echo "To run manually:"
echo "  ubuntu-boot-agent"

exit 0
EOF
chmod +x "$PKG_DIR/DEBIAN/postinst"

# Create prerm script
cat > "$PKG_DIR/DEBIAN/prerm" << 'EOF'
#!/bin/bash
set -e

# Disable service if enabled
systemctl --user disable ubuntu-boot-agent.service 2>/dev/null || true
systemctl --user stop ubuntu-boot-agent.service 2>/dev/null || true

exit 0
EOF
chmod +x "$PKG_DIR/DEBIAN/prerm"

# Build the package
echo "Building .deb package..."
dpkg-deb --build "$PKG_DIR"

# Move to dist
mkdir -p "$SCRIPT_DIR/dist"
mv "$SCRIPT_DIR/build/${APP_NAME}_${VERSION}_${ARCH}.deb" "$SCRIPT_DIR/dist/"

echo ""
echo "================================================"
echo "Package built successfully!"
echo "Output: dist/${APP_NAME}_${VERSION}_${ARCH}.deb"
echo ""
echo "Install with:"
echo "  sudo dpkg -i dist/${APP_NAME}_${VERSION}_${ARCH}.deb"
echo "  sudo apt-get install -f  # Install dependencies if needed"
