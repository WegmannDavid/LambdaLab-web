# LambdaLab-web

**https://lambdalab-web-7bria4l2la-ey.a.run.app**

The web playground for [LambdaLab](https://github.com/WegmannDavid/LambdaLab): paste a
program, press run, see it round-tripped through the verified parser and printer.

This repo owns everything web-facing — the page, the HTTP service that fronts the
compiler, the container image, and the deployment. It does **not** contain any Lean, and
building it does not require a Lean toolchain.

## The interface it consumes

The compiler is consumed as a published artifact, not as source:

```
ARTIFACT  ghcr.io/wegmanndavid/lambdalab-compiler:<tag>
  /usr/local/bin/stlc      executable, glibc only, 2.8 MB

BEHAVIOUR  stlc PATH
  valid    → exit 0,   canonical rendering on stdout
  invalid  → exit ≠ 0, stdout empty, diagnostic on stderr (not for display)
  missing  → exit ≠ 0

LAWS
  deterministic   same input → same bytes
  idempotent      stlc (stlc P) = stlc P
```

Exit code is the signal. stderr names the input path, which here is a server-side
temporary file, so it is never shown to the user.

## The contract suite

`contract/` holds the tests that pin the interface above. They are run by **both** repos:

- here, against the published image, on every change to this repo;
- in the compiler repo, against a freshly built binary, before it publishes anything.

So either side can change freely as long as the interface holds, and whichever side
breaks it finds out in its own pipeline rather than in production.

## Demo programs

The sample programs shown on the page live here, not in the compiler repo — which
examples make a good first impression is a presentation decision. The contract suite
asserts that they still compile, so a syntax change upstream turns the compiler repo's
pipeline red before it ships.

## Layout

```
static/      the page, and the demo program it loads
server/      the service: static files plus POST /api/compile
contract/    what we depend on from the compiler — the compiler repo runs this too
test/        our own service, over HTTP; takes a base URL, so CI and production share it
Dockerfile   compiler image as a build stage, python:slim as the runtime
```

## Running it locally

```
docker build -t lambdalab-web .
docker run --rm -p 8080:8080 lambdalab-web
python3 test/service.py http://127.0.0.1:8080
```

No Lean toolchain required — the compiler arrives prebuilt.

## Deployment

Cloud Run, `europe-west3`, deployed by `.github/workflows/ci.yml` after the tests pass on
`main`. Authentication is Workload Identity Federation: **no service-account key exists**.
GitHub signs a token naming this repository, Google's pool accepts it from here alone, and
the credential it returns lasts minutes.

The service runs as an identity with no permissions at all — it executes arbitrary input
from the internet and should be able to reach nothing. Concurrency is 8 rather than the
default 80, because every request forks a compiler; instances are capped at 3.

One platform quirk worth knowing: Cloud Run's frontend intercepts exactly `/healthz` and
never forwards it, which is why the health endpoint is `/api/health`.
