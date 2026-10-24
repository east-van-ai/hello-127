# Changelog

## [Unreleased]

## [0.1.1] - 2026-10-24

### Added

- Published on PyPI: `uv tool install hello-127` installs the `hello-127` command.
- The package metadata links the repository and the changelog.

## [0.1.0] - 2026-10-23

### Added

- `tunnel` carries TCP from a container to a service on the Mac's 127.0.0.1, as
  frames over the standard streams of `docker exec -i` or `container exec -i`.
- `--forward` sets each listener and its target, repeatable through one helper; both
  ends must be a 127.x address.
- `ollama-query` asks Tiny Aya through the tunnel from inside the container, with
  `--connect` naming the address and port the tunnel listens on.
- The helper and the probe need only the standard library, on Python 3.10 or later.
