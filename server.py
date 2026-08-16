#!/usr/bin/env python3
"""
PatchMon MCP Server
====================

An MCP (Model Context Protocol) server that connects to a PatchMon instance
via its Integration API and exposes host / patch-management data as MCP
tools, so an LLM client (Claude Desktop, Claude Code, etc.) can query and
manage PatchMon hosts.

PatchMon API reference:
https://docs.patchmon.net/books/patchmon-application-documentation/page/integration-api-documentation

Authentication
--------------
PatchMon's Integration API uses HTTP Basic Auth with a scoped API
credential (created in PatchMon under Settings -> Integrations ->
Auto-Enrollment & API -> New Token -> usage type "API"):

    Authorization: Basic base64(token_key:token_secret)

Configuration (environment variables)
--------------------------------------
PATCHMON_URL          Base URL of your PatchMon instance, e.g.
                       https://patchmon.example.com  (required)
PATCHMON_API_KEY       Token key, prefixed with patchmon_ae_  (required)
PATCHMON_API_SECRET    Token secret, shown only once at creation (required)
PATCHMON_API_VERSION   API version path segment, defaults to "v1"
PATCHMON_VERIFY_SSL    "false" to disable TLS verification (dev only),
                       defaults to "true"
PATCHMON_TIMEOUT       Request timeout in seconds, defaults to 30

Scopes required
----------------
- `host:get`    for all read-only tools (list/info/stats/etc.)
- `host:delete` for the delete_host tool

Run
---
    pip install -r requirements.txt
    export PATCHMON_URL="https://patchmon.example.com"
    export PATCHMON_API_KEY="patchmon_ae_..."
    export PATCHMON_API_SECRET="..."
    python server.py
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

import httpx
from fastmcp import FastMCP

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

PATCHMON_URL = os.environ.get("PATCHMON_URL", "").rstrip("/")
PATCHMON_API_KEY = os.environ.get("PATCHMON_API_KEY", "")
PATCHMON_API_SECRET = os.environ.get("PATCHMON_API_SECRET", "")
PATCHMON_API_VERSION = os.environ.get("PATCHMON_API_VERSION", "v1")
PATCHMON_VERIFY_SSL = os.environ.get("PATCHMON_VERIFY_SSL", "true").lower() not in (
    "false",
    "0",
    "no",
)
PATCHMON_TIMEOUT = float(os.environ.get("PATCHMON_TIMEOUT", "30"))

if not PATCHMON_URL or not PATCHMON_API_KEY or not PATCHMON_API_SECRET:
    print(
        "ERROR: PATCHMON_URL, PATCHMON_API_KEY and PATCHMON_API_SECRET "
        "environment variables must all be set.",
        file=sys.stderr,
    )
    sys.exit(1)

API_BASE = f"{PATCHMON_URL}/api/{PATCHMON_API_VERSION}/api"

mcp = FastMCP("patchmon")


# --------------------------------------------------------------------------
# HTTP client helper
# --------------------------------------------------------------------------


class PatchMonError(Exception):
    """Raised when the PatchMon API returns an error response."""


def _client() -> httpx.Client:
    return httpx.Client(
        auth=(PATCHMON_API_KEY, PATCHMON_API_SECRET),
        timeout=PATCHMON_TIMEOUT,
        verify=PATCHMON_VERIFY_SSL,
    )


def _request(
    method: str,
    path: str,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Make an authenticated request to the PatchMon Integration API.

    Raises PatchMonError with a helpful message on any non-2xx response,
    covering the documented PatchMon error cases (401 auth, 403 scope/IP,
    404 not found, 400 bad UUID, 500 server error).
    """
    url = f"{API_BASE}{path}"
    # Drop None-valued params rather than sending them as literal "None".
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}

    try:
        with _client() as client:
            response = client.request(method, url, params=clean_params)
    except httpx.TimeoutException as exc:
        raise PatchMonError(f"Request to {url} timed out: {exc}") from exc
    except httpx.RequestError as exc:
        raise PatchMonError(f"Request to {url} failed: {exc}") from exc

    if response.status_code >= 400:
        try:
            body = response.json()
            message = body.get("error", body)
        except ValueError:
            message = response.text

        hints = {
            401: "Authentication failed - check PATCHMON_API_KEY / PATCHMON_API_SECRET.",
            403: "Access denied - the credential may lack the required scope "
            "(host:get / host:delete) or the client IP is not allowlisted.",
            404: "Not found - verify the host ID (use list_hosts to look it up).",
            400: "Bad request - check that the host ID is a valid UUID.",
        }
        hint = hints.get(response.status_code, "")
        raise PatchMonError(
            f"PatchMon API error {response.status_code} for {method} {path}: "
            f"{message}" + (f" ({hint})" if hint else "")
        )

    if not response.content:
        return {}
    return response.json()


# --------------------------------------------------------------------------
# Tools - Hosts
# --------------------------------------------------------------------------


@mcp.tool()
def list_hosts(
    hostgroup: Optional[str] = None,
    include_stats: bool = False,
) -> dict[str, Any]:
    """List all hosts monitored by PatchMon.

    Args:
        hostgroup: Optional comma-separated host group name(s) or UUID(s)
            to filter by (OR logic across multiple groups), e.g.
            "Production" or "Production,Development".
        include_stats: If true, include package update counts and extra
            metadata (OS, status, update state, etc.) inline for each host.
            This is more efficient than calling get_host_stats per host.

    Returns:
        A dict with `hosts` (list of host objects), `total`, and
        `filtered_by_groups` (if a hostgroup filter was applied).
    """
    params: dict[str, Any] = {}
    if hostgroup:
        params["hostgroup"] = hostgroup
    if include_stats:
        params["include"] = "stats"
    return _request("GET", "/hosts", params=params)


