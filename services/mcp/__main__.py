"""`uv run python -m services.mcp --stdio` (default) or `--http --port 8001` (streamable HTTP at /mcp)."""

from __future__ import annotations

import argparse
import os

from mcp.server.transport_security import TransportSecuritySettings

from services.mcp.server import build_server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m services.mcp", description="PartSmith MCP server")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--stdio", action="store_true", help="serve over stdio (default)")
    mode.add_argument("--http", action="store_true", help="serve streamable HTTP at /mcp")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--read-only", action="store_true", help="leave out start_fix_job and report_need")
    a = ap.parse_args(argv)
    read_only = a.read_only or os.environ.get("PARTSMITH_MCP_READ_ONLY", "0") == "1"
    if a.http:
        server = build_server(allow_paths=False, read_only=read_only)
        local = a.host in ("127.0.0.1", "localhost", "::1")
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=local,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        )
        server.run(
            "streamable-http", host=a.host, port=a.port, streamable_http_path="/mcp", transport_security=security
        )
    else:
        build_server(allow_paths=True, read_only=read_only).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
