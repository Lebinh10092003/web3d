# OpenClaw Setup Checklist

This repository is ready for the Django side of the integration:
- website chat widget
- operator reply bridge
- blog automation bridge
- review/publish workflow

What is still external and must be completed on the host:

## 1. Install and run OpenClaw
- Install the OpenClaw CLI and gateway on the machine that will keep WhatsApp logged in.
- Recommended docs:
  - https://docs.openclaw.ai/start/wizard
  - https://docs.openclaw.ai/channels/whatsapp

## 2. Connect a model provider
Choose one:
- ChatGPT / Codex sign-in with OpenClaw
- OpenAI API key

Docs:
- https://docs.openclaw.ai/providers/openai

## 3. Connect WhatsApp
- Log in with the operator WhatsApp number.
- Keep the OpenClaw gateway running on the same host or trusted private network.

## 4. Fill Django env vars
Required for live relay:
- SUPPORT_CHAT_OPENCLAW_HOOK_TOKEN
- SUPPORT_CHAT_OWNER_WHATSAPP

Required for blog automation:
- BLOG_AUTOMATION_DEFAULT_AUTHOR_USERNAME
- BLOG_AUTOMATION_TOKEN

Current local defaults are in `.env_local`.

## 5. Optional but recommended for auto-written blog posts
- Add a web search provider to OpenClaw so the agent can research before writing.

Docs:
- https://docs.openclaw.ai/tools/web

## 6. Operator workflow
- Website chat reply:
  - `#W4821 Your reply`
- Blog draft:
  - `/blogpost ...`
- Blog preview:
  - `/blogpreview <request_id>`
- Blog publish:
  - `/blogpublish <request_id>`

Detailed agent rules:
- `openclaw/workspace-main/AGENTS.md`
- `openclaw/workspace-main/WHATSAPP_COMMANDS.md`

## 7. Local verification
Useful commands:

```bash
python manage.py check
python manage.py integration_status
python manage.py runserver
```

## 8. Limits of local-only mode
- Website chat works locally without OpenClaw.
- Blog draft creation works locally without OpenClaw.
- WhatsApp relay does not work until OpenClaw is installed, logged in, and configured.
