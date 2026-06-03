# isemass

`isemass` is a Python CLI for mass operations related to Cisco ISE.

Current routines include:
- **coa**: Perform CoA (Change-of-Authority) for multiple MAC addresses from an input text file, using Cisco ISE Monitoring Open API
- **swauth**: Reauthenticate ISE sessions from NAD's directly over switch SSH


## Requirements

This should work on Windows, MacOS, and Linux.


## How to Install

You can use `pip` or `pipx`, but the preferred is to use `uv`. First, install uv on your system:

https://docs.astral.sh/uv/getting-started/installation/

Then install the tool simply with:
```
uv tool install isemass
```

Next, optionally, you can initialize generated config files:
```
isemass init
```
This creates:
- `settings.toml`, which can be used to set configuration for the tool.
- `ssh_config`, which `swauth` passes to Netmiko for Cisco switch SSH compatibility.

This is optional for `coa`, as the tool will run with all CLI arguments. For `swauth`, running
`isemass init` is recommended so the Cisco SSH `ssh_config` file is available (needed for older switches).


## Configuration Order

The tool with take priority of configuration inputs is this order:
1. CLI arguments
2. `settings.toml` values (if set)
3. Backend defaults (set in `defaults.py`)


## How to Use (coa)

First, you can see help for all options:
```
isemass coa --help
```

Here is a typical example of using the CoA routine:
```
isemass coa --input-file macs.txt --host ise-mnt.example.com --node ise-psn01
```
Notable mandatory fields are:
- `input-file`: This input file contains MAC address in any cleaned or uncleaned text format. The tool will parse and find all MAC addresses automatically.
- `host`: The main URL host to perform the Monitoring API. This is typically the MnT node. Use FQDN or IP.
- `node`: The PSN node to run the CoA from. This can be any PSN node in the environment. Use short node name only (not FQDN or IP)

Also: to perform operations using the Monitoring APIs, the users must be assigned to one of the following Admin Groups and must be authenticated against the credentials stored in the Cisco ISE internal database (internal admin users):
- Super Admin
- System Admin
- MnT Admin


## How to Use (swauth)

First, you can see help for all options:
```
isemass swauth --help
```

Here is a typical example of using the switch reauthentication routine:
```
isemass swauth --input-file switches-and-macs.csv --username switch-admin
```

The input CSV must include these columns:
- `switch_address`: Switch IP address, hostname, or FQDN.
- `mac_address`: One MAC address in colon, dash, or Cisco dotted format.

Repeated `switch_address` values are expected. `swauth` groups MAC addresses by switch, opens one
SSH session per switch worker, checks each MAC with `show authentication sessions mac ... detail`,
and clears found sessions with `clear authentication sessions mac ...`.

