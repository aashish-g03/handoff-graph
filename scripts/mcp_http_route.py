"""Call route_issue on a deployed MCP server: python scripts/mcp_http_route.py https://host/mcp"""
import json
import sys
import urllib.request

URL = sys.argv[1]


def post(body, sid=None):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        h["mcp-session-id"] = sid
    r = urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), h), timeout=90)
    raw, sid = r.read().decode(), r.headers.get("mcp-session-id") or sid
    data = [line[5:] for line in raw.splitlines() if line.startswith("data:")] or [raw]
    return (json.loads(data[-1]) if data[-1].strip() else None), sid


_, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}}})
post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
res, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "route_issue", "arguments": {
    "title": "Tab titles render with no text in the new modern UI",
    "body": "After enabling the new modern workbench UI, editor tab titles appear blank until hovered. macOS.",
    "proposed_assignee": "benibenj"}}}, sid)
print(json.dumps(res["result"].get("structuredContent", res["result"]), indent=1)[:1500])
