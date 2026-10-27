# Changelog

## [Unreleased]

## [0.2.0] - 2026-10-27

### Added

- The container side also comes in JavaScript, Perl, Ruby, PHP, and BusyBox sh, sent
  to `node -e`, `perl -e`, `ruby -e`, `php -r`, or `busybox sh -c`, for Node 20,
  Perl 5.34, Ruby 3.3, PHP 8.2, or BusyBox 1.36 with the full `nc`.
- `ollama-query` in Perl and BusyBox only checks that Ollama answers, and prints
  `Ollama is running`.
- `tunnel` and `ollama-query` detect the language: they try `python3`, `node`,
  `perl`, `ruby`, `php`, then `busybox`, take the first one present and new enough,
  and name it on stderr.
- `--languages LIST` on both commands sets the languages to try, in order; one name
  pins one language. With none left, one line says what each language found.
- `languages RUNTIME CONTAINER` names the container's image, then lists every
  choice with what the container has: the interpreter and its version, or why it is
  unusable.
- `docs/LANGUAGES.md` walks through the tunnel, both ways, on Node, Perl, Ruby, PHP,
  and BusyBox images.
- `docs/STRESS.md` records how many connections each language holds at once, and
  how each breaks; a unit test holds a hundred through every one.
- `tunnel --in` runs the other way: the Mac listens, and the helper dials a service
  inside the container. One tunnel carries `--out` and `--in` together.

### Changed

- `--forward` is renamed `--out`, and `tunnel` has no default forward: it needs at
  least one `--out` or `--in`.
- The package metadata names the author without an email address.

### Fixed

- The programs sent into the container are read as UTF-8 instead of the system's
  code page.

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
