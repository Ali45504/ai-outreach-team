# -*- coding: utf-8 -*-
"""Senior Manager. Usage: python -I agent.py USA gate|report"""
import os, sys, json
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")))
import team as T

MUST_PASS = ["manager_3_replies", "manager_4_recorder_sync", "manager_1_selection", "manager_2_quality_critic"]


def rep(region, name):
    return T.load(T.today_file(region, f"report_{name}.json"), {})


def gate(region):
    cfg = T.settings()
    problems = []
    for m in MUST_PASS:
        r = rep(region, m)
        if r.get("status") != "PASS" or r.get("date") != T.TODAY:
            problems.append(f"{m} did not pass today ({r.get('status', 'missing')})")
    if problems:
        T.save(T.today_file(region, "05_send_batch.json"), [{"action": "none", "pause": 0}])
        T.report("Senior Manager gate", "FAIL", region=region, problems=problems)

    st, sup = T.state(region), T.suppression(region)
    drafts = T.load(T.today_file(region, "02_drafts.json"), {})
    replies = T.load(T.today_file(region, "03_reply_events.json"), {})
    send = cfg["send_mode"] == "send"
    pause = int(cfg["seconds_between_sends"]) if send else 2
    batch, seen, held = [], set(), []
    for d in drafts.get("drafts", []):
        e = d["email"]
        if d.get("qc") != "passed":
            held.append(f"{e}: {d.get('qc')}"); continue
        if (e, d["type"]) in seen or e in sup or st.get(e, {}).get("status") in ("talking", "declined", "bounced"):
            held.append(f"{e}: blocked at final gate"); continue
        if d["type"] == "new" and e in st:
            held.append(f"{e}: already in team memory"); continue
        seen.add((e, d["type"]))
        action = ("send_new" if send else "draft_new") if d["type"] == "new" else ("send_followup" if send else "draft_followup")
        batch.append({"key": f"{d['type']}:{e}", "action": action, "email": e, "name": d["name"],
                      "subject": d["subject"], "body": d["body"], "message_id": d.get("message_id", ""),
                      "thread_id": d.get("thread_id", ""), "pause": pause})
    for ev in replies.get("events", []):
        dr = ev.get("draft")
        if dr and dr.get("qc") == "passed":
            batch.append({"key": f"reply:{ev['message_id']}", "action": "draft_reply", "email": dr["to"],
                          "name": "", "subject": dr["subject"], "body": dr["body"],
                          "message_id": dr.get("reply_to_message_id", ""), "thread_id": dr.get("thread_id", ""),
                          "pause": 2})
    new_n = sum(1 for b in batch if b["action"] in ("send_new", "draft_new"))
    if new_n > cfg["daily_new_limit"]:
        T.save(T.today_file(region, "05_send_batch.json"), [{"action": "none", "pause": 0}])
        T.report("Senior Manager gate", "FAIL", region=region, problems=[f"{new_n} first emails over the limit"])
    T.save(T.today_file(region, "05_send_batch.json"), batch or [{"action": "none", "pause": 0}])
    T.report("Senior Manager gate", "PASS", region=region, mode=cfg["send_mode"], first_emails=new_n,
             followups=sum(1 for b in batch if "followup" in b["action"]),
             reply_drafts=sum(1 for b in batch if b["action"] == "draft_reply"), held_back=held[:10])


def report(region):
    cfg = T.settings()
    g, s1 = rep(region, "senior_manager_gate"), rep(region, "agent_1_selector")
    a3, a4 = rep(region, "agent_3_reply_handler"), rep(region, "agent_4_recorder_finalize")
    sync = rep(region, "agent_4_recorder_sync")
    managers = {m: rep(region, m).get("status", "missing") for m in MUST_PASS + ["manager_4_recorder_finalize"]}
    ok = all(v == "PASS" for v in managers.values()) and g.get("status") == "PASS"
    verb = "sent" if cfg["send_mode"] == "send" else "drafted in Gmail (press send)"
    lines = [
        f"USA outreach daily report, {T.TODAY}",
        f"Overall: {'all checks passed' if ok else 'ATTENTION, something was stopped, see below'}",
        "",
        f"First emails {verb}: {a4.get('sent', 0) + a4.get('drafted', 0)}",
        f"Follow-ups: {a4.get('followups', 0)}",
        f"New replies: {a3.get('new_replies', 0)} {json.dumps(a3.get('by_category', {}))}",
        f"Negotiation reply drafts waiting for you in Gmail: {a4.get('reply_drafts', 0)}",
        f"Your sheet edits picked up today: {sync.get('human_edits_found', 0)}",
        f"Send errors: {a4.get('errors', 0)}" + (f" ({len(a4['retry_later'])} only because Gmail was busy, they are tried "
                                                 "again on the next run)" if a4.get("retry_later") else ""),
        "",
        f"Sheet now: Outreaching USA {a4.get('outreaching_rows', '?')} rows, Ready to work {a4.get('ready_rows', '?')} rows",
        f"Still to contact: {a4.get('to_contact', '?')}",
        f"Skipped by the Selector: {json.dumps(s1.get('skipped', {}))}",
        "",
        "Manager checks: " + ", ".join(f"{k} {v}" for k, v in managers.items()),
        f"Final gate: {g.get('status', 'missing')} {('; '.join(g.get('problems', []) + g.get('held_back', [])))[:600]}",
        "",
        f"Sending mode: {cfg['send_mode']}. Change it in config/outreach_settings.json.",
    ] + ([f"Note: {a4['note']}"] if a4.get("note") else []) + ([f"Note: {s1['note']}"] if s1.get("note") else [])
    text = "\n".join(lines)
    path = os.path.join(T.ROOT, "logs", region, f"daily_report_{T.TODAY}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(text + "\n")
    T.release_run_lock(region)          # last step of the line: the next run may start
    T.report("Senior Manager report", "DONE", region=region, to=cfg["report_to"],
             subject=f"USA outreach report {T.TODAY}: {'OK' if ok else 'needs attention'}", body=text)


if __name__ == "__main__":
    region = (sys.argv[1] if len(sys.argv) > 1 else T.settings()["region"]).upper()
    (gate if (sys.argv[2] if len(sys.argv) > 2 else "gate") == "gate" else report)(region)
