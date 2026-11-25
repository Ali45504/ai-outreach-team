# -*- coding: utf-8 -*-
"""
Builds the n8n workflow "USA Outreach - Daily Team" (the visible team), and runs it.
  python -I build_team_workflow.py build   -> create/update it and switch the DAILY schedule on
  python -I build_team_workflow.py now     -> run the whole team once right now (temporary copy)
The flow (left to right in n8n):
  Triggers -> read Google Sheet (the owner's edits) + read Gmail (4 days) -> files
  Agent 3 Reply Handler -> Manager 3 -> Agent 4 Recorder sync -> Manager 4
  -> Agent 1 Selector -> Manager 1 -> Agent 2 Copywriter -> Manager 2 Quality Critic -> Senior Manager gate
  -> send list -> one email at a time (Gmail API, paced) -> results file
  -> Agent 4 Recorder finalize -> Manager 4 -> write both Google Sheet tabs -> Senior Manager daily report -> email to the owner
A manager that fails exits with an error, which stops the line before anything is sent.
"""
import sys, os, json, copy
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import n8n_api as N

ROOT = os.path.normpath(os.path.join(HERE, ".."))
CFG = json.load(open(os.path.join(ROOT, "config", "outreach_settings.json"), encoding="utf-8"))
REGION = CFG["region"]
SHEETS = json.load(open(os.path.join(ROOT, "data", "sheets.json"), encoding="utf-8"))[REGION]
PY = os.environ.get("PYTHON_EXE", sys.executable)   # full python path, n8n Execute Command needs it
P = ROOT.replace("\\", "/")
NAME = f"{REGION} Outreach - Daily Team"


def cmd(script, *args):
    return f'"{PY}" -I "{ROOT}\\agents\\{script}" {REGION} ' + " ".join(args)


def f(rel):
    return f"{P}/{rel}"


nodes, conns = [], {}


def node(name, typ, ver, params, x, y, **extra):
    n = {"parameters": params, "id": f"n{len(nodes)}", "name": name, "type": typ, "typeVersion": ver, "position": [x, y]}
    n.update(extra)
    nodes.append(n)
    return name


def link(a, b, out=0):
    conns.setdefault(a, {"main": []})
    while len(conns[a]["main"]) <= out:
        conns[a]["main"].append([])
    conns[a]["main"][out].append({"node": b, "type": "main", "index": 0})


def chain(*names):
    for a, b in zip(names, names[1:]):
        link(a, b)


def code(name, js, x, y, **extra):
    return node(name, "n8n-nodes-base.code", 2, {"mode": "runOnceForAllItems", "jsCode": js}, x, y, **extra)


def exe(name, command, x, y):
    return node(name, "n8n-nodes-base.executeCommand", 1, {"command": command}, x, y, executeOnce=True)


def to_file(name, x, y):
    return node(name, "n8n-nodes-base.convertToFile", 1.1, {"operation": "toJson", "options": {}}, x, y, executeOnce=False)


def write_file(name, path, x, y):
    return node(name, "n8n-nodes-base.readWriteFile", 1, {"operation": "write", "fileName": path, "options": {}}, x, y)


def read_file(name, path, x, y):
    return node(name, "n8n-nodes-base.readWriteFile", 1, {"fileSelector": path, "options": {}}, x, y, executeOnce=True)


def extract(name, x, y):
    return node(name, "n8n-nodes-base.extractFromFile", 1, {"operation": "fromJson", "options": {}}, x, y)


def sheet_read(name, tab, x, y):
    return node(name, "n8n-nodes-base.googleSheets", 4.5,
                {"resource": "sheet", "operation": "read",
                 "documentId": {"__rl": True, "mode": "id", "value": SHEETS["output_id"]},
                 "sheetName": {"__rl": True, "mode": "name", "value": tab}, "options": {}},
                x, y, credentials=N.CRED_SHEETS, executeOnce=True, alwaysOutputData=True)


