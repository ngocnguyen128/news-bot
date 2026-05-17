#!/bin/bash
# Script cập nhật code từ GitHub và restart bot
set -e

echo "=== Pulling latest code ==="
git pull origin main

echo "=== Installing/updating dependencies ==="
pip install -r requirements.txt

echo "=== Restarting bot service ==="
systemctl restart telegram-bot

echo "=== Done! Bot restarted ==="
systemctl status telegram-bot --no-pager
