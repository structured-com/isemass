# isemass

`isemass` is a Python CLI framework for mass operations related to Cisco ISE.

This first iteration only includes the CLI shape, project packaging, and optional settings
loading. Cisco ISE API calls, SSH commands, MAC parsing, and concurrent execution will be added
later.

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
isemass swauth
```

`isemass init` creates `settings.toml` in the operating system's standard user config directory
for the `isemass` app.