def sheet_clear(name, tab, x, y):
    return node(name, "n8n-nodes-base.googleSheets", 4.5,
                {"resource": "sheet", "operation": "clear",
                 "documentId": {"__rl": True, "mode": "id", "value": SHEETS["output_id"]},
                 "sheetName": {"__rl": True, "mode": "name", "value": tab}, "clear": "wholeSheet"},
                x, y, credentials=N.CRED_SHEETS, executeOnce=True, alwaysOutputData=True)


def sheet_append(name, tab, x, y):
    return node(name, "n8n-nodes-base.googleSheets", 4.5,
                {"resource": "sheet", "operation": "append",
                 "documentId": {"__rl": True, "mode": "id", "value": SHEETS["output_id"]},
                 "sheetName": {"__rl": True, "mode": "name", "value": tab},
                 "columns": {"mappingMode": "autoMapInputData", "value": {}},
                 "options": {"cellFormat": "RAW"}},          # plain text: Google must not turn +phones into numbers/formulas
                x, y, credentials=N.CRED_SHEETS, alwaysOutputData=True)


SLIM_GMAIL = r"""
const pick = v => v == null ? '' : (typeof v === 'string' ? v : (v.text || (v.value || []).map(x => x.address).join(', ') || JSON.stringify(v)));
const out = [];
for (const it of $input.all()) {
  const j = it.json;
  if (j && j.error) {   // Gmail refused (rate limit): the team goes on, but knows replies were not read this run
    out.push({ json: { gmail_error: String(j.error.message || j.error).slice(0, 300) } });
    continue;
  }
  if (!j || !j.id) continue;
  out.push({ json: { id: j.id, threadId: j.threadId, labelIds: j.labelIds || [], from: pick(j.from ?? j.From),
    to: pick(j.to ?? j.To), subject: j.subject ?? j.Subject ?? '', date: j.date ?? j.Date ?? '',
    has_image: /cid:|<img/i.test(String(j.html || '')) || (j.attachments || []).length > 0 || Object.keys(it.binary || {}).length > 0,
    text: String(j.text ?? j.snippet ?? '').slice(0, 6000) } });
}
return out.length ? out : [{ json: {} }];
"""

SPLIT_LIST = "const d = $input.first().json.data; const a = Array.isArray(d) ? d : (d ? [d] : []); return a.length ? a.map(r => ({ json: r })) : [{ json: { action: 'none', pause: 0 } }];"

BUILD_MIME = r"""
const j = $input.first().json;
const b64 = s => Buffer.from(String(s), 'utf8').toString('base64');
const url64 = s => s.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
if (!j.action || j.action === 'none') {
  return [{ json: Object.assign({}, j, { method: 'GET', api_url: 'https://gmail.googleapis.com/gmail/v1/users/me/profile', api_body: {} }) }];
}
const lines = [
  'From: %(name)s <%(sender)s>',
  'To: ' + j.email,
  'Subject: =?UTF-8?B?' + b64(j.subject) + '?=',
  'MIME-Version: 1.0',
  'Content-Type: text/plain; charset="UTF-8"',
  'Content-Transfer-Encoding: base64',
  '',
  b64(j.body)
];
const raw = url64(Buffer.from(lines.join('\r\n'), 'utf8').toString('base64'));
const msg = { raw };
if (j.thread_id && j.action !== 'send_new' && j.action !== 'draft_new') msg.threadId = j.thread_id;
const isDraft = j.action.startsWith('draft');
return [{ json: Object.assign({}, j, {
  method: 'POST',
  api_url: isDraft ? 'https://gmail.googleapis.com/gmail/v1/users/me/drafts' : 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
  api_body: isDraft ? { message: msg } : msg }) }];
""" % {"name": CFG["sender_name"], "sender": CFG["sender_email"]}

RECORD = r"""
const src = $('Build the email').first().json;
const r = $input.first().json || {};
const id = r.id || (r.message && r.message.id) || '';
return [{ json: { key: src.key, action: src.action, email: src.email, name: src.name, subject: src.subject,
  gmail_id: src.action === 'none' ? '' : (r.message ? r.message.id : id),
  draft_id: r.message ? r.id : '', thread_id: r.threadId || (r.message && r.message.threadId) || '',
  error: r.error ? JSON.stringify(r.error).slice(0, 300) : '' } }];
"""

