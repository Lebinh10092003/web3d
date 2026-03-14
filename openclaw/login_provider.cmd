@echo off
setlocal
echo OpenClaw provider login
echo.
echo This must run in a real interactive terminal.
echo Choose your provider or OAuth flow in the prompts that follow.
echo.
openclaw.cmd configure --section model
echo.
pause

