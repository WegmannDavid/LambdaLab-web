#!/usr/bin/env python3
"""The contract this website depends on, as executable assertions.

    contract/check.py PATH_TO_STLC

Run against any `stlc` binary. Both repos run this same file:

  * here, against the compiler image we are about to build on top of;
  * in the compiler repo, against a freshly built binary, *before* it publishes.

That second one is the point of the split. The compiler team can change anything they
like as long as this passes, and if they break it they find out in their own pipeline
rather than in ours — or in production.

Consumer-driven, so it asserts only what this website actually relies on. Notably it does
NOT assert the shape of the output: `stlc` currently renders a whole program onto one
line, and the page is content to display whatever it is handed. Pinning that here would
freeze the compiler's formatting on our behalf, which is not ours to freeze.

No third-party imports, deliberately — the compiler repo has to run this without setting
up a Python environment first.
"""

import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
DEMO = REPO / "static" / "demo.stlc"

TIMEOUT = 10  # generous; the compiler answers the demo in ~40ms

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok       {name}")
    else:
        print(f"  FAILED   {name}{': ' + detail if detail else ''}")
        failures.append(name)


def compile_source(binary: str, source: str) -> tuple[int, str, str]:
    """Run the compiler over `source`, the way the server does: via a temp file."""
    with tempfile.NamedTemporaryFile("w", suffix=".stlc", encoding="utf-8") as f:
        f.write(source)
        f.flush()
        p = subprocess.run(
            [binary, f.name],
            capture_output=True,
            timeout=TIMEOUT,
        )
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    binary = sys.argv[1]

    print(f"contract: checking {binary}")

    # --- the demo we ship must be a program this compiler accepts ------------------------
    # Ours to keep valid, but a syntax change upstream breaks it, and this is where that
    # gets caught.
    demo = DEMO.read_text(encoding="utf-8")
    rc, out, _ = compile_source(binary, demo)
    check("our demo.stlc compiles", rc == 0, f"exit {rc}")
    check("our demo.stlc produces output", bool(out.strip()))

    # --- a valid program: exit 0, something on stdout ------------------------------------
    rc, out, _ = compile_source(binary, "def id : ?0 → ?1 := λ x : ⋆ . x\n")
    check("valid program exits 0", rc == 0, f"exit {rc}")
    check("valid program writes stdout", bool(out.strip()))

    # --- the page renders whatever comes back, so it has to be text ----------------------
    check("output is valid UTF-8", isinstance(out, str) and "�" not in out)

    # --- an invalid program: non-zero, and nothing on stdout -----------------------------
    # The page shows "error" on a non-zero exit. If a rejected program still wrote to
    # stdout we would render that as if it were a successful compilation.
    rc, out, err = compile_source(binary, "def broken : = := λ\n")
    check("invalid program exits non-zero", rc != 0, f"exit {rc}")
    check("invalid program writes nothing to stdout", out == "", repr(out[:80]))
    check("invalid program explains itself on stderr", bool(err.strip()))

    # --- a missing file is an error, not a crash -----------------------------------------
    p = subprocess.run([binary, "/nonexistent/nope.stlc"], capture_output=True, timeout=TIMEOUT)
    check("missing file exits non-zero", p.returncode != 0)

    # --- determinism: the page caches nothing, but a flaky compiler would be worse -------
    rc1, out1, _ = compile_source(binary, demo)
    rc2, out2, _ = compile_source(binary, demo)
    check("deterministic across runs", (rc1, out1) == (rc2, out2))

    # --- idempotence: re-running on the output is what "round trip" means ----------------
    rc3, out3, _ = compile_source(binary, out1)
    check("output re-compiles", rc3 == 0, f"exit {rc3}")
    check("idempotent", out3 == out1)

    print()
    if failures:
        print(f"contract: {len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("contract: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