REPORT_MIME = r"""
const line = String($input.first().json.stdout || '').trim().split('\n').pop();
const r = JSON.parse(line);
const b64 = s => Buffer.from(String(s), 'utf8').toString('base64');
const mime = ['To: ' + r.to, 'Subject: =?UTF-8?B?' + b64(r.subject) + '?=', 'MIME-Version: 1.0',
  'Content-Type: text/plain; charset="UTF-8"', 'Content-Transfer-Encoding: base64', '', b64(r.body)].join('\r\n');
const raw = Buffer.from(mime, 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
return [{ json: { raw } }];
"""


def gmail_api(name, x, y, url_expr, body_expr, method_expr="POST", on_error=True):
    params = {"method": method_expr, "url": url_expr,
              "authentication": "predefinedCredentialType", "nodeCredentialType": "gmailOAuth2",
              "sendBody": True, "specifyBody": "json", "jsonBody": body_expr, "options": {}}
    extra = {"credentials": N.CRED_GMAIL}
    if on_error:
        extra["onError"] = "continueRegularOutput"
    return node(name, "n8n-nodes-base.httpRequest", 4.2, params, x, y, **extra)


def build():
    nodes.clear(); conns.clear()
    hh, mm = CFG["daily_run_time_new_york"].split(":")
    node("Every day (New York time)", "n8n-nodes-base.scheduleTrigger", 1.2,
         {"rule": {"interval": [{"field": "cronExpression", "expression": f"{int(mm)} {int(hh)} * * *"}]}}, 0, 0)
    node("Run now (button)", "n8n-nodes-base.manualTrigger", 1, {}, 0, 200)

    # --- 1. read the world -------------------------------------------------
    sheet_read("Read sheet: Outreaching", f"Outreaching {REGION}", 260, 100)
    to_file("Pack Outreaching", 480, 100)
    write_file("Save Outreaching snapshot", f(f"data/{REGION}/inbox/sheet_outreaching.json"), 700, 100)
    sheet_read("Read sheet: Ready to work", "Ready to work", 920, 100)
    to_file("Pack Ready", 1140, 100)
    write_file("Save Ready snapshot", f(f"data/{REGION}/inbox/sheet_ready.json"), 1360, 100)
    node("Read Gmail (last days)", "n8n-nodes-base.gmail", 2.1,
         {"resource": "message", "operation": "getAll", "returnAll": True, "simple": False,
          "filters": {"q": f"(in:sent OR (in:inbox -from:me)) newer_than:{CFG['gmail_lookback_days']}d "
                           "-category:promotions -category:social -category:updates -category:forums"},
          "options": {}}, 1580, 100, credentials=N.CRED_GMAIL, executeOnce=True, alwaysOutputData=True,
         retryOnFail=True, maxTries=3, waitBetweenTries=5000, onError="continueRegularOutput")
    code("Keep what matters", SLIM_GMAIL, 1800, 100)
    to_file("Pack Gmail", 2020, 100)
    write_file("Save Gmail snapshot", f(f"data/{REGION}/inbox/gmail_recent.json"), 2240, 100)
    link("Every day (New York time)", "Read sheet: Outreaching")
    link("Run now (button)", "Read sheet: Outreaching")
    chain("Read sheet: Outreaching", "Pack Outreaching", "Save Outreaching snapshot", "Read sheet: Ready to work",
          "Pack Ready", "Save Ready snapshot", "Read Gmail (last days)", "Keep what matters", "Pack Gmail",
          "Save Gmail snapshot")

    # --- 2. the team ---------------------------------------------------------
    team = [("Agent 3 · Reply Handler", cmd("3_Reply_Handler\\agent.py")),
            ("Manager 3 · checks replies", cmd("3_Reply_Handler\\manager.py")),
            ("Agent 4 · Recorder (sync)", cmd("4_Recorder\\agent.py", "sync")),
            ("Manager 4 · checks sync", cmd("4_Recorder\\manager.py", "sync")),
            ("Agent 1 · Selector", cmd("1_Selector\\agent.py")),
            ("Manager 1 · checks selection", cmd("1_Selector\\manager.py")),
            ("Agent 2 · Copywriter", cmd("2_Copywriter\\agent.py")),
            ("Manager 2 · Quality Critic", cmd("2_Copywriter\\manager.py")),
            ("Senior Manager · final gate", cmd("5_Senior_Manager\\agent.py", "gate"))]
    for i, (nm, c) in enumerate(team):
        exe(nm, c, 260 + i * 220, 380)
    link("Save Gmail snapshot", team[0][0])
    chain(*[t[0] for t in team])

    # --- 3. sending, one at a time --------------------------------------------
    read_file("Load send list", f(f"data/{REGION}/today/05_send_batch.json"), 260, 660)
    extract("Open send list", 480, 660)
    code("One item per email", SPLIT_LIST, 700, 660)
    node("One email at a time", "n8n-nodes-base.splitInBatches", 3, {"batchSize": 1, "options": {}}, 920, 660)
    code("Build the email", BUILD_MIME, 1140, 760)
    gmail_api("Gmail: send or draft", 1360, 760, "={{ $json.api_url }}", "={{ JSON.stringify($json.api_body) }}",
              method_expr="={{ $json.method }}")
    code("Record result", RECORD, 1580, 760)
    node("Pause between emails", "n8n-nodes-base.wait", 1.1,
         {"resume": "timeInterval", "amount": "={{ $('One email at a time').first().json.pause || 1 }}", "unit": "seconds"},
         1800, 760, webhookId="7d3c1e2a-9b4f-4c6d-8e1a-2f3b4c5d6e7f")
    code("Collect results", "return $input.all().map(i => ({ json: i.json }));", 1140, 560)
    to_file("Pack results", 1360, 560)
    write_file("Save send results", f(f"data/{REGION}/today/06_send_results.json"), 1580, 560)
    link(team[-1][0], "Load send list")
    chain("Load send list", "Open send list", "One item per email", "One email at a time")
    link("One email at a time", "Collect results", out=0)          # done
    link("One email at a time", "Build the email", out=1)          # loop
    chain("Build the email", "Gmail: send or draft", "Record result", "Pause between emails", "One email at a time")
    chain("Collect results", "Pack results", "Save send results")

    # --- 4. record + write the sheet + report -----------------------------------
    exe("Agent 4 · Recorder (finalize)", cmd("4_Recorder\\agent.py", "finalize"), 260, 940)
    exe("Manager 4 · checks final sheet", cmd("4_Recorder\\manager.py", "finalize"), 480, 940)
    read_file("Load Outreaching rows", f(f"output/sheet_{REGION}_outreaching.json"), 700, 940)
    extract("Open Outreaching rows", 920, 940)
    sheet_clear("Clear tab: Outreaching", f"Outreaching {REGION}", 1140, 940)
    code("Rows for Outreaching", "return ($('Open Outreaching rows').first().json.data || []).map(r => ({ json: r }));", 1360, 940)
    sheet_append("Write tab: Outreaching", f"Outreaching {REGION}", 1580, 940)
    read_file("Load Ready rows", f(f"output/sheet_{REGION}_ready.json"), 1800, 940)
    extract("Open Ready rows", 2020, 940)
    sheet_clear("Clear tab: Ready to work", "Ready to work", 2240, 940)
    code("Rows for Ready", "return ($('Open Ready rows').first().json.data || []).map(r => ({ json: r }));", 2460, 940)
    sheet_append("Write tab: Ready to work", "Ready to work", 2680, 940)
    exe("Senior Manager · daily report", cmd("5_Senior_Manager\\agent.py", "report"), 2900, 940)
    code("Report email", REPORT_MIME, 3120, 940)
    gmail_api("Email the report to the owner", 3340, 940, "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
              "={{ JSON.stringify({ raw: $json.raw }) }}")
    link("Save send results", "Agent 4 · Recorder (finalize)")
    chain("Agent 4 · Recorder (finalize)", "Manager 4 · checks final sheet", "Load Outreaching rows",
          "Open Outreaching rows", "Clear tab: Outreaching", "Rows for Outreaching", "Write tab: Outreaching",
          "Load Ready rows", "Open Ready rows", "Clear tab: Ready to work", "Rows for Ready", "Write tab: Ready to work",
          "Senior Manager · daily report", "Report email", "Email the report to the owner")
    for n in nodes:   # nodes after a multi-row step must run once, not once per row
        if n["name"] in ("Load Ready rows", "Senior Manager · daily report", "Agent 4 · Recorder (finalize)",
                         "Load send list", "Report email", "Email the report to the owner", "Collect results"):
            n["executeOnce"] = n["name"] not in ("Collect results",)
    for n in nodes:   # one short line under each node, so the canvas explains itself
        if n["name"] in NODE_NOTES:
            n["notes"], n["notesInFlow"] = NODE_NOTES[n["name"]], True
    for n in nodes:   # layout only: each stage gets its own band, with room for its heading
        x, y = n["position"]
        if n["name"] == "Every day (New York time)":
            n["position"] = [0, 300]
        elif n["name"] == "Run now (button)":
            n["position"] = [0, 470]
        elif 560 <= y <= 760:
            n["position"] = [x, y + 140]
        elif y == 940:
            n["position"] = [x, 1180]
    for i, (title, x, y, w, h, color) in enumerate(STICKIES):
        nodes.append({"parameters": {"content": title, "width": w, "height": h, "color": color},
                      "id": f"sticky{i}", "name": f"Note {i + 1}", "type": "n8n-nodes-base.stickyNote",
                      "typeVersion": 1, "position": [x, y]})
    return copy.deepcopy(nodes), copy.deepcopy(conns)


