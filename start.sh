#!/bin/bash
# Start virtual display (Xvfb) so Chrome runs non-headless without a real monitor
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
sleep 1
export DISPLAY=:99
exec python render_bot.py
