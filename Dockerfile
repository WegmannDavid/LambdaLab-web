# The website: the published compiler, plus a page and a service to drive it.
#
# The first stage is not a build — it is the compiler repo's artifact, pinned by tag. That
# is the whole coupling between the two repos: no Lean toolchain is installed here, no Lean
# source is checked out, and this image builds in seconds.

ARG COMPILER=ghcr.io/wegmanndavid/lambdalab-compiler:latest
FROM ${COMPILER} AS compiler

FROM python:3.13-slim

# The one file we take from the compiler image. 2.8 MB, dynamically linked against glibc,
# which python:slim (Debian) provides.
COPY --from=compiler /usr/local/bin/stlc /usr/local/bin/stlc

WORKDIR /app
COPY server/ server/
COPY static/ static/

# Unprivileged: the service runs arbitrary user input through a subprocess, and there is no
# reason for that subprocess to be able to write anywhere that matters.
RUN useradd --create-home --uid 10001 app
USER app

ENV PORT=8080
EXPOSE 8080

CMD ["python3", "-u", "server/app.py"]