@mcp.tool()
def get_host_stats(host_id: str) -> dict[str, Any]:
    """Get package and repository statistics for a specific host.

    Args:
        host_id: The PatchMon host UUID (see list_hosts).

    Returns:
        total_installed_packages, outdated_packages, security_updates,
        total_repos.
    """
    return _request("GET", f"/hosts/{host_id}/stats")


@mcp.tool()
def get_host_info(host_id: str) -> dict[str, Any]:
    """Get detailed information about a specific host (OS, agent version,
    host groups, machine ID, etc.).

    Args:
        host_id: The PatchMon host UUID (see list_hosts).
    """
    return _request("GET", f"/hosts/{host_id}/info")


@mcp.tool()
def get_host_network(host_id: str) -> dict[str, Any]:
    """Get network configuration for a specific host (IP, gateway, DNS
    servers, network interfaces).

    Args:
        host_id: The PatchMon host UUID (see list_hosts).
    """
    return _request("GET", f"/hosts/{host_id}/network")


@mcp.tool()
def get_host_system(host_id: str) -> dict[str, Any]:
    """Get system-level details for a specific host: architecture, kernel
    version (running vs installed), CPU, RAM, swap, load average, disk
    usage, and whether a reboot is pending and why.

    Args:
        host_id: The PatchMon host UUID (see list_hosts).
    """
    return _request("GET", f"/hosts/{host_id}/system")


@mcp.tool()
def get_host_packages(host_id: str, updates_only: bool = False) -> dict[str, Any]:
    """List packages installed on a specific host.

    Args:
        host_id: The PatchMon host UUID (see list_hosts).
        updates_only: If true, return only packages that have an update
            available (results are sorted security updates first).

    Returns:
        `host` (basic host identification), `packages` (list of package
        objects with current/available version and whether the update is
        security-related), and `total`.
    """
    params = {"updates_only": "true"} if updates_only else {}
    return _request("GET", f"/hosts/{host_id}/packages", params=params)


@mcp.tool()
def get_host_package_reports(host_id: str, limit: int = 10) -> dict[str, Any]:
    """Get the package-update report history for a specific host (each
    agent check-in produces a report with status, package counts and
    timing).

    Args:
        host_id: The PatchMon host UUID (see list_hosts).
        limit: Maximum number of reports to return (default 10).
    """
    return _request(
        "GET", f"/hosts/{host_id}/package_reports", params={"limit": limit}
    )


@mcp.tool()
def get_host_agent_queue(host_id: str, limit: int = 10) -> dict[str, Any]:
    """Get the agent job queue status and recent job history for a
    specific host (waiting/active/delayed/failed counts plus job records).

    Args:
        host_id: The PatchMon host UUID (see list_hosts).
        limit: Maximum number of job history records to return (default 10).
    """
    return _request("GET", f"/hosts/{host_id}/agent_queue", params={"limit": limit})


@mcp.tool()
def get_host_notes(host_id: str) -> dict[str, Any]:
    """Get free-text notes associated with a specific host.

    Args:
        host_id: The PatchMon host UUID (see list_hosts).
    """
    return _request("GET", f"/hosts/{host_id}/notes")


@mcp.tool()
def get_host_integrations(host_id: str) -> dict[str, Any]:
    """Get integration status for a specific host (e.g. Docker monitoring:
    whether it's enabled and counts of containers/volumes/networks).

    Args:
        host_id: The PatchMon host UUID (see list_hosts).
    """
    return _request("GET", f"/hosts/{host_id}/integrations")


@mcp.tool()
def delete_host(host_id: str, confirm: bool = False) -> dict[str, Any]:
    """Permanently delete a host and all related data (packages,
    repositories, update history, Docker data, job history, group
    memberships). This is IRREVERSIBLE and requires the host:delete scope.

    Args:
        host_id: The PatchMon host UUID (see list_hosts).
        confirm: Must be explicitly set to true to actually perform the
            deletion. This is a safety guard against accidental calls -
            if false, the tool returns without making any request.
    """
    if not confirm:
        return {
            "deleted": False,
            "message": (
                "No action taken. Re-call this tool with confirm=true to "
                "permanently delete this host and all its data."
            ),
        }
    return _request("DELETE", f"/hosts/{host_id}")


# --------------------------------------------------------------------------
# Convenience / aggregate tools
# --------------------------------------------------------------------------


@mcp.tool()
def get_host_overview(host_id: str) -> dict[str, Any]:
    """Get a combined overview of a host: info, stats, and system details
    in a single call. Useful when an LLM wants a full picture of one host
    without making three separate tool calls.

    Args:
        host_id: The PatchMon host UUID (see list_hosts).
    """
    info = _request("GET", f"/hosts/{host_id}/info")
    stats = _request("GET", f"/hosts/{host_id}/stats")
    system = _request("GET", f"/hosts/{host_id}/system")
    return {"info": info, "stats": stats, "system": system}


@mcp.tool()
def find_hosts_needing_security_updates(hostgroup: Optional[str] = None) -> dict[str, Any]:
    """List hosts that currently have one or more pending security
    updates, using the efficient `include=stats` listing rather than
    per-host calls.

    Args:
        hostgroup: Optional comma-separated host group name(s)/UUID(s) to
            filter by before checking for security updates.

    Returns:
        A dict with `hosts` (filtered list, each including its
        security_updates_count) and `total`.
    """
    params: dict[str, Any] = {"include": "stats"}
    if hostgroup:
        params["hostgroup"] = hostgroup
    data = _request("GET", "/hosts", params=params)
    flagged = [
        h for h in data.get("hosts", []) if h.get("security_updates_count", 0) > 0
    ]
    return {"hosts": flagged, "total": len(flagged)}


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
