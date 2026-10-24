#!/bin/bash
set -e

echo "=========================================="
echo "      News Video Generator - Codespace    "
echo "=========================================="

echo "--> 1. Installing system dependencies (ffmpeg & fonts)..."
sudo apt-get update -y
sudo apt-get install -y ffmpeg fonts-liberation fonts-dejavu-core

echo "--> 2. Installing Python dependencies..."
pip install -r requirements.txt

echo "--> 3. Checking gemini_keys.txt..."
if [ ! -f gemini_keys.txt ]; then
    echo "--------------------------------------------------------"
    echo " ATTENTION: gemini_keys.txt not found!"
    echo " Please create 'gemini_keys.txt' in this folder"
    echo " and paste your Gemini API keys (one per line)."
    echo "--------------------------------------------------------"
fi

echo "--> 4. Launching News Video Generator on port 8501..."
python main.py
