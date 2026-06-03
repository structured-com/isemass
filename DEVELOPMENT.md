# Development Guide

This document is intended to give a developer or AI coding assistant a fast technical map of the
`isemass` project. Read this with `README.md` for user-facing behavior and `BUILD.md` for release
and packaging notes.

## Project Summary

`isemass` is a Python CLI package for mass Cisco ISE related operations. The `isemass coa`
routine reads MAC addresses from a text file, normalizes and deduplicates them, asks for
confirmation, then performs Cisco ISE CoA Reauth API requests concurrently.

The `isemass swauth` routine reads switch/MAC pairs from CSV, groups MAC addresses by switch, and
uses Netmiko SSH sessions to clear matching switch authentication sessions concurrently.

## Technical Stack

- Python package layout: `src/isemass/`
- Build backend: `uv_build`
- Package/dependency manager: `uv`
- CLI framework: `click`
- Console rendering: `rich`
- Config location: `platformdirs.user_config_dir("isemass")`
- Config format: optional `settings.toml`, parsed with stdlib `tomllib`
- HTTP client: `requests`
- SSH client: `netmiko`
- CSV parsing: `pandas`
- HTTPS warning control: `urllib3`
- XML parsing: stdlib `xml.etree.ElementTree`
- Tests: `pytest`
- Linting: `ruff`

## Runtime Flow

Configuration priority is:

1. CLI arguments
2. Values from platform-specific `settings.toml`
3. Backend defaults in `src/isemass/defaults.py`

`isemass init` writes packaged `settings.toml` and `ssh_config` templates into the platformdirs
config directory. Existing files are left untouched unless `--force` is used.

`isemass coa` resolves options, prompts for any missing username, prompts for the API password
without storing it, extracts MAC addresses, previews the unique MAC list, asks for confirmation
unless `--yes` is provided, and runs CoA requests with a `ThreadPoolExecutor`.

Screen results are printed as each worker completes. Optional JSON output is written only after all
requests finish, ordered by the original normalized MAC list rather than by completion time.

`isemass swauth` resolves options, prompts for any missing switch username, prompts for the switch
password without storing it, validates the input CSV, prints warnings for skipped rows, groups valid
MAC addresses by switch, and runs one Netmiko SSH worker per switch.

## CoA Implementation Notes

Supported input MAC formats are colon, dash, and Cisco dotted notation. All matches are normalized
to uppercase colon format.

The CoA URL format is:

```text
https://{host}/admin/API/mnt/CoA/Reauth/{node}/{mac}/0
```

Each request uses:

- Method: `GET`
- Header: `Accept: application/xml`
- Auth: HTTP Basic auth from username and prompted password
- Timeout: 30 seconds
- TLS verify: `not insecure`

`CoaResult` is the central result object. It stores:

- `success`: true only when ISE reports `remoteCoA.results=true`
- `result_message`: short human-readable result
- request metadata
- response status, headers, and raw body
- parsed `remoteCoA.results`
- exception type/message when applicable

Passwords and auth tuples must not be stored in `CoaResult` or written to JSON.

## Result Classification

CoA responses are classified in this order:

1. Requests `SSLError`: `HTTPS certificate validation failed`
2. Other request or worker exceptions: `Undefined failure`
3. HTTP `401` or `403`: `Invalid API credentials`
4. Response text containing `No NAS_IP_ADDRESS associated with the calling station id`: `MAC address not a valid session`
5. Parsed `remoteCoA.results=true`: `CoA Succeeded`
6. Parsed `remoteCoA.results=false`: `CoA attempted but no response from network device`
7. Anything else: `Undefined failure`

## Swauth Implementation Notes

Supported input CSV columns are `switch_address` and `mac_address`; extra columns are ignored.
Each `mac_address` cell must contain exactly one colon, dash, or Cisco dotted MAC address. MAC
addresses are not normalized for `swauth`.

The Netmiko connection uses:

- `device_type`: `cisco_xe`
- `host`: CSV `switch_address`
- `username` and prompted password
- `ssh_config_file`: `platformdirs.user_config_dir("isemass") / "ssh_config"`

For each MAC on a switch, `swauth` runs:

```text
show authentication sessions mac {mac_address} detail
```

If the result contains `No sessions match supplied criteria`, the MAC result is `No Session Found`.
Otherwise, `swauth` runs:

```text
clear authentication sessions mac {mac_address}
```

## Testing And Verification

Primary checks:

```bash
uv run pytest
uv run ruff check .
uv run isemass coa --help
uv run isemass swauth --help
```

Build/package checks are covered in `BUILD.md`.

Tests avoid real network calls by patching the CoA runner or injecting fake request functions.
Tests avoid real switch SSH by injecting fake Netmiko connection handlers. When changing CLI
behavior, update `tests/test_cli.py`. When changing CoA parsing, request handling, result
classification, or JSON serialization, update `tests/test_coa.py`. When changing switch CSV
validation, grouping, SSH command behavior, or result handling, update `tests/test_swauth.py`.

## File Map

Ignored local artifacts such as `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `dist/`,
`old_references/`, `test*.txt`, and `test*.json` are not part of this file map.

| File | Summary |
| --- | --- |
| `.gitignore` | Defines ignored development artifacts, build output, old references, and local test input/output files. |
| `BUILD.md` | Developer notes for local tool install, wheel builds, tagging, and publishing. |
| `DEVELOPMENT.md` | Technical project guide for developers and AI assistants. |
| `LICENSE` | Apache-2.0 project license. |
| `README.md` | User-facing overview, install notes, command examples, and configuration precedence. |
| `pyproject.toml` | Package metadata, dependencies, console script entry point, pytest config, and Ruff config. |
| `uv.lock` | Locked dependency graph generated by `uv`. |
| `src/isemass/__init__.py` | Package initializer and package version constant. |
| `src/isemass/cli.py` | Click CLI entry point, config resolution, command definitions, prompts, and Rich output formatting. |
| `src/isemass/coa.py` | CoA domain logic: MAC parsing, request execution, response classification, concurrency, and JSON serialization. |
| `src/isemass/config.py` | Platformdirs config path handling, optional TOML loading, default merge logic, and template writing. |
| `src/isemass/console.py` | Shared Rich `Console` instance. |
| `src/isemass/defaults.py` | Backend defaults used when settings are absent. |
| `src/isemass/swauth.py` | Switch reauthentication domain logic: CSV validation, grouping, Netmiko execution, and concurrency. |
| `src/isemass/templates/__init__.py` | Makes packaged templates importable with `importlib.resources`. |
| `src/isemass/templates/settings.toml` | Packaged settings template written by `isemass init`. |
| `src/isemass/templates/ssh_config` | Packaged OpenSSH config template written by `isemass init` for Netmiko switch SSH. |
| `tests/test_cli.py` | CLI behavior tests for help output, config precedence, prompts, confirmation, and JSON output wiring. |
| `tests/test_coa.py` | Unit tests for MAC parsing, CoA request construction, classification, warning suppression, and JSON serialization. |
| `tests/test_swauth.py` | Unit tests for CSV validation, switch grouping, and Netmiko command handling. |

## Common Change Guidance

- Keep CLI orchestration in `cli.py`; keep Cisco ISE CoA behavior in `coa.py`.
- Preserve config precedence: CLI argument, then `settings.toml`, then backend default.
- Do not add secrets to `settings.toml`, JSON output, or result objects.
- Prefer small, direct helpers over broad abstractions.
- Add focused tests before or with behavior changes; mock network calls.
- Keep local manual test files named `test*.txt` or `test*.json` so they remain ignored.
