# -*- coding: utf-8 -*-
"""
EMPLOYEE: Publisher  (n8n workflow "Outreach - Publish <REGION>")
JOB: put the region files into Google Sheets on the OUTREACH account (your outreach Gmail):
  - "Influencer <REGION> raw"  : one tab "Raw (all sources)"           (the INPUT)
  - "Influencer <REGION>"      : tabs "Outreaching <REGION>" + "Ready to work"  (the OUTPUT)
How: a throwaway local web server (127.0.0.1 only) hands the JSON files to n8n, because
AutomateJoy's n8n cannot read big local files directly. n8n creates the spreadsheets and
writes the rows with the Google Sheets credential. Spreadsheet ids are saved to
data/sheets.json so the daily run updates the same files instead of making new ones.
USAGE: python -I publish_region.py USA
"""
import sys, os, json, threading, functools, http.server, socketserver
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import n8n_api as N

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PORT = 8765


def serve(folder):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=folder)
    handler.log_message = lambda *a, **k: None
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def sheet_node(nid, name, x, y, doc_expr, tab):
    return {"parameters": {"resource": "sheet", "operation": "append",
                           "documentId": {"__rl": True, "mode": "id", "value": doc_expr},
                           "sheetName": {"__rl": True, "mode": "name", "value": tab},
                           "columns": {"mappingMode": "autoMapInputData", "value": {}}, "options": {"cellFormat": "RAW"}},
            "id": nid, "name": name, "type": "n8n-nodes-base.googleSheets", "typeVersion": 4.5,
            "position": [x, y], "credentials": N.CRED_SHEETS}


def build(region):
    url = f"http://127.0.0.1:{PORT}/"
    tab_out = f"Outreaching {region}"
    nodes = [
        {"parameters": {"rule": {"interval": [{"field": "minutes", "minutesInterval": 1}]}},
         "id": "t", "name": "Trigger", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [100, 300]},
        {"parameters": {"resource": "spreadsheet", "operation": "create", "title": f"Influencer {region}",
                        "sheetsUi": {"sheetValues": [{"title": tab_out}, {"title": "Ready to work"}]}, "options": {}},
         "id": "c1", "name": "Create output sheet", "type": "n8n-nodes-base.googleSheets", "typeVersion": 4.5,
         "position": [300, 200], "credentials": N.CRED_SHEETS},
        {"parameters": {"resource": "spreadsheet", "operation": "create", "title": f"Influencer {region} raw",
                        "sheetsUi": {"sheetValues": [{"title": "Raw (all sources)"}]}, "options": {}},
         "id": "c2", "name": "Create raw sheet", "type": "n8n-nodes-base.googleSheets", "typeVersion": 4.5,
         "position": [500, 200], "credentials": N.CRED_SHEETS},
        {"parameters": {"url": url + f"Influencer_{region}.json", "options": {"timeout": 120000}},
         "id": "h1", "name": "Get output rows", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [700, 200]},
        {"parameters": {"mode": "runOnceForAllItems", "jsCode": "return $input.first().json.outreaching.map(r => ({json: r}));"},
         "id": "s1", "name": "Outreaching rows", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [900, 100]},
        sheet_node("w1", "Write Outreaching tab", 1100, 100, "={{ $('Create output sheet').first().json.spreadsheetId }}", tab_out),
        {"parameters": {"mode": "runOnceForAllItems", "jsCode": "const r = $('Get output rows').first().json.ready; return (r.length ? r : []).map(x => ({json: x}));"},
         "id": "s2", "name": "Ready rows", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1300, 100]},
        sheet_node("w2", "Write Ready tab", 1500, 100, "={{ $('Create output sheet').first().json.spreadsheetId }}", "Ready to work"),
        {"parameters": {"url": url + f"Influencer_{region}_raw.json", "options": {"timeout": 120000}},
         "id": "h2", "name": "Get raw rows", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [1700, 100]},
        {"parameters": {"mode": "runOnceForAllItems", "jsCode": "return $input.all().filter(i => i.json && Object.keys(i.json).length).map(i => ({json: i.json}));"},
         "id": "s3", "name": "Raw rows", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1900, 100]},
        sheet_node("w3", "Write raw tab", 2100, 100, "={{ $('Create raw sheet').first().json.spreadsheetId }}", "Raw (all sources)"),
        {"parameters": {"mode": "runOnceForAllItems", "jsCode":
            "return [{json:{output_id: $('Create output sheet').first().json.spreadsheetId, output_url: $('Create output sheet').first().json.spreadsheetUrl,"
            " raw_id: $('Create raw sheet').first().json.spreadsheetId, raw_url: $('Create raw sheet').first().json.spreadsheetUrl,"
            " outreaching_rows: $('Outreaching rows').all().length, ready_rows: $('Ready rows').all().length, raw_rows: $('Raw rows').all().length}}];"},
         "id": "d", "name": "Done", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [2300, 100]},
    ]
    chain = ["Trigger", "Create output sheet", "Create raw sheet", "Get output rows", "Outreaching rows",
             "Write Outreaching tab", "Ready rows", "Write Ready tab", "Get raw rows", "Raw rows", "Write raw tab", "Done"]
    conns = {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(chain, chain[1:])}
    # nodes that must run ONCE, not once per incoming row
    for n in nodes:
        if n["name"] in ("Create output sheet", "Create raw sheet", "Get output rows", "Get raw rows"):
            n["executeOnce"] = True
    # a node with zero input items stops the chain, so keep going even when a tab is empty
    for n in nodes:
        if n["name"] in ("Write Outreaching tab", "Write Ready tab", "Write raw tab", "Ready rows", "Raw rows"):
            n["alwaysOutputData"] = True
    return nodes, conns


