# -*- coding: utf-8 -*-
"""
Launcher for the n8n-mcp connector (czlonkowski/n8n-mcp, pinned 2.103.2) used by Claude via .mcp.json.
Why a launcher: the n8n API key stays ONLY in secrets.env (project rule), never in a config file.
Settings:
  - WEBHOOK_SECURITY_MODE=moderate: allows localhost (our n8n), still blocks private IPs and cloud metadata
  - telemetry OFF (by default it sends usage data to the author)
  - tools switched off: deleting workflows, credentials, data tables, variables, agents, folders
    (not needed, and credentials would expose secrets)
Talks MCP over stdin/stdout, so this script prints nothing itself.
"""
import os, sys, subprocess

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
NODE_DIR = r"C:\Program Files\nodejs"

keys = {}
for line in open(os.path.join(ROOT, "secrets.env"), encoding="utf-8"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        keys[k.strip()] = v.strip().strip('"')

env = dict(os.environ)
env["PATH"] = NODE_DIR + os.pathsep + env.get("PATH", "")
env.update({
    "MCP_MODE": "stdio",
    "LOG_LEVEL": "error",
    "DISABLE_CONSOLE_OUTPUT": "true",
    "N8N_MCP_TELEMETRY_DISABLED": "true",
    "WEBHOOK_SECURITY_MODE": "moderate",
    "N8N_API_URL": keys.get("N8N_API_URL", "http://localhost:5678").rstrip("/").removesuffix("/api/v1"),
    "N8N_API_KEY": keys["N8N_API_KEY"],
    "DISABLED_TOOLS": "n8n_delete_workflow,n8n_manage_credentials,n8n_manage_datatable,"
                      "n8n_manage_variables,n8n_manage_agents,n8n_manage_folders",
})
sys.exit(subprocess.run([os.path.join(NODE_DIR, "npx.cmd"), "-y", "n8n-mcp@2.103.2"], env=env).returncode)
