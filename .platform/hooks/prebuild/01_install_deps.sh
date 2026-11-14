#!/bin/bash
# Prebuild hook for Elastic Beanstalk
# Runs before the application is built

set -e

echo "=== Prebuild hook starting ==="

# Ensure we're in the right directory
cd /var/app/staging

# Check Python version
python3 --version

# Upgrade pip
pip install --upgrade pip

# Install dependencies
if [ -f requirements.txt ]; then
    echo "Installing Python dependencies..."
    pip install -r requirements.txt
fi

echo "=== Prebuild hook completed ==="