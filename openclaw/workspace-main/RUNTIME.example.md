# Runtime config

Create a local-only copy of this file as `RUNTIME.md` on the gateway host.
Do not commit `RUNTIME.md`.

## Site
- Public site base URL: `https://stemrobotics.io.vn`

## Operator
- Operator WhatsApp number: `+84374202948`

## Django automation endpoints
- Operator reply endpoint: `https://stemrobotics.io.vn/support-chat/internal/operator-reply/`
- Blog publish endpoint: `https://stemrobotics.io.vn/automation/blog/publish/`
- Blog request detail endpoint template: `https://stemrobotics.io.vn/automation/blog/requests/{request_id}/`
- Blog publish confirm endpoint template: `https://stemrobotics.io.vn/automation/blog/requests/{request_id}/publish/`

## Bearer tokens
- Support chat operator token: `REPLACE_WITH_SUPPORT_CHAT_OPERATOR_TOKEN`
- Blog automation token: `REPLACE_WITH_BLOG_AUTOMATION_TOKEN`

## Rules
- Use the support chat operator token only for the operator reply endpoint.
- Use the blog automation token for blog publish, preview, and publish-confirm endpoints.
- Never reveal these tokens in chat responses.
