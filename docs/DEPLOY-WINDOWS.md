# Deploy on Windows Server 2019

This runs Python directly as a Windows service through WinSW 2.12.0 x64. It needs
neither WSL nor containers. The default topology is ASP.NET and the worker on the
same Windows machine. The worker binds `127.0.0.1:8020`. ASP.NET holds the service
key server side and calls that loopback address. Never include the production key
in a browser page. The browser UI is a local demonstration for an operator.

These steps change machine configuration. They have not been run as part of the
demo build. Only PowerShell syntax and XML parsing have been checked. Record the
actual recovery and reboot evidence in the README after running them.

## 1. Prerequisites

Use an elevated 64-bit Windows PowerShell 5.1 session. Install a supported CPython
version >=3.11 for **all users**, for example `C:\Program Files\Python314`, with pip
and the standard library. Choose an installer that supports your server's patch
level. Do not use the Microsoft Store alias, a user profile Python, or a WSL Python.
The build tests used Python 3.14.8; Server 2019 compatibility must be checked here.

Install uv using your organization's approved method, and ensure `uv --version`
works in the elevated shell. The service does not run uv; only installation and
updates use it. Its venv points to the all-users Python, so keep that interpreter
installed and readable by the service account. Verify before proceeding:

```powershell
& 'C:\Program Files\Python314\python.exe' --version
uv --version
```

Keep the source checkout outside the deployment directory. The installer copies
the application to `C:\ProgramData\ArabicDiacritizer`, creates `.venv` there with
`uv sync --locked --no-dev`, and disables uv interpreter downloads. It never uses
a virtual environment or managed Python in an operator's profile.

## 2. Pin the WinSW artifact