ALERT_NAME = f"{REGION} Outreach - Error alert"


def build_alert():
    """Small separate workflow n8n runs automatically when the Daily Team fails (settings.errorWorkflow).
    Emails the owner which step stopped and the managers' own reasons. Needs no activation."""
    nodes.clear(); conns.clear()
    node("When the daily team fails", "n8n-nodes-base.errorTrigger", 1, {}, 0, 300)
    clean = ("{{ String(($json.execution.error && $json.execution.error.message) || '')"
             ".replace(/[\"%\\r\\n]/g, ' ').slice(0, 300) }}")
    node("Night Watch · why did it stop", "n8n-nodes-base.executeCommand", 1,
         {"command": f'="{PY}" -I "{ROOT}\\scripts\\why_stopped.py" {REGION} '
                     '"{{ String($json.execution.lastNodeExecuted || \'\').replace(/[\\"%]/g, \' \') }}" "' + clean + '"'},
         240, 300, executeOnce=True)
    code("Alert email", REPORT_MIME, 480, 300)
    gmail_api("Email the alert to the owner", 720, 300, "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
              "={{ JSON.stringify({ raw: $json.raw }) }}", on_error=False)
    chain("When the daily team fails", "Night Watch · why did it stop", "Alert email", "Email the alert to the owner")
    nodes.append({"parameters": {"content": "## ERROR ALERT\nn8n runs this by itself when **USA Outreach - Daily Team** "
                                            "stops. It emails you which step stopped and the managers' reasons. "
                                            "Nothing to click here.", "width": 960, "height": 320, "color": 2},
                  "id": "stickyA", "name": "Note", "type": "n8n-nodes-base.stickyNote", "typeVersion": 1,
                  "position": [-60, 120]})
    return copy.deepcopy(nodes), copy.deepcopy(conns)


