# isemass

`isemass` is a Python CLI for mass operations related to Cisco ISE.

The `coa` command performs Cisco ISE API Change-of-Authorization requests from MAC addresses
found in an input text file. The `swauth` command is still a placeholder for future switch SSH
reauthentication work.

## Development

```bash
uv sync
uv run isemass --help
uv run pytest
uv run ruff check .
```

## Commands

```bash
isemass init
isemass coa --input-file macs.txt --host ise-mnt.example.com --node ise-psn01
isemass coa --input-file macs.txt --host ise-mnt.example.com --node ise-psn01 --yes
isemass swauth
```

`isemass init` creates `settings.toml` in the operating system's standard user config directory
for the `isemass` app. 

`isemass coa` accepts colon, dash, and Cisco dotted MAC formats, normalizes them to uppercase
colon format, removes duplicates, prompts for the API password, previews the target MAC list, and
asks for confirmation before sending requests. Use `--insecure` or `insecure = true` only when you
need to skip HTTPS certificate validation.

## Input Config

Priority of configuration input is this order:
1. CLI arguments
2. settings.toml values
3. back-end defaults (in defaults.py)