The only download URL in `install.ps1` is the official fixed release:
[WinSW v2.12.0](https://github.com/winsw/winsw/releases/tag/v2.12.0).
The artifact is `WinSW-x64.exe`. No binary is included in this repository.

`$WinSWSha256` is empty, so installation stops before creating directories or
downloading anything. Obtain the artifact through your organization's trusted
review process, verify its identity, and set the approved SHA256 in `install.ps1`.
A hash of an unverified download alone does not establish its identity. The
installer compares the download against the pin before executing WinSW and removes
the download on a mismatch.

## 3. Configure credentials and permissions

From the source checkout:

```powershell
Copy-Item .env.example .env
notepad .env
```

Choose a long random `SERVICE_KEY`; do not deploy `dev-key`. First use
`FAKE_PROVIDER=1` for installation and recovery checks. For paid calls later set
`FAKE_PROVIDER=0`, `LLM_PROVIDER`, `LLM_BASE_URL` (ending in `/v1` for typical
providers), `LLM_MODEL`, and `LLM_API_KEY`. A secondary provider is optional:
set all four `FALLBACK_*` identity, URL, model and key fields to enable it. Both
providers must support `/chat/completions` with a `usage` object.

Credentials are read only from the application's own `.env`, without variable
interpolation or parent-directory discovery. Inherited key variables are ignored.
Nonsecret settings can be overridden by environment variables. Leave `DB_PATH`
relative as `data/corrections.db`, `LOG_TEXT=0`, `HOST=127.0.0.1`, `PORT=8020`.
The service XML explicitly sets its bind address and port; changing `.env` does not
override those uvicorn arguments. Limit and timeout changes take effect on restart.

The supplied service identity is `NT AUTHORITY\LocalService`, requiring no stored
account password. The installer protects the deployment directory with an exact
ACL: SYSTEM and Administrators have full control; LocalService has read and execute.
Only `data` and `logs` grant LocalService modify permission. `.env` inherits the
protected read ACL, and it stays out of Git. Inspect afterward with:

```powershell
icacls C:\ProgramData\ArabicDiacritizer
icacls C:\ProgramData\ArabicDiacritizer\.env
icacls C:\ProgramData\ArabicDiacritizer\data
```

Protect the source `.env` as well using your organization's credential handling
policy; the installer sets ACLs only on the deployed copy. Do not put secrets in
XML, shell history, scripts, version control or support tickets.

If policy requires a dedicated domain account or gMSA, review the WinSW service
account configuration and grant it read/execute plus modify only on data and logs.
Grant "Log on as a service" using your normal policy tools. Amend the installer ACL
SIDs for that account before deployment; the supplied scripts support LocalService.

## 4. Install and verify the access boundary

Windows Firewall must be enabled with default inbound Block on all profiles.
The script refuses to proceed otherwise. Inspect existing allow rules for Python
and TCP 8020 and remove broader access through your normal firewall policy process.
An additional narrow allow rule cannot override another broad allow rule.

```powershell
.\deploy\windows\install.ps1 -ASPNET_HOST_IP 127.0.0.1 `
  -PythonExe 'C:\Program Files\Python314\python.exe'
Get-Service ArabicDiacritizer
Invoke-RestMethod http://127.0.0.1:8020/health/live
Invoke-RestMethod http://127.0.0.1:8020/health/ready
Get-NetTCPConnection -LocalPort 8020 -State Listen
Get-NetFirewallRule -Name ArabicDiacritizer-ASPNET | Get-NetFirewallAddressFilter
```

The listener must report `127.0.0.1`. From another machine a connection to the
server's network IP on 8020 should fail. Test a missing or wrong `X-Service-Key`
and confirm 401, then configure the correct key in ASP.NET's server-side secret
store and confirm a successful request. Local loopback alone cannot distinguish
processes on the same host; the secret provides that application boundary.

If ASP.NET is on **another host**, the default loopback listener cannot accept it,
even if `ASPNET_HOST_IP` allows that host in the firewall. Before deployment, change
the XML `--host` to a private interface, use the actual ASP.NET host IP in the
installer, and terminate TLS on a private reverse proxy with an explicit route and
network policy. Keep port 8020 off the public network. That alternate network
topology is not demonstrated or measured here.

## 5. Measure recovery and reboot startup

Run from the source checkout in an elevated shell during an agreed test window:

```powershell
.\deploy\windows\verify.ps1
```

It first checks live health, verifies the installed wrapper's path, finds only
uvicorn Python descendants of `ArabicDiacritizer`, force-kills those processes,
and measures until health responds with new service-owned Python PIDs. It does
not kill arbitrary Python processes. It times out after 90 seconds by default.
Record the printed seconds and OS/Python versions in the README. Review the event
log to confirm the recovery was performed by SCM rather than by an operator.

The XML uses Automatic delayed startup, three restart entries with a five second
delay, and a one hour failure reset. WinSW repeats the last recovery action after
the configured sequence, so further failures continue restarting at five seconds.
See the [WinSW v2 XML documentation](https://winsw.github.io/v2/doc/xmlConfigFile/).

Reboot manually when permitted. After logging back in, without manually starting
the service, run:

```powershell
.\deploy\windows\verify.ps1 -AfterReboot
```

This checks live health, the configured Automatic/delayed mode, and prints OS boot
time, service-wrapper process creation time, and their difference. It does not kill
anything in this mode. Process timestamps alone cannot prove that no one started
the service manually; retain the test procedure and SCM event log evidence along
with the result. Delayed startup can take minutes after boot. Run the switch only
after an actual reboot; the script itself never reboots the machine.

## 6. Logs and key rotation

`C:\ProgramData\ArabicDiacritizer\logs` holds captured stdout/stderr and WinSW's
own wrapper log. Application records are JSON with request IDs, provider/model,
attempt, validity, usage/cost, status and latency. Source/output text is omitted
unless `LOG_TEXT=1`; keys and upstream error bodies are never logged. Uvicorn's
startup/shutdown diagnostics and the WinSW wrapper log use their own formats.
Access logs are disabled in the XML. Each captured stream rotates at 10 MiB and
keeps eight archived files, per the [WinSW logging documentation](https://winsw.github.io/v2/doc/loggingAndErrorReporting/).

To rotate a service key, edit only the protected deployed `.env`: move the old key
to `SERVICE_KEY_PREVIOUS`, put the new key in `SERVICE_KEY`, restart the service,
and update ASP.NET. After verifying the new key, clear the previous key and restart
again. Both keys are compared with `hmac.compare_digest` on every authenticated
request. Never set the previous key to a default development key.

## 7. Update and rollback

Use a maintenance window; the demo has a single instance and no zero-downtime
update mechanism. Obtain the approved revision in a separate source directory.
Do not run `install.ps1` over an existing service; it refuses to do so.

1. Record the current revision and run the source tests and measurement script.
2. Stop `ArabicDiacritizer` and wait for Stopped. Make a protected backup of `app`,
   `static/index.html`, `pyproject.toml`, `uv.lock`, `diacritizer.xml`, `.env`, and the
   complete `data` directory. Preserve ACLs; use a separate admin-only backup folder.
3. Copy the new `app` directory and lock/project files to the deployment directory.
   Copy `static/index.html` if the approved revision includes it. Preserve the
   deployed `.env` and data; remove stale source modules deliberately if needed.
4. In `C:\ProgramData\ArabicDiacritizer` run the following as administrator:

```powershell
$env:UV_PROJECT_ENVIRONMENT = 'C:\ProgramData\ArabicDiacritizer\.venv'
$env:UV_CACHE_DIR = 'C:\ProgramData\ArabicDiacritizer\.uv-cache'
$env:UV_PYTHON_DOWNLOADS = 'never'
uv sync --locked --no-dev --python 'C:\Program Files\Python314\python.exe'
if ($LASTEXITCODE -ne 0) { throw 'Dependency update failed; do not start the service.' }
Start-Service ArabicDiacritizer
Invoke-RestMethod http://127.0.0.1:8020/health/ready
```

5. Verify an authenticated fake or approved real request, a correction write and
   read, and the recovery test. Recheck `.env`, code and data permissions.
6. For rollback, stop the service, restore the backed-up code and lock files, run
   the same locked sync against the previous project, and start/verify again.
   This version has no schema migration; preserve live corrections unless an
   explicit database restore is required. If restoring data, stop first and restore
   the entire consistent database set. If changing XML recovery or account settings,
   consult WinSW's service refresh procedure and recheck SCM configuration.

For removal, `uninstall.ps1` stops/removes the named service and its named firewall
rule. It retains all deployment files and correction data for deliberate backup
and later removal. It does not delete any directories recursively.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Installer immediately stops | Set the WinSW checksum after independent artifact verification |
| Python cannot be started after logout/reboot | All-users interpreter path and LocalService execute permission; never use a profile venv base |
| Service starts and exits | Wrapper/error logs, missing own `.env`, empty service key, invalid provider configuration or denied DB directory |
| Health works but diacritization returns 401 | Header name, current/previous key, deployed `.env`, and restart after edits |
| 502 | Upstream HTTP error, malformed response or missing token usage; inspect provider settings without exposing secrets |
| 504 | Both configured providers exhausted timeout attempts; review `TIMEOUT_S` and outbound connectivity |
| 422 validation_failed | Inspect reason and request ID; source changed or output wrapped; there is exactly one repair attempt |
| Corrections fail to write | LocalService modify permission on the data directory and available disk space |
| Remote ASP.NET cannot connect | Default is loopback; confirm intended topology before changing the bind address |
| Recovery test times out | SCM failure actions, WinSW log, Python descendant PIDs, and port conflicts |

Worst case per request is two validation attempts times (primary plus configured
fallback) times (`MAX_RETRIES + 1`) transport calls, each with the configured httpx
timeout for network phases. This is not a strict total wall-clock deadline. An
ASP.NET timeout should allow the intended retry budget, or reduce the budget.
