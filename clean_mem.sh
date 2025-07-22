#!/bin/sh
echo "Starting Clean Mem..."
pkill -9 chrome
pkill -9 chromium
pkill -9 thorium
pkill -9 "thorium-browser"
pkill -9 "Google Chrome"
pkill -9 "google chrome"
pkill -9 "playwright"
pkill -9 node
pkill -9 nodejs

echo "Finished Cleaning Mem..."
