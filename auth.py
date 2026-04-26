"""
Minimal OAuth 2.0 shim for claude.ai remote MCP.
Implements only what claude.ai requires:
  GET  /.well-known/oauth-authorization-server  → server metadata
  GET  /oauth/authorize                          → show approve page
  POST /oauth/token                              → exchange code for token
  All MCP routes: validate Bearer token
"""

import os
import secrets
import time
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route
from starlette.middleware.base import BaseHTTPMiddleware

# ── config (set these as env vars in docker-compose) ────────────────────────
CLIENT_ID     = os.environ.get("OAUTH_CLIENT_ID", "claude-ai")
CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "change-me-in-compose")
BEARER_TOKEN  = os.environ.get("OAUTH_BEARER_TOKEN", secrets.token_urlsafe(32))
BASE_URL      = os.environ.get("BASE_URL", "http://localhost:3000")

# In-memory one-time-use codes (good enough for single user)
_pending_codes: dict[str, float] = {}


async def oauth_metadata(request: Request):
    return JSONResponse({
        "issuer": BASE_URL,
        "authorization_endpoint": f"{BASE_URL}/oauth/authorize",
        "token_endpoint": f"{BASE_URL}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
    })


async def oauth_authorize(request: Request):
    redirect_uri  = request.query_params.get("redirect_uri", "")
    state         = request.query_params.get("state", "")
    client_id     = request.query_params.get("client_id", "")

    if request.method == "POST":
        # User clicked Approve
        code = secrets.token_urlsafe(16)
        _pending_codes[code] = time.time()
        sep = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(f"{redirect_uri}{sep}code={code}&state={state}", status_code=302)

    # Show approve page
    html = f"""
    <!DOCTYPE html><html><body style="font-family:sans-serif;max-width:500px;margin:80px auto;padding:20px">
    <h2>Estate 3.0 Wiki MCP</h2>
    <p>Client <strong>{client_id}</strong> is requesting access to the wiki database.</p>
    <form method="POST">
      <input type="hidden" name="redirect_uri" value="{redirect_uri}">
      <input type="hidden" name="state" value="{state}">
      <button type="submit" style="padding:10px 24px;font-size:16px;background:#2563eb;color:white;border:none;border-radius:6px;cursor:pointer">
        Approve
      </button>
    </form>
    </body></html>
    """
    return HTMLResponse(html)


async def oauth_token(request: Request):
    form = await request.form()
    code = form.get("code", "")

    # Validate code exists and is < 5 minutes old
    issued_at = _pending_codes.pop(code, None)
    if issued_at is None or (time.time() - issued_at) > 300:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)

    return JSONResponse({
        "access_token": BEARER_TOKEN,
        "token_type": "Bearer",
        "expires_in": 315360000,  # 10 years — single user, don't expire
    })


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject MCP requests without a valid Bearer token."""
    EXEMPT = {
        "/.well-known/oauth-authorization-server",
        "/oauth/authorize",
        "/oauth/token",
        "/health",
    }

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.EXEMPT or request.method == "OPTIONS":
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {BEARER_TOKEN}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def add_oauth_routes(app):
    """Call this to mount OAuth onto the FastMCP Starlette app."""
    app.add_middleware(BearerAuthMiddleware)
    app.routes.extend([
        Route("/.well-known/oauth-authorization-server", oauth_metadata),
        Route("/oauth/authorize", oauth_authorize, methods=["GET", "POST"]),
        Route("/oauth/token", oauth_token, methods=["POST"]),
        Route("/health", lambda r: JSONResponse({"ok": True})),
    ])
