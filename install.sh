#!/bin/bash
# Installation script for Press Projector System

set -e

echo "Press Projector System - Installation Script"
echo "============================================="

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    echo "Error: pip3 is required but not installed."
    exit 1
fi

echo "Installing Python dependencies..."
pip3 install -r requirements.txt

echo "Setting up directories..."
mkdir -p config jobs uploads frontend/templates frontend/static

echo "Making scripts executable..."
chmod +x start_server.py
chmod +x test_system.py

echo "Running system tests..."
python3 test_system.py

if [ $? -eq 0 ]; then
    echo ""
    echo "Installation completed successfully!"
    echo ""
    echo "To start the server:"
    echo "  python3 start_server.py"
    echo ""
    echo "To start with custom settings:"
    echo "  python3 start_server.py --host 0.0.0.0 --port 5000"
    echo ""
    echo "Control interface: http://localhost:5000/control"
    echo "Projector view: http://localhost:5000/projector"
else
    echo ""
    echo "Installation completed with errors. Please check the output above."
    exit 1
fi
