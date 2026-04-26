"""
Estate 3.0 Wiki MCP Server — uses official Anthropic mcp package (not fastmcp).
"""

import os
import sqlite3
from contextlib import contextmanager

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

DB_PATH = os.environ.get("WIKI_DB", "/data/wiki.sqlite")

server = Server("estate3-wiki")


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


# ── tool implementations (sync, called from async handlers) ──────────────────

def _list_components() -> str:
    with db() as con:
        rows = con.execute(
            "SELECT run, component, file, type, tags FROM components ORDER BY run, component"
        ).fetchall()
    lines = ["Run | Component | File | Type | Tags", "----|-----------|------|------|-----"]
    for r in rows:
        lines.append(f"{r['run']} | {r['component']} | {r['file']} | {r['type']} | {r['tags']}")
    return "\n".join(lines)


def _get_component(name: str) -> str:
    with db() as con:
        row = con.execute(
            "SELECT * FROM components WHERE component LIKE ? LIMIT 1",
            (f"%{name}%",)
        ).fetchone()
        if not row:
            return f"No component matching '{name}'. Use list_components() to see all."
        cid = row["id"]
        funcs   = con.execute("SELECT name, signature, does FROM functions WHERE component_id=?", (cid,)).fetchall()
        configs = con.execute("SELECT param, default_val, effect FROM config_params WHERE component_id=?", (cid,)).fetchall()
        gotchas = con.execute("SELECT text FROM gotchas WHERE component_id=?", (cid,)).fetchall()
        ifaces  = con.execute("SELECT direction, name, from_to, itype FROM interfaces WHERE component_id=?", (cid,)).fetchall()

    out = [
        f"# {row['component']}",
        f"**File:** {row['file']}  |  **Type:** {row['type']}  |  **Tags:** {row['tags']}",
        f"\n## Purpose\n{row['purpose']}",
    ]
    if ifaces:
        out += ["\n## Interfaces", "Direction | Name | From/To | Type", "----------|------|---------|-----"]
        for i in ifaces:
            out.append(f"{i['direction']} | {i['name']} | {i['from_to']} | {i['itype']}")
    if funcs:
        out += ["\n## Functions", "Name | Signature | Does", "-----|-----------|-----"]
        for f in funcs:
            out.append(f"{f['name']} | {f['signature']} | {f['does']}")
    if configs:
        out += ["\n## Config", "Param | Default | Effect", "------|---------|-------"]
        for c in configs:
            out.append(f"{c['param']} | {c['default_val']} | {c['effect']}")
    if gotchas:
        out.append("\n## Gotchas")
        for g in gotchas:
            out.append(f"- {g['text']}")
    return "\n".join(out)


def _search_gotchas(keyword: str) -> str:
    with db() as con:
        rows = con.execute(
            """SELECT c.component, c.file, g.text
               FROM gotchas g JOIN components c ON c.id = g.component_id
               WHERE lower(g.text) LIKE lower(?) ORDER BY c.component""",
            (f"%{keyword}%",)
        ).fetchall()
    if not rows:
        return f"No gotchas matching '{keyword}'."
    out = [f"Found {len(rows)} gotcha(s) matching '{keyword}':\n"]
    for r in rows:
        out.append(f"**[{r['component']}]** ({r['file']})\n  {r['text']}\n")
    return "\n".join(out)


def _search_wiki(query: str) -> str:
    like = f"%{query}%"
    with db() as con:
        comps = con.execute(
            "SELECT 'component' as src, component as label, file, purpose as snippet FROM components "
            "WHERE lower(component) LIKE lower(?) OR lower(purpose) LIKE lower(?) LIMIT 5",
            (like, like)
        ).fetchall()
        funcs = con.execute(
            "SELECT 'function' as src, f.name as label, c.file, f.does as snippet "
            "FROM functions f JOIN components c ON c.id=f.component_id "
            "WHERE lower(f.name) LIKE lower(?) OR lower(f.does) LIKE lower(?) LIMIT 5",
            (like, like)
        ).fetchall()
        gotchas = con.execute(
            "SELECT 'gotcha' as src, c.component as label, c.file, g.text as snippet "
            "FROM gotchas g JOIN components c ON c.id=g.component_id "
            "WHERE lower(g.text) LIKE lower(?) LIMIT 5",
            (like,)
        ).fetchall()
    results = list(comps) + list(funcs) + list(gotchas)
    if not results:
        return f"Nothing found for '{query}'. Try list_components() to browse."
    out = [f"Search results for '{query}' ({len(results)} hits):\n"]
    for r in results:
        snippet = r['snippet'] or ''
        out.append(f"[{r['src'].upper()}] **{r['label']}** ({r['file']})")
        out.append(f"  {snippet[:200]}{'...' if len(snippet) > 200 else ''}\n")
    return "\n".join(out)


# ── MCP handlers ─────────────────────────────────────────────────────────────

@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(name="list_components", description="List all documented components with file, type, and tags.",
             inputSchema={"type": "object", "properties": {}}),
        Tool(name="get_component",
             description="Get full details for a component (purpose, functions, config, gotchas). Partial name match OK.",
             inputSchema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}),
        Tool(name="search_gotchas",
             description="Search all gotchas for a keyword (case-insensitive).",
             inputSchema={"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}),
        Tool(name="search_wiki",
             description="Full-text search across component names, purposes, functions, and gotchas.",
             inputSchema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    args = arguments or {}
    if name == "list_components":
        text = _list_components()
    elif name == "get_component":
        text = _get_component(args.get("name", ""))
    elif name == "search_gotchas":
        text = _search_gotchas(args.get("keyword", ""))
    elif name == "search_wiki":
        text = _search_wiki(args.get("query", ""))
    else:
        text = f"Unknown tool: {name}"
    return [TextContent(type="text", text=text)]


# ── Starlette app (SSE transport + OAuth + health) ───────────────────────────

sse_transport = SseServerTransport("/messages/")


async def handle_sse(request: Request):
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


def build_app() -> Starlette:
    routes = [
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse_transport.handle_post_message),
        Route("/health", lambda r: JSONResponse({"ok": True})),
    ]
    app = Starlette(routes=routes)
    try:
        from auth import add_oauth_routes
        add_oauth_routes(app)
    except ImportError:
        pass
    return app


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "3000"))
    cert = os.environ.get("TLS_CERT", "")
    key  = os.environ.get("TLS_KEY", "")
    ssl_kwargs = {"ssl_certfile": cert, "ssl_keyfile": key} if cert and key else {}
    uvicorn.run(build_app(), host="0.0.0.0", port=port, **ssl_kwargs)
