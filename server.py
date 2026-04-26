"""
Estate 3.0 Wiki MCP Server
Exposes wiki.sqlite via MCP tools for Claude Code and claude.ai.
"""

import os
import sqlite3
from contextlib import contextmanager
from fastmcp import FastMCP

DB_PATH = os.environ.get("WIKI_DB", "/data/wiki.sqlite")

mcp = FastMCP("estate3-wiki")


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


@mcp.tool()
def list_components() -> str:
    """List all documented components with their file, type, and run group."""
    with db() as con:
        rows = con.execute(
            "SELECT run, component, file, type, tags FROM components ORDER BY run, component"
        ).fetchall()
    lines = ["Run | Component | File | Type | Tags", "----|-----------|------|------|-----"]
    for r in rows:
        lines.append(f"{r['run']} | {r['component']} | {r['file']} | {r['type']} | {r['tags']}")
    return "\n".join(lines)


@mcp.tool()
def get_component(name: str) -> str:
    """
    Get full details for a component: purpose, interfaces, functions, config, gotchas.
    name: component name (partial match OK, case-insensitive)
    """
    with db() as con:
        row = con.execute(
            "SELECT * FROM components WHERE component LIKE ? LIMIT 1",
            (f"%{name}%",)
        ).fetchone()
        if not row:
            return f"No component matching '{name}'. Use list_components() to see all."

        cid = row["id"]

        funcs = con.execute(
            "SELECT name, signature, does FROM functions WHERE component_id=?", (cid,)
        ).fetchall()

        configs = con.execute(
            "SELECT param, default_val, effect FROM config_params WHERE component_id=?", (cid,)
        ).fetchall()

        gotchas = con.execute(
            "SELECT text FROM gotchas WHERE component_id=?", (cid,)
        ).fetchall()

        ifaces = con.execute(
            "SELECT direction, name, from_to, itype FROM interfaces WHERE component_id=?", (cid,)
        ).fetchall()

    out = [
        f"# {row['component']}",
        f"**File:** {row['file']}  |  **Type:** {row['type']}  |  **Tags:** {row['tags']}",
        f"\n## Purpose\n{row['purpose']}",
    ]

    if ifaces:
        out.append("\n## Interfaces")
        out.append("Direction | Name | From/To | Type")
        out.append("----------|------|---------|-----")
        for i in ifaces:
            out.append(f"{i['direction']} | {i['name']} | {i['from_to']} | {i['itype']}")

    if funcs:
        out.append("\n## Functions")
        out.append("Name | Signature | Does")
        out.append("-----|-----------|-----")
        for f in funcs:
            out.append(f"{f['name']} | {f['signature']} | {f['does']}")

    if configs:
        out.append("\n## Config")
        out.append("Param | Default | Effect")
        out.append("------|---------|-------")
        for c in configs:
            out.append(f"{c['param']} | {c['default_val']} | {c['effect']}")

    if gotchas:
        out.append("\n## Gotchas")
        for g in gotchas:
            out.append(f"- {g['text']}")

    return "\n".join(out)


@mcp.tool()
def search_gotchas(keyword: str) -> str:
    """
    Search all gotchas for a keyword. Returns matching gotchas with their component.
    keyword: word or phrase to search for (case-insensitive)
    """
    with db() as con:
        rows = con.execute(
            """
            SELECT c.component, c.file, g.text
            FROM gotchas g JOIN components c ON c.id = g.component_id
            WHERE lower(g.text) LIKE lower(?)
            ORDER BY c.component
            """,
            (f"%{keyword}%",)
        ).fetchall()

    if not rows:
        return f"No gotchas matching '{keyword}'."

    out = [f"Found {len(rows)} gotcha(s) matching '{keyword}':\n"]
    for r in rows:
        out.append(f"**[{r['component']}]** ({r['file']})")
        out.append(f"  {r['text']}\n")
    return "\n".join(out)


@mcp.tool()
def search_wiki(query: str) -> str:
    """
    Full-text search across component names, purposes, function descriptions, and gotchas.
    Returns up to 15 matches. Use this when you don't know which component to look at.
    query: word or phrase (case-insensitive)
    """
    like = f"%{query}%"
    with db() as con:
        # Components matching on name or purpose
        comps = con.execute(
            """
            SELECT 'component' as source, component as label, file, purpose as snippet
            FROM components
            WHERE lower(component) LIKE lower(?) OR lower(purpose) LIKE lower(?)
            LIMIT 5
            """,
            (like, like)
        ).fetchall()

        # Functions matching on name or does
        funcs = con.execute(
            """
            SELECT 'function' as source, f.name as label, c.file, f.does as snippet
            FROM functions f JOIN components c ON c.id = f.component_id
            WHERE lower(f.name) LIKE lower(?) OR lower(f.does) LIKE lower(?)
            LIMIT 5
            """,
            (like, like)
        ).fetchall()

        # Gotchas
        gotchas = con.execute(
            """
            SELECT 'gotcha' as source, c.component as label, c.file, g.text as snippet
            FROM gotchas g JOIN components c ON c.id = g.component_id
            WHERE lower(g.text) LIKE lower(?)
            LIMIT 5
            """,
            (like,)
        ).fetchall()

    all_results = list(comps) + list(funcs) + list(gotchas)
    if not all_results:
        return f"Nothing found for '{query}'. Try list_components() to browse."

    out = [f"Search results for '{query}' ({len(all_results)} hits):\n"]
    for r in all_results:
        out.append(f"[{r['source'].upper()}] **{r['label']}** ({r['file']})")
        snippet = r['snippet'] or ''
        out.append(f"  {snippet[:200]}{'...' if len(snippet) > 200 else ''}\n")
    return "\n".join(out)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "3000"))
    cert = os.environ.get("TLS_CERT", "")
    key = os.environ.get("TLS_KEY", "")

    ssl_kwargs = {}
    if cert and key:
        ssl_kwargs = {"ssl_certfile": cert, "ssl_keyfile": key}

    # For claude.ai: mount OAuth on same app (see auth.py)
    try:
        from auth import add_oauth_routes
        app = mcp.http_app()
        add_oauth_routes(app)
        uvicorn.run(app, host="0.0.0.0", port=port, **ssl_kwargs)
    except ImportError:
        # Claude Code mode: no OAuth needed
        mcp.run(transport="sse", host="0.0.0.0", port=port)
