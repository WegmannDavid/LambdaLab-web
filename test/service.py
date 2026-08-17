#!/usr/bin/env python3
"""Drive the running service over HTTP.

    test/service.py http://127.0.0.1:8099

Distinct from `contract/`, and the distinction matters: `contract/` is what we depend on
*from the compiler*, and the compiler repo runs it too. This file is our own service
behaving correctly, and only we run it.

Written against a base URL so the same checks cover the container in CI and the deployed
service in production — the difference between "the image works" and "the thing you can
actually visit works" has bitten everyone at least once.

Standard library only, to match the server.
"""

import json
import sys
import urllib.error
import urllib.request

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok       {name}")
    else:
        print(f"  FAILED   {name}{': ' + detail if detail else ''}")
        failures.append(name)


def get(base: str, path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(base + path, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def post_compile(base: str, source: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        base + "/api/compile",
        data=json.dumps({"source": source}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: service.py BASE_URL", file=sys.stderr)
        return 2
    base = sys.argv[1].rstrip("/")
    print(f"service: checking {base}")

    status, _ = get(base, "/healthz")
    check("healthz responds", status == 200, f"status {status}")

    status, body = get(base, "/")
    check("index is served", status == 200 and "<title>LambdaLab</title>" in body)

    status, demo = get(base, "/demo.stlc")
    check("demo.stlc is served", status == 200 and demo.strip() != "")

    # The page shows the demo on load, so the demo must survive the round trip it advertises.
    status, data = post_compile(base, demo)
    check("the demo compiles through the API", status == 200 and data.get("ok") is True,
          json.dumps(data)[:120])
    check("the demo produces output", bool(data.get("output", "").strip()))

    # A rejected program is a normal answer: 200 with ok=false, so the page can distinguish
    # "your program is wrong" from "the service is down".
    status, data = post_compile(base, "def broken : = := λ")
    check("a rejected program is 200 ok=false", status == 200 and data.get("ok") is False,
          f"status {status} {json.dumps(data)[:80]}")
    check("a rejected program carries an error string", bool(data.get("error")))

    # The compiler names the temp file it was given; that path must not reach the user.
    check("no server path leaks in the error", "/tmp" not in json.dumps(data))

    status, data = post_compile(base, "x" * 100_000)
    check("oversize source is refused with 413", status == 413, f"status {status}")

    req = urllib.request.Request(
        base + "/api/compile", data=b'{"nope":1}',
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    check("malformed payload is refused with 400", code == 400, f"status {code}")

    status, _ = get(base, "/../server/app.py")
    check("path traversal is refused", status in (400, 404), f"status {status}")

    print()
    if failures:
        print(f"service: {len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("service: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
