# Agent 1 · Selector

**Job:** decide WHO gets an email today. Nothing else.

**Reports to:** Manager 1 (below), then the Senior Manager.

**Reads:** `output/Influencer_USA.json` (fresh from the Recorder's morning sync), the team memory,
the suppression list, and the full Gmail history scan (`data/gmail_scan.json`).

**Writes:** `data/USA/today/01_selected.json`

## Skills
- Picks up to **25 new people** (setting `daily_new_limit`) from "Outreaching USA" with status
  "To contact", in sheet order.
- Picks **follow-ups**: people emailed by the team at least 4 days ago, no reply, no follow-up yet.
- Spreads risk: at most 2 first emails a day to the same company domain (agencies manage many creators).

## Never selects
- Anyone already emailed (team memory, Gmail history, Partner logs), talking, declined, bounced.
- Anyone in "Ready to work" or with a contact number.
- Invalid or role addresses (press@, legal@, support@, noreply@...).
- The same email twice.

## Manager 1 checks
1. New ≤ 25 and follow-ups ≤ their limit.
2. Every pick is valid, unique, not suppressed, not already contacted, not in Ready to work.
3. Domain spread rule respected.
Any breach stops the line (nothing is sent).
