"""Smoke-test the MCP server over stdio JSON-RPC, the way an MCP client would."""
import json
import subprocess
import sys

msgs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "handoff_history", "arguments": {"person": "pwang347", "limit": 2}}},
]
p = subprocess.Popen([sys.executable, "-m", "handoff_graph.mcp_server"], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
for m in msgs:
    p.stdin.write(json.dumps(m) + "\n")
    p.stdin.flush()
    if "id" in m:
        reply = json.loads(p.stdout.readline())
        if m["id"] == 1:
            print("server:", reply["result"]["serverInfo"])
        elif m["id"] == 2:
            print("tools:", [t["name"] for t in reply["result"]["tools"]])
        else:
            r = reply["result"]
            print("call:", json.dumps(r.get("structuredContent") or r["content"])[:300])
p.terminate()
