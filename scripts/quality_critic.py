# -*- coding: utf-8 -*-
"""
EMPLOYEE: Quality Critic  (outreach compliance gate)
-----------------------------------------------------------------------------
JOB DESCRIPTION
  Checks every creator-facing email draft BEFORE it is allowed to become a
  Gmail draft. If it FAILS, the draft goes back to the Copywriter, never to a
  creator. This is the quality gate.
  Reports to : the n8n Outreach Manager workflow.
  Skill set  : The owner's OUTREACH_OS_BRAIN rules + a free second-opinion model.
  Cost       : 0 Claude tokens (uses automation/engine.py).

RULES ENFORCED (from the outreach policy)
  - No dashes, no parentheses, no brackets, no "$".
  - No income promises or guaranteed returns. The compliance word is "simulated".
  - Must ask the three discovery questions: US audience %, rate, preferred deal.
  - Must carry the signature with your Telegram handle.
  - No blank fill-ins left for the owner (e.g. [name], TODO, XXXX, <...>).

INPUT   a JSON array of drafts [{"name","subject","body"}] via a file path arg
        or stdin.  Or:  python quality_critic.py --demo
OUTPUT  one JSON array of verdicts to stdout:
        [{"name","passed","score","problems":[...],"llm_notes":"..."}]
"""
import sys, os, json, re

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "llm"))
try:
    _SIGN = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config",
                      "outreach_settings.json"), encoding="utf-8")).get("telegram_handle", "").lower()
except Exception:
    _SIGN = ""
try:
    import engine  # free model caller (Groq / Cerebras / Gemini ...)
except Exception:
    engine = None

BANNED = [r"guarantee", r"guaranteed", r"\bprofits?\b", r"\bprofitable\b",
          r"make money", r"risk[- ]free", r"double your", r"\breturns?\b",
          r"\bwin[- ]rate\b", r"drawdown"]
FILLIN = [r"\[[^\]]+\]", r"\bTODO\b", r"\bXXXX?\b", r"<[^>]+>", r"\bFIRST[_ ]?NAME\b"]
DISCOVERY = {
    "US audience %": r"(audience .*\bu\.?s\.?\b|part of your audience|in the us|united states)",
    "rate / price": r"(charge|rate|price|how much|cost)",
    "deal type": r"(performance|flat fee|revenue share|rev[- ]share|\bboth\b|deal)",
}

def deterministic(subject, body):
    text = (subject or "") + "\n" + (body or ""); low = text.lower(); p = []
    if re.search(r"[\u2013\u2014]", text) or " - " in text:
        p.append("Contains a dash. Use commas or full sentences.")
    if "(" in text or ")" in text: p.append("Contains parentheses. Remove them.")
    if "[" in text or "]" in text: p.append("Contains brackets. Remove them.")
    if "$" in text: p.append("Contains the dollar sign.")
    for b in BANNED:
        if re.search(b, low): p.append("Compliance risk phrase: " + b.replace("\\b", "").replace("[- ]", " "))
    for f in FILLIN:
        if re.search(f, text, re.I): p.append("Unfilled placeholder left in the draft.")
    missing = [k for k, rx in DISCOVERY.items() if not re.search(rx, low)]
    if missing: p.append("Missing discovery question(s): " + ", ".join(missing))
    if _SIGN and _SIGN not in low: p.append("Signature / Telegram " + _SIGN + " missing.")
    m = re.search(r"(?<![@\w.])((?:www\.)?[a-z0-9-]+\.(?:com|net|io|co|ai|org|me|gg|tv))\b", low)
    if m: p.append("Website link in the email (" + m.group(1) + "). Remove it, bare domains get auto-wrapped by Gmail into ugly tracking links.")
    return p


_WEB = re.compile(r"(?<![@\w.])((?:www\.)?[a-z0-9-]+\.(?:com|net|io|co|ai|org|me|gg|tv))\b", re.I)


def autofix(text):
    """Mechanically clean the SAFE rule breaks: dashes, parentheses, brackets, dollar signs,
    and website links. Does NOT touch wording, so missing questions or risky phrases still fail."""
    if not text:
        return text
    t = text.replace(" - ", ", ").replace("—", ", ").replace("–", ", ")
    t = _WEB.sub("", t)
    for ch in "()[]$":
        t = t.replace(ch, "")
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = "\n".join(ln.rstrip() for ln in t.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def review_and_fix(subject, body):
    """Auto-clean the draft, then re-check. Returns (fixed_subject, fixed_body, problems_left, passed)."""
    fs, fb = autofix(subject), autofix(body)
    problems = deterministic(fs, fb)
    return fs, fb, problems, (len(problems) == 0)

LLM_SYSTEM = ("You are a strict outreach editor for an independent creator partnerships specialist "
    "writing a warm first email to a skeptical creator. Fail the draft if it sounds like AI, is vague, "
    "has a weak first line, or breaks compliance (no income promise, the word is simulated). "
    "Reply in this exact format and nothing else:\nVERDICT: PASS or FAIL\nNOTES:\n- one note per line, or none")

def llm_notes(subject, body):
    if engine is None: return "VERDICT: PASS\nNOTES:\n- engine unavailable, deterministic checks only"
    try:
        return engine.ask("cerebras_qwen", LLM_SYSTEM, "SUBJECT: " + subject + "\n\nBODY:\n" + body, max_tokens=400)
    except Exception as e:
        return "VERDICT: PASS\nNOTES:\n- llm check skipped: " + str(e)[:50]

def review(d):
    subject, body = d.get("subject", ""), d.get("body", "")
    probs = deterministic(subject, body)
    notes = llm_notes(subject, body)
    llm_fail = "VERDICT: FAIL" in notes.upper()
    passed = (not probs) and (not llm_fail)
    score = max(0, 100 - 20 * len(probs) - (25 if llm_fail else 0))
    return {"name": d.get("name", ""), "passed": passed, "score": score,
            "problems": probs, "llm_notes": notes.strip()}

DEMO = [
    {"name": "BAD draft", "subject": "A quick collab idea",
     "body": "Hi there - I guarantee you will profit $500 fast. Reply (if interested)."},
    {"name": "GOOD draft", "subject": "A quick collab idea for Jake",
     "body": ("Hi Jake,\n\nI help creators team up with brands that genuinely fit them. Right now I am "
              "working with a new US brand that launches next month, and I "
              "really like how you cover trading, so I wanted to reach out early.\n\nA few quick things. "
              "What part of your audience is in the US, roughly? What do you charge for a dedicated video, "
              "and for a shorter shoutout? Are you open to a performance based deal, a flat fee, or both?\n\n"
              "No rush at all. Reply here or message me on Telegram @YourTelegram.\n\nThanks,\nYour Name")},
]

def main():
    if "--demo" in sys.argv: data = DEMO
    elif len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        data = json.load(open(sys.argv[1], encoding="utf-8"))
    else:
        raw = sys.stdin.read(); data = json.loads(raw) if raw.strip() else []
    if isinstance(data, dict): data = [data]
    print(json.dumps([review(d) for d in data], ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
