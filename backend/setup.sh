#!/bin/bash
# Backend setup script

set -e

echo "Setting up backend virtual environment..."

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    if ! python3 -m venv venv; then
        echo ""
        echo "❌ Virtual environment creation failed."
        echo ""
        echo "Please install python3-venv first:"
        echo "  sudo apt install python3.12-venv"
        echo ""
        echo "Or if that doesn't work:"
        echo "  sudo apt install python3-venv"
        echo ""
        echo "After installing, run this script again:"
        echo "  ./setup.sh"
        exit 1
    fi
else
    echo "Virtual environment already exists"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "✅ Backend setup complete!"
echo ""
echo "To activate the virtual environment in the future, run:"
echo "  source venv/bin/activate"
echo ""
echo "To run the backend server:"
echo "  uvicorn app.main:app --reload --port 8000"

