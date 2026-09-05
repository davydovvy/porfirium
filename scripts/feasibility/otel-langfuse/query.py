#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--env-file", required=True, type=Path)
    args = parser.parse_args()
    values = dict(
        line.split("=", 1)
        for line in args.env_file.read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    raw = values["LANGFUSE_AUTH"].removeprefix("Basic ")
    public_key, secret_key = base64.b64decode(raw).decode().split(":", 1)
    auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    url = "http://127.0.0.1:3000/api/public/observations?" + urllib.parse.urlencode(
        {"traceId": args.trace_id, "limit": 100}
    )
    for _ in range(40):
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"}), timeout=10
        ) as response:
            items = json.load(response).get("data", [])
        names = {item.get("name") for item in items}
        if {"gate.sdk", "gate.gateway"} <= names:
            print("PASS: correlated SDK and gateway spans found in Langfuse")
            return
        time.sleep(0.5)
    raise RuntimeError(f"missing correlated observations; found {sorted(names)}")


if __name__ == "__main__":
    main()