def build_update(region, ids):
    """Same files every day: clear each tab, then write the fresh rows into the SAME spreadsheets."""
    url = f"http://127.0.0.1:{PORT}/"
    tab_out = f"Outreaching {region}"
    out_id, raw_id = ids["output_id"], ids["raw_id"]

    def clear(nid, name, doc, tab, x):
        return {"parameters": {"resource": "sheet", "operation": "clear",
                               "documentId": {"__rl": True, "mode": "id", "value": doc},
                               "sheetName": {"__rl": True, "mode": "name", "value": tab}, "clear": "wholeSheet"},
                "id": nid, "name": name, "type": "n8n-nodes-base.googleSheets", "typeVersion": 4.5,
                "position": [x, 300], "credentials": N.CRED_SHEETS, "executeOnce": True, "alwaysOutputData": True}

    nodes = [
        {"parameters": {}, "id": "t", "name": "Trigger", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [100, 300]},
        {"parameters": {"url": url + f"Influencer_{region}.json", "options": {"timeout": 120000}},
         "id": "h1", "name": "Get output rows", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
         "position": [300, 300], "executeOnce": True},
        clear("c1", "Clear Outreaching tab", out_id, tab_out, 500),
        {"parameters": {"mode": "runOnceForAllItems", "jsCode": "return $('Get output rows').first().json.outreaching.map(r => ({json: r}));"},
         "id": "s1", "name": "Outreaching rows", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [700, 300]},
        sheet_node("w1", "Write Outreaching tab", 900, 300, out_id, tab_out),
        clear("c2", "Clear Ready tab", out_id, "Ready to work", 1100),
        {"parameters": {"mode": "runOnceForAllItems", "jsCode": "return $('Get output rows').first().json.ready.map(r => ({json: r}));"},
         "id": "s2", "name": "Ready rows", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1300, 300]},
        sheet_node("w2", "Write Ready tab", 1500, 300, out_id, "Ready to work"),
        clear("c3", "Clear raw tab", raw_id, "Raw (all sources)", 1700),
        {"parameters": {"url": url + f"Influencer_{region}_raw.json", "options": {"timeout": 120000}},
         "id": "h2", "name": "Get raw rows", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
         "position": [1900, 300], "executeOnce": True},
        {"parameters": {"mode": "runOnceForAllItems", "jsCode": "return $input.all().filter(i => i.json && Object.keys(i.json).length).map(i => ({json: i.json}));"},
         "id": "s3", "name": "Raw rows", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [2100, 300]},
        sheet_node("w3", "Write raw tab", 2300, 300, raw_id, "Raw (all sources)"),
        {"parameters": {"mode": "runOnceForAllItems", "jsCode":
            f"return [{{json:{{output_id:'{out_id}', output_url:'{ids.get('output_url','')}', raw_id:'{raw_id}', raw_url:'{ids.get('raw_url','')}',"
            " outreaching_rows: $('Outreaching rows').all().length, ready_rows: $('Ready rows').all().length, raw_rows: $('Raw rows').all().length}}];"},
         "id": "d", "name": "Done", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [2500, 300]},
    ]
    for n in nodes:
        if n["name"].startswith("Write") or n["name"].endswith("rows"):
            n["alwaysOutputData"] = True
    chain = [n["name"] for n in nodes]
    return nodes, {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(chain, chain[1:])}


if __name__ == "__main__":
    region = (sys.argv[1] if len(sys.argv) > 1 else "USA").upper()
    reg_path = os.path.join(ROOT, "data", "sheets.json")
    known = json.load(open(reg_path, encoding="utf-8")).get(region) if os.path.exists(reg_path) else None
    httpd = serve(os.path.join(ROOT, "output"))
    try:
        nodes, conns = build_update(region, known) if known else build(region)
        if known:
            print("updating existing sheets for", region, flush=True)
        print("publishing", region, "to Google Sheets (outreach account) ...", flush=True)
        ex = N.fire_once(f"Outreach - Publish {region}", nodes, conns, trigger_name="Trigger")
        r = N.last_node_output(ex, "Done")[0]
    finally:
        httpd.shutdown()
    reg = os.path.join(ROOT, "data", "sheets.json")
    allr = json.load(open(reg, encoding="utf-8")) if os.path.exists(reg) else {}
    allr[region] = r
    json.dump(allr, open(reg, "w", encoding="utf-8"), indent=1)
    print(json.dumps(r, indent=1))