# ---- what the owner reads on the canvas (headings behind each stage + one line under each node) ----
STICKIES = [
    ("## HOW TO RUN\nClick **Execute workflow** (bottom). Run it as often as you like, 3 or 4 times a day is fine.\n\n"
     "- Max **25 new emails per 24 hours** in total, later runs only read replies and update the sheet.\n"
     "- It also runs by itself every day at 10:00 New York (18:00 Moscow).\n"
     "- One run at a time: wait until the last node is green.\n"
     "- Red node = that stage stopped on purpose. Click it to read why, or ask Claude.",
     -540, 0, 680, 680, 4),
    ("## 1  READ   ·   sheet + Gmail\nReads both sheet tabs (to keep YOUR edits) and the last 4 days of Gmail "
     "(sent mail + replies). Saves a snapshot for the team. If Gmail is busy the run still goes on.",
     200, 0, 2220, 280, 7),
    ("## 2  THE TEAM   ·   every agent has a manager\nAgent 3 reads replies and drafts answers · Agent 4 updates memory · "
     "Agent 1 picks who to email · Agent 2 writes the emails · Senior Manager lets nothing out unless every manager passed. "
     "A manager that finds a problem turns red and STOPS the line, nothing is sent.",
     200, 290, 2220, 310, 6),
    ("## 3  SEND   ·   one by one\nSends (or drafts) each approved email, about 5 a minute. Negotiation replies are always "
     "drafts for you. Nothing here when the 25 of the day are already done.",
     200, 620, 1800, 460, 5),
    ("## 4  RECORD + SHEET + REPORT\nRecords what was sent, rewrites both tabs of the Google Sheet (rows that need a new email "
     "at the bottom), and emails you the daily report.",
     200, 1100, 3320, 280, 3),
]

