from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any

import httpx

DEFAULT_BASE_URL = os.getenv("TALOS_BASE_URL", "http://127.0.0.1:8000")


def _print_json(data: Any, pretty: bool = True) -> None:
    if pretty:
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False))
    else:
        print(json.dumps(data, ensure_ascii=False))


def _request(
    method: str,
    url: str,
    *,
    json_body: dict | None = None,
    timeout: float = 5.0,
) -> Any:
    headers = {"accept": "application/json"}
    if json_body is not None:
        headers["content-type"] = "application/json"

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.request(method, url, headers=headers, json=json_body)
    except httpx.RequestError as e:
        raise RuntimeError(f"Request failed: {e}") from e

    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type:
        payload: Any = resp.json()
    else:
        payload = resp.text

    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} error: {payload}")

    return payload


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


# -------------------------
# OpenAPI helpers
# -------------------------
def fetch_openapi_spec(base_url: str, *, timeout: float) -> dict:
    """
    Fetch OpenAPI spec from /openapi.json
    """
    url = f"{_normalize_base_url(base_url)}/openapi.json"
    spec = _request("GET", url, timeout=timeout)
    if not isinstance(spec, dict) or "paths" not in spec:
        raise RuntimeError(f"Invalid OpenAPI spec from {url}: missing 'paths'")
    return spec


def list_apis(spec: dict) -> list[tuple[str, str]]:
    """
    Return list of (METHOD, PATH) for all endpoints (method-level).
    """
    apis: list[tuple[str, str]] = []
    paths = spec.get("paths", {})
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method in methods.keys():
            # OpenAPI uses lowercase methods typically
            apis.append((str(method).upper(), str(path)))
    apis.sort(key=lambda x: (x[1], x[0]))  # sort by path, then method
    return apis


def count_apis(spec: dict) -> int:
    """
    Count method-level endpoints.
    """
    paths = spec.get("paths", {})
    total = 0
    for _, methods in paths.items():
        if isinstance(methods, dict):
            total += len(methods.keys())
    return total


