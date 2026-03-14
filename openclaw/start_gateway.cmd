@echo off
setlocal
echo Starting OpenClaw gateway on ws://127.0.0.1:18789
echo.
openclaw.cmd gateway run --force
