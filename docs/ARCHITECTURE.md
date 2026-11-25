# Architecture notes

## Building blocks
- **n8n** runs the order of work: triggers, Google Sheets and Gmail access, the sending loop, the sheet
  rewrite and the error alert. Credentials live in n8n's own vault.
- **Agents are small Python programs** called by n8n one after another. They hand work to each other
  through files in a working folder, so every step leaves a record you can open and check.
- **Managers** are separate programs that read what their agent produced and exit with a failure when a
  rule is broken. n8n stops the line on that failure, before anything reaches a person.

## Team memory
Every contact has one status in the memory: drafted, emailed, talking, declined (or open to future
offers), bounced, failed to send. The memory decides who is never emailed again, who gets one follow up
after a set number of days, and which tab of the sheet a row belongs to. Memory is never deleted.

## The sheet
Two tabs. **Outreaching**: people to contact first, then waiting, then closed, and at the bottom every
row that needs a new email from a human (missing, bounced or failed). **Ready to work**: people talking
or reachable directly, with price, contacts and notes. Before every run the team compares the sheet with
what it last wrote, so anything a human changed is kept.

## Reading replies safely
Replies are cut at the quoted part, so the team only reads what the creator wrote. A free model sorts the
reply and suggests prices and contacts, then plain rules verify them: a price survives only if its numbers
are literally in the email, phone numbers must look like phone numbers (not dates or ids in links),
and replies with images are flagged for a human. Long running conversations are flagged instead of
answered with a template.

## Safety
- Daily limit counted across all runs of the day, max per company domain.
- One run at a time (a lock), released by the last step or by any failure.
- Gmail busy: the run continues without replies, follow ups wait until replies are read again.
- Gmail busy while sending: the person is retried next run, never marked as failed.
- Error workflow: any stop sends an email with the step and the managers' own reasons.
