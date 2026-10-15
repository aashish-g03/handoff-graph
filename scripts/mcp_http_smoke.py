"""Smoke-test the MCP server over streamable HTTP: python scripts/mcp_http_smoke.py http://host:port/mcp"""
import json
import sys
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765/mcp"


def post(body, sid=None):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        h["mcp-session-id"] = sid
    r = urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), h), timeout=60)
    raw, sid = r.read().decode(), r.headers.get("mcp-session-id") or sid
    data = [line[5:] for line in raw.splitlines() if line.startswith("data:")] or [raw]
    return (json.loads(data[-1]) if data[-1].strip() else None), sid


init, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}}})
print("server", init["result"]["serverInfo"])
post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
tools, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
print("tools", [t["name"] for t in tools["result"]["tools"]])
call, _ = post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "handoff_history", "arguments": {"person": "benibenj", "limit": 2}}}, sid)
print("call", json.dumps(call["result"].get("structuredContent"))[:200])
