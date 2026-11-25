# -*- coding: utf-8 -*-
"""Tiny helper for the local n8n REST API (AutomateJoy at localhost:5678).
Key is read from n8n task/secrets.env (gitignored). Used by Claude at build time only."""
import json, os, urllib.request, urllib.error

BASE = "http://localhost:5678"
HERE = os.path.dirname(os.path.abspath(__file__))
SECRETS = os.path.join(HERE, "..", "secrets.env")

# Known credential ids in the owner's n8n (ids are not secrets)
def _secret(name):
    if not os.path.exists(SECRETS):
        return ""
    for line in open(SECRETS, encoding="utf-8"):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    return ""


def _cred(name):
    return os.environ.get(name) or _secret(name) or "SET_ME"


CRED_SHEETS = {"googleSheetsOAuth2Api": {"id": _cred("N8N_CRED_SHEETS_ID"), "name": "Google Sheets account"}}
CRED_GMAIL = {"gmailOAuth2": {"id": _cred("N8N_CRED_GMAIL_ID"), "name": "Gmail account"}}


def _key():
    for line in open(SECRETS, encoding="utf-8"):
        if line.startswith("N8N_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("N8N_API_KEY missing in secrets.env")


def api(method, path, body=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + "/api/v1" + path, data=data, method=method,
                                 headers={"X-N8N-API-KEY": _key(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"n8n API {method} {path} -> {e.code}: {e.read().decode('utf-8', 'ignore')[:800]}")


def find_workflow(name):
    for w in api("GET", "/workflows?limit=100").get("data", []):
        if w["name"] == name:
            return w
    return None


def upsert_workflow(name, nodes, connections, settings=None):
    """Create the workflow, or replace it in place if one with this name exists.
    settings can add e.g. errorWorkflow (the workflow n8n runs when this one fails)."""
    body = {"name": name, "nodes": nodes, "connections": connections,
            "settings": dict({"executionOrder": "v1"}, **(settings or {}))}
    old = find_workflow(name)
    if old:
        if old.get("active"):
            api("POST", f"/workflows/{old['id']}/deactivate")
        api("PUT", f"/workflows/{old['id']}", body)
        return old["id"]
    return api("POST", "/workflows", body)["id"]


def activate(wid):
    return api("POST", f"/workflows/{wid}/activate")


def run_once(wid, max_wait=900, poll=10):
    """AutomateJoy does not serve production webhooks, but schedules work.
    So: activate a workflow whose trigger fires every minute, wait for ONE finished
    execution, deactivate, and return that execution (with data)."""
    import time
    before = {e["id"] for e in api("GET", f"/executions?workflowId={wid}&limit=20").get("data", [])}
    activate(wid)
    run_id, waited = None, 0
    try:
        while run_id is None and waited < 180:          # wait for the first run to START
            time.sleep(poll); waited += poll
            new = [e for e in api("GET", f"/executions?workflowId={wid}&limit=5").get("data", [])
                   if e["id"] not in before]
            if new:
                run_id = new[-1]["id"]
    finally:
        api("POST", f"/workflows/{wid}/deactivate")      # stop further minute ticks immediately
    if run_id is None:
        raise SystemExit("schedule never fired")
    waited = 0
    while waited < max_wait:                              # then wait for THAT run to finish
        e = api("GET", f"/executions/{run_id}")
        if e.get("finished") or e.get("stoppedAt"):
            return api("GET", f"/executions/{run_id}?includeData=true", timeout=180)
        time.sleep(poll); waited += poll
    raise SystemExit(f"run {run_id} not finished after {max_wait}s")


def fire_once(name, nodes, connections, trigger_name="Trigger", lead_minutes=2, max_wait=2400, poll=20, settings=None):
    """Run a workflow exactly ONCE without anyone clicking: set its schedule trigger to a
    single cron minute a couple of minutes ahead (n8n timezone America/New_York), activate,
    wait for that one finished execution, deactivate. Cannot overlap, unlike every-minute."""
    import time, datetime, copy
    try:
        from zoneinfo import ZoneInfo
        ny = datetime.datetime.now(ZoneInfo("America/New_York"))
    except Exception:                                   # no tzdata: EST fallback (UTC-5)
        ny = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5)
    at = ny + datetime.timedelta(minutes=lead_minutes)
    cron = f"{at.minute} {at.hour} {at.day} {at.month} *"
    nodes = copy.deepcopy(nodes)
    for n in nodes:
        if n["name"] == trigger_name:
            n["type"], n["typeVersion"] = "n8n-nodes-base.scheduleTrigger", 1.2
            n["parameters"] = {"rule": {"interval": [{"field": "cronExpression", "expression": cron}]}}
    wid = upsert_workflow(name, nodes, connections, settings)
    base = max([int(e["id"]) for e in api("GET", f"/executions?workflowId={wid}&limit=20").get("data", [])] or [0])
    activate(wid)
    print(f"  scheduled single run at {at:%H:%M} New York time (cron '{cron}')", flush=True)
    try:
        waited = 0
        while waited < max_wait:
            time.sleep(poll); waited += poll
            done = [e for e in api("GET", f"/executions?workflowId={wid}&limit=10").get("data", [])
                    if int(e["id"]) > base]
            if done:
                return api("GET", f"/executions/{done[0]['id']}?includeData=true", timeout=180)
        raise SystemExit(f"no finished run after {max_wait}s")
    finally:
        api("POST", f"/workflows/{wid}/deactivate")


def last_node_output(execution, node_name):
    rd = execution["data"]["resultData"]
    if rd.get("error"):
        raise SystemExit("workflow error: " + json.dumps(rd["error"])[:800])
    return [i["json"] for i in rd["runData"][node_name][0]["data"]["main"][0]]


def call_webhook(path, payload=None, timeout=600):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(BASE + "/webhook/" + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"webhook {path} -> {e.code}: {e.read().decode('utf-8', 'ignore')[:800]}")
