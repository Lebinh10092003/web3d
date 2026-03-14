@echo off
setlocal
echo OpenClaw WhatsApp login
echo.
echo Scan the QR in WhatsApp: Linked Devices.
echo Keep this window open until login completes.
echo.
openclaw.cmd channels login --channel whatsapp --verbose
echo.
pause

