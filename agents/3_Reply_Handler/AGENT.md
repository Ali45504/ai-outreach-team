# Agent 3 · Reply Handler

**Job:** read every new reply in the outreach inbox and turn it into clean information plus a
negotiation draft for the owner.

**Reports to:** Manager 3 (below), then the Senior Manager.

**Reads:** `data/USA/inbox/gmail_recent.json` (written by n8n from Gmail, last 4 days)
and the team memory `data/USA/state/outreach_state.json`.

**Writes:** `data/USA/today/03_reply_events.json`

## Skills
- Sorts each reply into: rates given · interested no rates · question · not interested ·
  auto reply · bounce · unclear.
- Pulls out every price exactly as written, WhatsApp / Telegram / phone, US audience share, demands.
- Drafts the reply using `knowledge/03_NEGOTIATION_PLAYBOOK.md`: lowest real price,
  performance based first, ask for real numbers, never accept on the spot.
- Uses a free AI model (Groq / Cerebras via automation/engine.py) to read the message,
  with rule based checks first and after (no Claude tokens).

## Rules (from knowledge/01 and 06)
- Never invent a price or contact. A price is only kept if its number is literally in the reply.
- Auto replies are not conversations. The creator stays "emailed".
- "Not interested" goes to the suppression list. Nobody on it is ever emailed again.
- Every reply draft is a Gmail DRAFT. The owner negotiates money himself.

## Manager 3 checks
1. Every new reply in the inbox got a decision (nothing silently skipped).
2. Every saved price really appears in the reply text.
3. Every draft passes the compliance check (no promises, no dashes, no dollar sign, no links).
4. No draft exists for auto replies, bounces or unclear messages.
Bad drafts are removed and flagged for the owner. A broken file stops the line.
