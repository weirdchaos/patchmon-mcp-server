# PatchMon MCP Server

An MCP (Model Context Protocol) server that connects to a [PatchMon](https://patchmon.net)
instance via its Integration API, so an LLM client (Claude Desktop, Claude
Code, etc.) can query host inventory, patch status, and system details, and
optionally delete hosts.

Built against PatchMon's documented Integration API:
https://docs.patchmon.net/books/patchmon-application-documentation/page/integration-api-documentation

Uses the standalone [`fastmcp`](https://github.com/jlowin/fastmcp) library
(v2.x) to implement the MCP server. This is a separate project from, but
protocol-compatible with, Anthropic's official `mcp` Python SDK — any MCP
client (Claude Desktop, Claude Code, MCP Inspector) works with it
identically.

## Tools exposed

| Tool | Scope needed | Description |
|---|---|---|
| `list_hosts` | `host:get` | List all hosts, optionally filtered by host group, optionally with inline stats |
| `get_host_stats` | `host:get` | Package/repo statistics for one host |
| `get_host_info` | `host:get` | OS, agent version, host groups for one host |
| `get_host_network` | `host:get` | IP, gateway, DNS, interfaces |
| `get_host_system` | `host:get` | CPU/RAM/disk/kernel/uptime/reboot status |
| `get_host_packages` | `host:get` | Installed packages, optionally updates-only |
| `get_host_package_reports` | `host:get` | Agent check-in report history |
| `get_host_agent_queue` | `host:get` | Agent job queue + job history |
| `get_host_notes` | `host:get` | Free-text notes on a host |
| `get_host_integrations` | `host:get` | Integration status (e.g. Docker) |
| `delete_host` | `host:delete` | Permanently delete a host (guarded by `confirm=true`) |
| `get_host_overview` | `host:get` | Combined info + stats + system in one call |
| `find_hosts_needing_security_updates` | `host:get` | Hosts with pending security updates |

## 1. Create a PatchMon API credential

1. Log in to your PatchMon instance as an administrator.
2. Go to **Settings → Integrations → Auto-Enrollment & API**.
3. Click **New Token**, choose usage type **API**.
4. Grant scope `host: get` (add `delete` too if you want the `delete_host`
   tool to work).
5. Copy the **Token Key** (`patchmon_ae_...`) and **Token Secret** — the
   secret is shown only once.

## 2. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Configure

The server reads its configuration from environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `PATCHMON_URL` | yes | — | Base URL of your PatchMon instance, e.g. `https://patchmon.example.com` |
| `PATCHMON_API_KEY` | yes | — | Token key (`patchmon_ae_...`) |
| `PATCHMON_API_SECRET` | yes | — | Token secret |
| `PATCHMON_API_VERSION` | no | `v1` | API version path segment |
| `PATCHMON_VERIFY_SSL` | no | `true` | Set to `false` to skip TLS verification (dev/self-signed only) |
| `PATCHMON_TIMEOUT` | no | `30` | Request timeout in seconds |

## 4. Run standalone (for testing)

```bash
export PATCHMON_URL="https://patchmon.example.com"
export PATCHMON_API_KEY="patchmon_ae_abc123"
export PATCHMON_API_SECRET="your_secret_here"
python server.py
```

The server speaks MCP over stdio, so it's normally launched by an MCP
client rather than run interactively.

> **Note:** `list_tools.py` (a small helper for querying the server's tool
> list from the command line) uses the official `mcp` package's client
> classes (`ClientSession`, `stdio_client`). That's independent of which
> SDK the *server* is built on — any MCP client can talk to any MCP
> server. If you don't already have `mcp` installed for the client side,
> add it with `pip install mcp`.

## 5. Connect it to Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "patchmon": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/server.py"],
      "env": {
        "PATCHMON_URL": "https://patchmon.example.com",
        "PATCHMON_API_KEY": "patchmon_ae_abc123",
        "PATCHMON_API_SECRET": "your_secret_here"
      }
    }
  }
}
```

Restart Claude Desktop and the `patchmon` tools will be available.

## 6. Connect it to Claude Code

```bash
claude mcp add patchmon \
  --env PATCHMON_URL=https://patchmon.example.com \
  --env PATCHMON_API_KEY=patchmon_ae_abc123 \
  --env PATCHMON_API_SECRET=your_secret_here \
  -- /absolute/path/to/.venv/bin/python /absolute/path/to/server.py
```

## Notes on safety

- `delete_host` is destructive and irreversible. It requires an explicit
  `confirm=true` argument in addition to the `host:delete` scope, as a
  guard against accidental invocation.
- Credentials are read from environment variables only — never hard-code
  them into the server or commit them to version control.
- Consider restricting the PatchMon API credential to specific IPs and
  setting an expiration date (see PatchMon's Security Best Practices).
