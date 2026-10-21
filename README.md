# Arabic diacritizer service

A small public reconstruction of an Arabic diacritization worker for an Upwork
application. This is independently written demo code, not the client's code.
It adds a native Windows deployment path, persisted human corrections, contract
tests and reproducible offline measurements around an OpenAI-compatible API.

The validator rejected 1,200/1,200 generated corrupt outputs and accepted 200/200
correct outputs, and 100 fake HTTP requests had 1.97 ms median and 2.31 ms p95 latency.
I verified those results with `uv run python scripts/measure.py` over a real
loopback HTTP socket and `uv run pytest -q`, which passed 93 tests on Python 3.14.8.

## Run locally

Python >=3.11 and [uv](https://docs.astral.sh/uv/) are required. PowerShell:

```powershell
uv sync --locked
Copy-Item .env.example .env
uv run python -m app
```

Open <http://127.0.0.1:8020/> for the separately built UI, or use `/docs` for the
interactive API documentation. Stop the foreground process with Ctrl+C.
The example uses `FAKE_PROVIDER=1` and `SERVICE_KEY=dev-key`; there are no paid calls.
The fake dictionary has 16 entries. Unknown text is returned unchanged, so the fake
mode demonstrates preservation and rejection, not general Arabic language quality.

```powershell
$Headers = @{ 'X-Service-Key' = 'dev-key' }
$Body = @{ text = 'ذهب الولد إلى المدرسة'; request_id = 'demo-1' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8020/v1/diacritize `
  -Headers $Headers -ContentType 'application/json; charset=utf-8' `
  -Body ([Text.Encoding]::UTF8.GetBytes($Body))
```

Expected output text: `ذَهَبَ الْوَلَدُ إِلَى الْمَدْرَسَةِ`.
Add `simulate = 'added_word'` to the request to get a 422 after two failed attempts.
Other supported simulations are `removed_word`, `translation`, and `markdown`.
They fail both the initial and repair response, and are ignored with real providers.

For a real provider, edit this checkout's `.env`: set `FAKE_PROVIDER=0`, a strong
`SERVICE_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY`, then restart.
URLs are API roots such as `https://api.openai.com/v1`; the client appends
`/chat/completions`. Set `FALLBACK_BASE_URL`, `FALLBACK_MODEL`, `FALLBACK_API_KEY`,
and `FALLBACK_PROVIDER` to enable a secondary OpenAI-compatible provider.
No real provider was called during this build.

## Architecture and behavior

```text
ASP.NET / local demo UI
  -> FastAPI + X-Service-Key
  -> primary provider [bounded transport retries]
       -> secondary provider on timeout or upstream 5xx
  -> strip permitted diacritics and compare exact base text
       -> one repair call if validation fails
  -> validated response + total successful-call usage + cost estimate

human correction -> base-text check -> SQLite transaction
```

`app/validation.py` contains pure functions; `app/providers.py` handles HTTP;
`app/corrections.py` owns SQLite; `app/main.py` implements the shared contract.
The process reuses an async httpx connection pool, and correction writes use their
own SQLite connections. Run one service instance for this demo.

The removable diacritics are exactly U+064B through U+0652 and U+0670. Tatweel
(U+0640) must be preserved as a base character. No whitespace, punctuation, Unicode
normalization, hamza, or spelling changes are accepted. Existing permitted marks
are ignored in the base comparison, so they may be corrected too. This tests text
preservation, not whether the selected vowels are linguistically correct.

New Markdown wrappers and JSON objects/arrays are rejected before base comparison.
For other mismatches, increased/decreased whitespace-delimited word counts map to
`added_words`/`removed_words`; equal counts map to `changed_letters`. A translation
therefore uses one of those reasons, not a separate reason outside the contract.

`MAX_RETRIES` means extra transport attempts **per provider per validation attempt**,
bounded from 0 to 5. Timeouts and 5xx responses are retried then fall back. Other
HTTP errors, connection failures and malformed responses map to 502 immediately.
An exhausted timeout maps to 504. Validation gets at most two completions total.
Each timeout applies to httpx network phases, not the entire request wall clock.
Real providers must return string content and nonnegative integer token usage.
HTTP proxy environment variables are not inherited by the provider client.

Usage sums successful completions including repair. Estimates use configured
`LLM_INPUT_COST_PER_MILLION`/`LLM_OUTPUT_COST_PER_MILLION` and corresponding
`FALLBACK_*` rates in USD. Their defaults are zero, meaning **pricing unconfigured**.
Fake mode reports zero tokens and cost. Failed upstream calls may still be billed;
their unavailable token usage cannot be included in the estimate.

## API and configuration

The exact schemas are in [API-CONTRACT.md](API-CONTRACT.md). All `/v1/*` endpoints
require `X-Service-Key`; both the current and optional previous key are evaluated
with constant-time comparisons. Health and the demo page are public.

| Route | Purpose |
| --- | --- |
| `GET /` | Serve the UI agent's `static/index.html` |
| `GET /health/live` | Process liveness |
| `GET /health/ready` | Configuration metadata; no paid provider probe |
| `POST /v1/diacritize` | Diacritize and validate, with one repair attempt |
| `POST /v1/corrections` | Persist a correction; 201 on success |
| `GET /v1/corrections?limit=20` | Latest stored records, including original text |

Error bodies use the contract's 401, 413, 422, 502 and 504 shapes. Schema errors
use `validation_failed/empty`, attempts 0; malformed correction requests use
`invalid_correction/base_text_mismatch`. Those schema-error mappings and a 1..100
listing limit fill details the shared contract does not specify. IDs are generated
when omitted. The response body and JSON logs retain a supplied ID; the optional
`X-Request-ID` header uses a generated UUID when a supplied ID cannot safely fit
in an HTTP header. Request IDs are at most 128 characters and notes at most 2,000.

[.env.example](.env.example) lists all configuration. Nonsecret environment
variables override that file; **keys are read only from this repo's own `.env`**,
with interpolation disabled. Parent `.env` files and inherited credential variables
are never used. Tests set `DIACRITIZER_SKIP_DOTENV=1` before importing the app and
inject isolated settings and databases. `python -m app` reads HOST/PORT; direct
uvicorn CLI arguments, including the service XML, set the listener explicitly.

Application logs are JSON with request IDs and no source/output text unless
`LOG_TEXT=1`. Correction records intentionally contain raw text and must be
protected and retained according to the deployment's policy. See
[docs/corrections.md](docs/corrections.md) for the stored shape and change-count
definition. No provider keys or upstream error bodies are logged.

## Reproduce the measured result

```powershell
uv run pytest -q
uv run python scripts/measure.py
# Optional larger sample:
uv run python scripts/measure.py --n 1000 --requests 500
```

Measured on Windows, Python 3.14.8, on 2026-10-21. `pytest -q`: **93 passed in
0.78s**, with one upstream Starlette deprecation warning for its httpx test client.
The validator corpus has 200 distinct numbered inputs per corruption type plus
200 correct outputs. It is synthetic and is not a linguistic accuracy benchmark.
The HTTP measurement makes ten warmup requests followed by 100 serial requests
cycling through all 16 dictionary entries. It includes JSON, authentication,
validation and a real TCP connection, with no paid LLM or disk correction write.
The measurement server is shut down in `finally`; its SQLite file is under ignored
`data/`. Logs are disabled for this latency measurement. Timings vary by machine.

Actual `scripts/measure.py` output:

| Validator case | Result |
| --- | --- |
| added_word rejected | 200/200 |
| removed_word rejected | 200/200 |
| changed_letter rejected | 200/200 |
| markdown rejected | 200/200 |
| json rejected | 200/200 |
| translation rejected | 200/200 |
| All bad outputs rejected | 1200/1200 |
| Correct outputs accepted | 200/200 |

| Fake HTTP latency | Result |
| --- | --- |
| Successful measured requests | 100/100 |
| Median | 1.97 ms |
| p95 (nearest rank) | 2.31 ms |
| Mean | 2.03 ms |

Tests cover all validation reasons and supported combining marks, mock HTTP success,
timeout/5xx fallback, malformed data, bounded retries, repair, usage/cost aggregation,
current/previous/missing/wrong auth, exact error bodies, logging, correction rejection,
listing and persistence across app restarts. No test reads a developer `.env`.

## Native Windows service

Follow [docs/DEPLOY-WINDOWS.md](docs/DEPLOY-WINDOWS.md) for a second-engineer runbook:
all-users Python, uv, LocalService permissions, a protected `.env`, loopback and
the ASP.NET firewall rule, install, recovery verification, reboot, logs, update
and rollback. Scripts and [WinSW XML](deploy/windows/diacritizer.xml) are in
`deploy/windows/`. The service uses a machine-wide venv and Automatic delayed
startup, five second failure recovery and rotating logs.

**The WinSW SHA256 pin is a marked placeholder.** The installer refuses to run
until an independently verified hash is supplied. No service has been installed,
WinSW downloaded, firewall changed, or reboot performed during this build.
Scripts and XML were parsed locally; native service behavior remains to be measured.
The default assumes ASP.NET is on the same machine. A remote-host adaptation needs
a private listener, narrow firewall access and TLS as described in the runbook.

### Results on a real Windows machine

| Check | Result | Evidence |
| --- | --- | --- |
| Restart after killing Python | TODO: seconds | Omar: run `deploy/windows/verify.ps1` |
| Up after reboot | TODO: pass/fail and boot-to-start seconds | Omar: reboot, then run `verify.ps1 -AfterReboot` |
| OS / Python / WinSW versions | TODO | Record tested machine and date |

Repository commits are local only. There is no configured remote and nothing has
been pushed. The UI agent owns `static/`; it is served but is outside these backend
commits.
