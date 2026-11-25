# -*- coding: utf-8 -*-
"""
Shared toolbox for the outreach team (all agents and managers import this).
Holds: settings, file locations, the team memory (who was emailed / talking / declined),
the suppression list, email validity rules and the quality checks.
"""
import os, sys, json, re, datetime, shutil

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import clean_influencers as C            # noqa: E402
import quality_critic as QC              # noqa: E402
from build_region import pkey            # noqa: E402

TODAY = datetime.date.today().isoformat()


# ------------------------------------------------------------------ settings + paths
def settings():
    return json.load(open(os.path.join(ROOT, "config", "outreach_settings.json"), encoding="utf-8"))


def region_dir(region, *parts):
    p = os.path.join(ROOT, "data", region, *parts)
    os.makedirs(os.path.dirname(p) if os.path.splitext(p)[1] else p, exist_ok=True)
    return p


def today_file(region, name):
    return region_dir(region, "today", name)


def inbox_file(region, name):
    return region_dir(region, "inbox", name)


def state_file(region, name):
    return region_dir(region, "state", name)


def load(path, default):
    if not os.path.exists(path):
        return default
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return default
    # files written by n8n "Convert to File / toJson" are arrays of item json
    return d


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def n8n_items(path):
    """n8n writes files as a JSON array of items; Extract-from-File may wrap them as {data:[...]}."""
    d = load(path, [])
    if isinstance(d, dict) and "data" in d:
        d = d["data"]
    if isinstance(d, dict):
        d = [d]
    return [x for x in d if isinstance(x, dict) and x]


def start_new_day(region):
    """Archive yesterday's working files and start a clean 'today' folder."""
    tdir = region_dir(region, "today")
    stamp = os.path.join(tdir, "_date.txt")
    old = open(stamp).read().strip() if os.path.exists(stamp) else ""
    if old and old != TODAY:
        dest = region_dir(region, "history", old)
        for f in os.listdir(tdir):
            shutil.move(os.path.join(tdir, f), os.path.join(dest, f))
    open(stamp, "w").write(TODAY)


# ------------------------------------------------------------------ team memory
def state(region):
    return load(state_file(region, "outreach_state.json"), {})


def save_state(region, st):
    save(state_file(region, "outreach_state.json"), st)


def suppression(region):
    return load(state_file(region, "suppression.json"), {})


def save_suppression(region, sup):
    save(state_file(region, "suppression.json"), sup)


def log_event(rec, event):
    rec.setdefault("history", []).append({"date": TODAY, "event": event})


def row_key(row):
    k = pkey(row.get("Social Profile", ""))
    return k or ("name:" + (row.get("Username") or "").strip().lower())


# ------------------------------------------------------------------ email rules
ROLE_BAD = re.compile(r"^(no-?reply|noreply|donotreply|footage|press|media|legal|privacy|abuse|dmca|careers|jobs|"
                      r"support|help|billing|security|admin|webmaster|postmaster)@", re.I)
FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "proton.me", "protonmail.com",
             "aol.com", "live.com", "msn.com", "gmx.net", "gmx.de", "mail.ru", "yandex.ru", "ymail.com", "me.com"}


def email_ok(e):
    e = (e or "").strip().lower()
    if not C.EMAIL_RE.fullmatch(e):
        return False, "not a valid email"
    if ROLE_BAD.match(e):
        return False, "role address (press/legal/support...)"
    if re.search(r"\.(png|jpe?g|gif|webp)$", e):
        return False, "image file name, not an email"
    return True, ""


def company_domain(e):
    d = (e or "").split("@")[-1].lower()
    return None if d in FREE_MAIL else d


# ------------------------------------------------------------------ quality checks
def qc_outreach(subject, body):
    """First emails: full rule set incl. the 3 discovery questions. Returns fixed text + problems."""
    return QC.review_and_fix(subject, body)


def qc_reply(subject, body):
    """Replies / follow-ups: compliance only (no discovery-question requirement)."""
    fs, fb = QC.autofix(subject), QC.autofix(body)
    probs = [p for p in QC.deterministic(fs, fb) if not p.startswith("Missing discovery")]
    return fs, fb, probs, not probs


def first_name(name, email):
    lp = re.split(r"[._@+\d]", (email or "").lower())[0]
    toks = [t for t in re.split(r"\s+", (name or "").strip()) if t]
    bad = re.compile(r"trade|crypto|bitcoin|money|wealth|stock|fx|forex|invest|market|daily|show|podcast|"
                     r"official|tv|news|media|channel|team|gaming|games|music|studio|club|the$|^the", re.I)
    if toks and len(toks) <= 3 and toks[0].isalpha() and 2 < len(toks[0]) <= 12 and not bad.search(name) \
            and not name.isupper():
        return toks[0].capitalize()
    if lp.isalpha() and 3 <= len(lp) <= 10 and toks and toks[0].lower().startswith(lp):
        return lp.capitalize()
    return ""


# ------------------------------------------------------------------ one run at a time
LOCK_MINUTES = 30      # a lock older than this is from a run that died; it is ignored


def lock_path(region):
    return region_dir(region, "run.lock")


def take_run_lock(region, who):
    """Only one team run (n8n button, schedule, RUN_USA_NOW, SEND_WAITING_DRAFTS) may work at a time.
    Two runs at once mix their files: the second reads an old sheet and sees fake 'human edits'."""
    p = lock_path(region)
    now = datetime.datetime.now()
    if os.path.exists(p):
        info = load(p, {})
        try:
            age = (now - datetime.datetime.fromisoformat(info.get("started", ""))).total_seconds() / 60
        except ValueError:
            age = LOCK_MINUTES
        if age < LOCK_MINUTES:
            print(json.dumps({"agent": "Run lock", "status": "FAIL", "why":
                  f"another run ({info.get('who')}) started at {info.get('started')} and is still working. "
                  f"Nothing was changed. Run again when it is finished (at the latest after {LOCK_MINUTES} minutes)."}))
            sys.exit(1)
        os.remove(p)
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(json.dumps({"agent": "Run lock", "status": "FAIL", "why": "another run started this same second"}))
        sys.exit(1)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"started": now.isoformat(timespec="seconds"), "who": who}, f)


def release_run_lock(region):
    try:
        os.remove(lock_path(region))
    except FileNotFoundError:
        pass


def _crash_frees_lock(kind, value, tb):
    """Any agent that crashes stops the line, so free the lock instead of blocking runs for 30 minutes."""
    try:
        release_run_lock(settings()["region"])
    finally:
        sys.__excepthook__(kind, value, tb)


sys.excepthook = _crash_frees_lock


# ------------------------------------------------------------------ reporting
def report(agent, status, **info):
    """Every agent and manager ends with one JSON line (n8n shows it) and writes it to today's folder."""
    out = dict({"agent": agent, "status": status, "date": TODAY}, **info)
    region = info.get("region") or settings()["region"]
    save(today_file(region, f"report_{agent.replace(' ', '_').lower()}.json"), out)
    print(json.dumps(out, ensure_ascii=True))
    if status == "FAIL":
        release_run_lock(region)       # the line stops here, so free it for the next run
        sys.exit(1)