def list_apis_grouped_by_tag(spec: dict) -> dict[str, list[str]]:
    """
    Group endpoints by OpenAPI tags.
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    paths = spec.get("paths", {})
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, meta in methods.items():
            method_u = str(method).upper()
            if isinstance(meta, dict):
                tags = meta.get("tags") or ["ungrouped"]
            else:
                tags = ["ungrouped"]
            for tag in tags:
                grouped[str(tag)].append(f"{method_u:6} {path}")
    # sort entries
    for tag in list(grouped.keys()):
        grouped[tag] = sorted(grouped[tag])
    return dict(sorted(grouped.items(), key=lambda x: x[0].lower()))


# -------------------------
# Command implementations
# -------------------------
def cmd_api(args: argparse.Namespace) -> Any:
    base = _normalize_base_url(args.base_url)
    spec = fetch_openapi_spec(base, timeout=args.timeout)

    if args.action == "count":
        return {"base_url": base, "total": count_apis(spec)}

    if args.action == "list":
        if args.group:
            grouped = list_apis_grouped_by_tag(spec)
            # return as json object for consistency
            return {"base_url": base, "grouped": grouped}

        # plain list
        apis = list_apis(spec)
        return {"base_url": base, "apis": [f"{m:6} {p}" for (m, p) in apis]}

    raise RuntimeError(f"Unknown api action: {args.action}")


def cmd_devices(args: argparse.Namespace) -> Any:
    base = _normalize_base_url(args.base_url)

    if args.action == "list":
        return _request("GET", f"{base}/api/devices/", timeout=args.timeout)

    if args.action == "health_summary":
        return _request("GET", f"{base}/api/devices/health/summary", timeout=args.timeout)

    device_id = args.device_id

    if args.action == "get":
        return _request("GET", f"{base}/api/devices/{device_id}", timeout=args.timeout)

    if args.action == "connectivity":
        return _request("GET", f"{base}/api/devices/{device_id}/connectivity", timeout=args.timeout)

    if args.action == "health":
        return _request("GET", f"{base}/api/devices/{device_id}/health", timeout=args.timeout)

    raise RuntimeError(f"Unknown devices action: {args.action}")


def cmd_constraints(args: argparse.Namespace) -> Any:
    base = _normalize_base_url(args.base_url)

    if args.action == "list":
        return _request("GET", f"{base}/api/constraints/", timeout=args.timeout)

    device_id = args.device_id
    if args.action == "get":
        return _request("GET", f"{base}/api/constraints/{device_id}", timeout=args.timeout)

    raise RuntimeError(f"Unknown constraints action: {args.action}")


def cmd_parameters(args: argparse.Namespace) -> Any:
    base = _normalize_base_url(args.base_url)
    device_id = args.device_id

    if args.action == "read":
        body = {"device_id": device_id, "parameter": args.parameter}
        return _request("POST", f"{base}/api/parameters/read", json_body=body, timeout=args.timeout)

    if args.action == "read_multiple":
        body = {"device_id": device_id, "parameters": args.parameters}
        return _request("POST", f"{base}/api/parameters/read-multiple", json_body=body, timeout=args.timeout)

    if args.action == "write":
        body = {"device_id": device_id, "parameter": args.parameter, "value": args.value}
        return _request("POST", f"{base}/api/parameters/write", json_body=body, timeout=args.timeout)

    raise RuntimeError(f"Unknown params action: {args.action}")


# -------------------------
# CLI parser
# -------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="talosctl",
        description="Talos edge point-to-point device operations (API wrapper).",
    )

    p.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL of Talos API (default: $TALOS_BASE_URL or http://127.0.0.1:8000)",
    )
    p.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout seconds (default: 5)")
    p.add_argument("--raw", action="store_true", help="Print raw JSON without pretty formatting")

    sub = p.add_subparsers(dest="cmd", required=True)

    # api
    api = sub.add_parser("api", help="OpenAPI helpers")
    api_sub = api.add_subparsers(dest="action", required=True)

    api_list = api_sub.add_parser("list", help="List all supported APIs from /openapi.json")
    api_list.add_argument("--group", action="store_true", help="Group by OpenAPI tags")

    api_sub.add_parser("count", help="Count APIs (method-level) from /openapi.json")

    # devices
    dev = sub.add_parser("devices", help="Device-related APIs")
    dev_sub = dev.add_subparsers(dest="action", required=True)

    dev_sub.add_parser("list", help="GET /api/devices/")

    dev_get = dev_sub.add_parser("get", help="GET /api/devices/{device_id}")
    dev_get.add_argument("device_id")

    dev_conn = dev_sub.add_parser("connectivity", help="GET /api/devices/{device_id}/connectivity")
    dev_conn.add_argument("device_id")

    dev_health = dev_sub.add_parser("health", help="GET /api/devices/{device_id}/health")
    dev_health.add_argument("device_id")

    dev_sub.add_parser("health_summary", help="GET /api/devices/health/summary")

    # params
    par = sub.add_parser("params", help="Parameter read/write APIs")
    par_sub = par.add_subparsers(dest="action", required=True)

    par_read = par_sub.add_parser("read", help="POST /api/parameters/read")
    par_read.add_argument("device_id")
    par_read.add_argument("parameter")

    par_rm = par_sub.add_parser("read_multiple", help="POST /api/parameters/read-multiple")
    par_rm.add_argument("device_id")
    par_rm.add_argument("parameters", nargs="+")

    par_write = par_sub.add_parser("write", help="POST /api/parameters/write")
    par_write.add_argument("device_id")
    par_write.add_argument("parameter")
    par_write.add_argument("value")

    # constraints
    con = sub.add_parser("constraints", help="Constraint APIs")
    con_sub = con.add_subparsers(dest="action", required=True)

    con_sub.add_parser("list", help="GET /api/constraints/")

    con_get = con_sub.add_parser("get", help="GET /api/constraints/{device_id}")
    con_get.add_argument("device_id")

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.cmd == "api":
            result = cmd_api(args)
        elif args.cmd == "devices":
            result = cmd_devices(args)
        elif args.cmd == "params":
            result = cmd_parameters(args)
        elif args.cmd == "constraints":
            result = cmd_constraints(args)
        else:
            raise RuntimeError(f"Unknown command: {args.cmd}")

        _print_json(result, pretty=not args.raw)
        return 0

    except Exception as e:
        base = _normalize_base_url(getattr(args, "base_url", DEFAULT_BASE_URL))
        print(f"[ERROR] base_url={base} - {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
