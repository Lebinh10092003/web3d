# OpenClaw Natural Blog Intents Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let OpenClaw handle natural-language WhatsApp blog instructions and safely resolve `latest post in this chat` through Django automation endpoints.

**Architecture:** Extend `automation_bridge` with latest-request lookup and publish endpoints keyed by `source_channel` plus `requested_by`, then update OpenClaw workspace instructions to route natural-language blog intents to the correct endpoints. Keep chat relay exact-match behavior unchanged and preserve existing slash-command support as shorthand.

**Tech Stack:** Django, Django test runner, Markdown workspace docs, OpenClaw prompt workspace

---

## Chunk 1: Django Latest Request Resolution

### Task 1: Add failing tests for latest request lookup and publish

**Files:**
- Modify: `automation_bridge/tests.py`
- Test: `automation_bridge/tests.py`

- [x] **Step 1: Write failing tests for latest lookup and publish**

```python
def test_latest_request_detail_filters_by_whatsapp_sender(self):
    ...

def test_latest_request_publish_promotes_latest_post_for_sender(self):
    ...
```

- [x] **Step 2: Run the targeted test module and verify the new tests fail**

Run:
```bash
$env:DJANGO_DEBUG='1'; $env:DB_PASSWORD='abc'; python manage.py test automation_bridge
```

Expected:
- The new latest route tests fail because the routes or views do not exist yet.

- [ ] **Step 3: Commit checkpoint**

```bash
git add automation_bridge/tests.py
git commit -m "test: cover latest blog request bridge flows"
```

### Task 2: Implement latest lookup and publish endpoints

**Files:**
- Modify: `automation_bridge/views.py`
- Modify: `automation_bridge/urls.py`
- Test: `automation_bridge/tests.py`

- [x] **Step 1: Add minimal helpers and routes**

Implement:
- a lookup helper for the latest created automation run by `source_channel` and `requested_by`
- `blog_request_latest_detail`
- `blog_request_latest_publish`

- [x] **Step 2: Re-run the targeted tests and verify they pass**

Run:
```bash
$env:DJANGO_DEBUG='1'; $env:DB_PASSWORD='abc'; python manage.py test automation_bridge
```

Expected:
- All `automation_bridge` tests pass.

- [ ] **Step 3: Commit checkpoint**

```bash
git add automation_bridge/views.py automation_bridge/urls.py automation_bridge/tests.py
git commit -m "feat: add latest blog request bridge endpoints"
```

## Chunk 2: OpenClaw Workspace Instructions

### Task 3: Update OpenClaw prompt rules and operator docs

**Files:**
- Modify: `openclaw/workspace-main/AGENTS.md`
- Modify: `openclaw/workspace-main/WHATSAPP_COMMANDS.md`
- Modify: `openclaw/workspace-main/RUNTIME.example.md`
- Modify: `openclaw/SETUP_CHECKLIST.md`

- [x] **Step 1: Rewrite blog flow instructions for natural-language intents**

Update docs so they:
- allow natural-language blog intents in addition to slash commands
- describe when to default to `review`
- describe when to publish immediately
- instruct the agent to resolve `latest in this chat` through the new Django endpoints

- [x] **Step 2: Review doc examples for consistency**

Check that examples and endpoint names match the implemented Django routes.

- [ ] **Step 3: Commit checkpoint**

```bash
git add openclaw/workspace-main/AGENTS.md openclaw/workspace-main/WHATSAPP_COMMANDS.md openclaw/workspace-main/RUNTIME.example.md openclaw/SETUP_CHECKLIST.md
git commit -m "docs: support natural language blog operations in openclaw"
```

## Chunk 3: Verification

### Task 4: Run focused verification and capture final state

**Files:**
- Modify: `docs/superpowers/plans/2026-03-18-openclaw-natural-blog-intents.md`

- [x] **Step 1: Run the final relevant test command**

Run:
```bash
$env:DJANGO_DEBUG='1'; $env:DB_PASSWORD='abc'; python manage.py test automation_bridge
```

Expected:
- `automation_bridge` passes with 0 failures.

- [x] **Step 2: Update this plan if execution deviated materially**

Record any plan changes or skipped steps caused by environment/tool limits.

- [ ] **Step 3: Commit checkpoint**

```bash
git add docs/superpowers/plans/2026-03-18-openclaw-natural-blog-intents.md
git commit -m "docs: record openclaw natural blog intents plan"
```

## Execution Notes

- Executed in the current session instead of a subagent workflow because delegation was not explicitly requested.
- Verified in an isolated worktree first, then copied the verified changes back into the shared workspace.
- Commit checkpoints were intentionally not executed because the user asked for implementation, not commits.
