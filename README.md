# estate3-wiki-mcp

MCP server that exposes the Estate 3.0 wiki database (`wiki.sqlite`) to
Claude Code and claude.ai via four query tools.

Built with [FastMCP](https://github.com/jlowin/fastmcp). Runs in Docker on
Unraid behind Tailscale.

## Tools

| Tool | What it does |
|------|-------------|
| `list_components()` | All 26 documented components with file, type, tags |
| `get_component(name)` | Full detail: purpose, functions, config, gotchas |
| `search_gotchas(keyword)` | Find gotchas matching a word or phrase |
| `search_wiki(query)` | Full-text search across all sections |

## Quickstart on Unraid

### 1. Prerequisites

- Tailscale installed and running on Unraid
- Docker Compose available (Unraid Community Apps)
- `wiki.sqlite` built from the estate3 project and copied to Unraid

### 2. Clone the repo

SSH into Unraid:

```bash
mkdir -p /mnt/user/appdata/estate3-wiki
cd /mnt/user/appdata/estate3-wiki
git clone https://github.com/YOUR_USERNAME/estate3-wiki-mcp.git .
```

### 3. Get a Tailscale TLS cert

```bash
mkdir -p /mnt/user/appdata/estate3-wiki/tls
TSHOST=$(tailscale status --json | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))")
echo "Hostname: $TSHOST"

tailscale cert \
  --cert-file /mnt/user/appdata/estate3-wiki/tls/cert.pem \
  --key-file  /mnt/user/appdata/estate3-wiki/tls/key.pem \
  "$TSHOST"
```

### 4. Create `.env`

```bash
cp .env.template .env
# Edit .env — fill in TAILSCALE_HOSTNAME, MCP_CLIENT_SECRET, MCP_BEARER_TOKEN
nano .env
```

Generate secrets:
```bash
openssl rand -hex 32   # run twice — once for each secret
```

### 5. Copy wiki.sqlite from your dev machine

On your Mac (in the estate3 project):
```bash
rsync -av wiki_runs/wiki.sqlite \
  tower:/mnt/user/appdata/estate3-wiki/wiki.sqlite
```

### 6. Start the container

```bash
docker-compose up -d --build
docker-compose logs -f
# Expected: Uvicorn running on 0.0.0.0:3000
```

### 7. Verify

```bash
curl https://$TSHOST/health
# {"ok": true}
```

## Wire up Claude Code (on your Mac)

Copy `mcp.json` to your project root as `.claude/mcp.json` and update the
hostname:

```json
{
  "mcpServers": {
    "estate3-wiki": {
      "type": "sse",
      "url": "https://YOUR-TAILSCALE-HOSTNAME/sse"
    }
  }
}
```

Test:
```bash
claude mcp list
claude mcp test estate3-wiki list_components
```

## Wire up claude.ai

1. Settings → Integrations → Add MCP Server
2. URL: `https://YOUR-TAILSCALE-HOSTNAME`
3. Complete the OAuth flow (click Approve on the page that opens)

If claude.ai can't reach the server (Anthropic cloud → can't hit Tailscale):

```bash
# On Unraid — expose via Tailscale Funnel (public HTTPS proxy)
tailscale funnel 3000
# Use the Funnel URL shown in: tailscale funnel status
```

## Updating wiki.sqlite

The server reads the DB at query time — no restart needed.

```bash
# On Mac, after adding new wiki files:
python wiki_runs/build_db.py

# Sync to Unraid:
rsync -av wiki_runs/wiki.sqlite tower:/mnt/user/appdata/estate3-wiki/wiki.sqlite
```

## Renewing the TLS cert (~90 days)

```bash
# On Unraid:
tailscale cert \
  --cert-file /mnt/user/appdata/estate3-wiki/tls/cert.pem \
  --key-file  /mnt/user/appdata/estate3-wiki/tls/key.pem \
  "$TSHOST"
docker-compose restart estate3-wiki-mcp
```
