#!/bin/bash
set -e
echo "Installing Node.js..."
apt-get update -qq 2>/dev/null
apt-get install -y -qq nodejs npm 2>/dev/null
echo "Installing Chromium..."
apt-get install -y -qq chromium 2>/dev/null
echo "Installing Lighthouse..."
npm install -g lighthouse 2>/dev/null
echo "=== Verify ==="
which node && node --version
which npx
which chromium || which chromium-browser || echo "chromium path TBD"
npx lighthouse --version 2>&1 || echo "lighthouse version check failed"
echo "DONE"