NODE_NOTES = {
    "Every day (New York time)": "automatic, 10:00 NY",
    "Run now (button)": "or click Execute workflow",
    "Read sheet: Outreaching": "your edits are kept",
    "Read Gmail (last days)": "sent mail + replies",
    "Agent 3 · Reply Handler": "reads replies, drafts answers",
    "Manager 3 · checks replies": "prices really in the email?",
    "Agent 4 · Recorder (sync)": "updates team memory",
    "Manager 4 · checks sync": "no row lost, edits kept",
    "Agent 1 · Selector": "who gets an email today",
    "Manager 1 · checks selection": "max 25, nobody twice",
    "Agent 2 · Copywriter": "writes each email",
    "Manager 2 · Quality Critic": "blocks rule breaks",
    "Senior Manager · final gate": "all managers passed?",
    "One email at a time": "loop",
    "Gmail: send or draft": "5 a minute",
    "Agent 4 · Recorder (finalize)": "records the sends",
    "Manager 4 · checks final sheet": "checks before writing",
    "Write tab: Outreaching": "Google Sheet tab 1",
    "Write tab: Ready to work": "Google Sheet tab 2",
    "Senior Manager · daily report": "writes the report",
    "Email the report to the owner": "to your inbox",
}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    if mode == "build":
        an, ac = build_alert()
        alert_id = N.upsert_workflow(ALERT_NAME, an, ac)
    else:
        w = N.find_workflow(ALERT_NAME)
        alert_id = w["id"] if w else None
    settings = {"errorWorkflow": alert_id} if alert_id else {}
    ns, cs = build()
    if mode == "build":
        wid = N.upsert_workflow(NAME, ns, cs, settings)
        N.activate(wid)
        print(json.dumps({"workflow": NAME, "id": wid, "daily_at_new_york": CFG["daily_run_time_new_york"],
                          "active": True, "error_alert_workflow": alert_id, "url": f"http://localhost:5678/workflow/{wid}"}))
    elif mode == "now":
        tmp = NAME + " (run now)"
        ns = [n for n in ns if n["name"] != "Run now (button)"]
        cs.pop("Run now (button)", None)
        ex = N.fire_once(tmp, ns, cs, trigger_name="Every day (New York time)", max_wait=3600, settings=settings)
        rd = ex["data"]["resultData"]
        last = rd.get("lastNodeExecuted")
        err = (rd.get("error") or {}).get("message")
        print(json.dumps({"finished_at_node": last, "error": err}))
        w = N.find_workflow(tmp)
        if w:
            N.api("DELETE", f"/workflows/{w['id']}")
