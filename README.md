# LambdaLab-web

The web playground for [LambdaLab](https://github.com/WegmannDavid/LambdaLab): paste a
program, press run, see it round-tripped through the verified parser and printer.

This repo owns everything web-facing — the page, the HTTP service that fronts the
compiler, the container image, and the deployment. It does **not** contain any Lean, and
building it does not require a Lean toolchain.

## The interface it consumes

The compiler is consumed as a published artifact, not as source:

```
ARTIFACT  ghcr.io/wegmanndavid/lambdalab-compiler:<tag>
  /usr/local/bin/stlc      executable, glibc only

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

## Status

Early. Nothing built yet beyond this README.
