# OpenClaw Natural Blog Intents Design

**Date:** 2026-03-18

## Goal

Allow the OpenClaw WhatsApp operator agent to understand natural-language blog instructions without requiring `/blogpost`, `/blogpreview`, or `/blogpublish`, while keeping chat relay behavior and blog publishing safety intact.

## Current Constraints

- The Django automation bridge can create a blog request and can preview or publish only when a `request_id` is known.
- The current OpenClaw workspace instructions explicitly forbid blog actions unless the message starts with slash commands.
- Natural phrases such as `Dang bai vua viet len web` therefore cannot be resolved reliably today.

## Approved Behavior

### Intent routing

- `#W...` remains the only format for customer chat relay replies.
- Natural-language blog requests are allowed in addition to slash commands.
- Slash commands remain supported as explicit shorthand.
- Casual chat must not trigger a publish action.

### Blog safety

- If the message clearly expresses publish intent, the agent may publish immediately.
- If intent is not clearly publish, the agent defaults to `review`.
- When the operator refers to `bai vua viet`, `bai moi nhat`, or equivalent, the agent must resolve that to the latest blog request from the same WhatsApp chat only.
- If no matching blog request exists for that chat, the agent must not guess.

### Latest-in-chat lookup

- The Django automation bridge becomes the source of truth for `latest blog request in this WhatsApp chat`.
- Resolution is based on:
  - `source_channel=whatsapp`
  - `requested_by=<current WhatsApp number>`
- Only created automation runs with an attached post are eligible.

## Backend Design

### New endpoints

1. `GET /automation/blog/requests/latest/`
   - Query params: `source_channel`, `requested_by`
   - Returns the same serialized request payload shape as the existing request detail endpoint.
   - Returns `404` when no blog request exists for that chat.

2. `POST /automation/blog/requests/latest/publish/`
   - JSON body: `source_channel`, `requested_by`, optional `publish_at`
   - Finds the latest matching request and publishes or schedules it.
   - Returns the existing post payload plus `request_id`.

### Publish rules

- If `publish_at` is omitted, publish immediately.
- If `publish_at` is in the future, mark the post as `SCHEDULED`.
- If the latest post is already `PUBLISHED` and no future `publish_at` is provided, return success with `already_published=true` instead of mutating it.

## OpenClaw Workspace Design

### AGENTS.md

- Replace the slash-command-only rule with intent classification rules.
- Keep slash commands as supported shorthand.
- Add examples for natural Vietnamese phrases that map to:
  - create draft/review
  - preview latest post in chat
  - publish latest post in chat
  - schedule latest post in chat
- Instruct the agent to use the new latest endpoints for `bai vua viet` style requests instead of relying on conversation memory.

### WHATSAPP_COMMANDS.md

- Reframe the document as supported operator examples rather than mandatory command prefixes.
- Keep slash commands documented.
- Add natural-language Vietnamese examples for the same actions.

### SETUP_CHECKLIST.md and RUNTIME.example.md

- Document the new latest endpoints and the natural-language workflow.
- Clarify that slash commands are optional shortcuts, not the only supported format.

## Error Handling

- Missing required fields for creating a post: ask focused follow-up questions.
- No latest request found for the current chat: reply that no blog draft/request exists in this WhatsApp conversation yet.
- Validation error from Django bridge: relay the short error and do not retry blindly.
- Missing `RUNTIME.md`: ask the operator to configure it and do not guess endpoints or tokens.

## Testing

- Add integration tests for latest lookup and latest publish behavior.
- Verify that latest lookup never crosses WhatsApp chats.
- Verify scheduling via `publish_at`.
- Verify already-published responses.

