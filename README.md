# isemass

`isemass` is a Python CLI for mass operations related to Cisco ISE.

Current routines include:
- **coa**: CoA (Change-of-Authority) for multiple MAC address from an input text file, using Cisco ISE Monitoring Open API
- **swauth**: Reauthenticate ISE sessions from NAD's directly (WIP)


## Requirements

This should work on Windows, MacOS, and Linux.

## How to Install

You can use `pip` or `pipx`, but the preferred is to use `uv`. First, install uv on your system:

https://docs.astral.sh/uv/getting-started/installation/

Then install the tool simply with:
```
uv tool install isemass
```

Next, optionally, you can initialize the `settings.toml` file which can be used to set configuration for the tool:
```
isemass init
```
(This is optional, as the tool will run with all CLI arguments, if you prefer)


## How to Use (coa) (TODO)




## Commands (TODO)

```bash
isemass init
isemass coa --input-file macs.txt --host ise-mnt.example.com --node ise-psn01
isemass coa --input-file macs.txt --host ise-mnt.example.com --node ise-psn01 --yes
isemass coa --input-file macs.txt --host ise-mnt.example.com --node ise-psn01 --output-file coa-results.json
isemass swauth
```


`isemass coa` accepts colon, dash, and Cisco dotted MAC formats, normalizes them to uppercase
colon format, removes duplicates, prompts for the API password, previews the target MAC list, and
asks for confirmation before sending requests. Use `--insecure` or `insecure = true` only when you
need to skip HTTPS certificate validation.

Use `-o/--output-file` or `[coa].output_file` to write detailed per-MAC JSON results after all CoA
requests complete.

## Configuration Order

The tool with take priority of configuration inputs is this order:
1. CLI arguments
2. `settings.toml` values (if set)
3. Backend defaults (set in `defaults.py`)
