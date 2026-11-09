# E. Delegation router: send bulky, low-reasoning coding work to cheap models

- **Size:** XL in total, split into tasks E0–E6 (each S–L, each its own branch and PR)
- **Needs first:** D5 (app lock, used to protect endpoint edits). B1 push is optional.
- **Branches:** `feat/e0-router-spike`, `feat/e1-router-core`, `feat/e2-router-validation`, `feat/e3-router-mcp`,
  `feat/e4-router-dashboard`, `feat/e5-router-editing`, `feat/e6-router-agent`

Read [00-rules-for-implementers.md](00-rules-for-implementers.md) first. Every golden rule applies here, and this
feature is the first one that **sends project code off the computer**, so section 11 (security and privacy) is
mandatory reading for every task, not only the one that adds the UI.

---

## 1. Goal

Frontier-model tokens (Claude Opus/Sonnet, used through Claude Code) are the scarce resource. A lot of what a coding
agent produces is bulky and predictable: test cases that follow an existing pattern, docstrings, fixtures, mechanical
API migrations across 30 files, summaries of a 5,000-line log. That work does not need a frontier model. It needs a
competent model, a precise instruction, and a mechanical check that the result is correct.

The router is a small Python component inside agents-dialpad that:

1. takes a **delegation job** (an instruction, a task kind, and the files involved),
2. picks a model through a **waterfall**: free APIs first (Groq for speed, Gemini Flash for very large context), then
   paid Azure AI Foundry deployments (DeepSeek, Phi-4) paid from the $140/month credit,
3. handles **HTTP 429 and other failures** automatically (wait briefly, or cool the model down and fall through),
4. runs the output through a **validation gate** (format, path safety, syntax, optional named checks such as `pytest`),
5. returns a **compact result** so the caller (Claude Code, through MCP) spends a few hundred tokens reviewing instead
   of thousands generating.

The owner sees it all in the PWA (health, quotas, Azure spend, recent jobs, tokens saved) and can **add and edit
providers, models, keys and rules from the frontend**, and start jobs from the phone.

### Non-goals

- Not a general LLM gateway or proxy for other apps. One caller pattern: delegation jobs.
- No LLM-based "router model" deciding where to send work. Routing is deterministic and explainable (section 5).
- No autonomous multi-step agent loop inside the router. A job is one instruction → one validated output (with at most
  one repair round per model). Planning stays with the frontier agent.
- No editing of files outside the job's file list, no deletes, no shell commands chosen by a model.

---

## 2. Architecture

```
                         ┌──────────────────────────── agents_dialpad/router/ ─────────────────────────────┐
 Claude Code ──stdio──►  │ mcp_server.py ─┐                                                                 │
 (MCP tool "delegate")   │                │                                                                 │
 Terminal / Codex ─────► │ cli (delegate) ├─► service.run_job() ─► route.candidates() ─► client.complete() ─┼──► Groq
 PWA (phone) ──/api──►   │ app.py routes ─┘        │                      ▲                   │             │──► Gemini (OpenAI-compatible)
                         │                         │                      │ limits.py          │             │──► Azure AI Foundry
                         │                         ▼                      │ (429, cooldown,    ▼             │──► any OpenAI-compatible URL
                         │                 validate.py (gates G1–G8)      │  breaker, budget)  prompt.py     │    (added from the UI)
                         │                         │                      │                                  │
                         │                         ▼                      │                                  │
                         │                 apply.py (stage / apply) ──────┴──► router.db (SQLite, WAL)       │
                         │                                                     model state, jobs, attempts,  │
                         │  settings.py (router.json)   secrets.py (keyring / router-secrets.json / env)     │
                         └──────────────────────────────────────────────────────────────────────────────────┘
```

Key decisions and why:

| Decision | Why |
|---|---|
| **One OpenAI-compatible client** for all providers (`/chat/completions`), with small per-provider "quirks" (auth header, 429 parsing, `<think>` stripping) | Groq, Gemini (its OpenAI-compatible endpoint) and Azure AI Foundry all speak it. One code path, and the UI can add Ollama, OpenRouter, Cerebras etc. without new code. |
| **SQLite (`<data>/router.db`, WAL mode, stdlib `sqlite3`)** for rate-limit state, jobs and the spend ledger | Several processes share the state: the server, and one MCP server process per Claude Code session. JSON files would race; SQLite handles multi-process writes. Stdlib, no new dependency. |
| **`<data>/router.json`** for providers/models/rules, separate from `config.json` | `config.json` stays hand-edited by the owner (like schedules and quick commands). `router.json` is written by the UI, with an mtime check like `devices.py` so CLI and UI edits do not clobber each other. |
| **Core library usable without the server running** | The MCP server and CLI import `agents_dialpad.router` directly. The dashboard reads the same `router.db`, so jobs started from Claude Code appear in the PWA. |
| **Optional extra `router = ["httpx>=0.27", "mcp>=1.2"]`**, imported lazily | Keeps the base install small (rule 6). `httpx` for async HTTP with timeouts and test transports; the official `mcp` SDK for the stdio server. API routes return 501 when the extra is missing; `doctor` explains how to install it. |
| **Edits as SEARCH/REPLACE blocks**, new files as whole files, never unified diffs from the model | Cheap models produce broken unified diffs constantly. Exact-match search/replace either applies cleanly or fails the gate cleanly. The router builds the diff itself. |
| **Stage by default, apply only after every gate passes** | The frontier agent stays in control and reviews `git diff --stat` plus spot checks, which is cheap. |

### File layout

```
agents_dialpad/router/
  __init__.py        public API: run_job(), status(), Job, JobResult
  settings.py        router.json: load / normalize / save, seeded defaults, validation regexes
  secrets.py         API keys: env var > keyring (if installed) > router-secrets.json; never returned or logged
  db.py              SQLite schema + small DAO (model_state, jobs, attempts, ledger)
  client.py          async OpenAI-compatible client (httpx), per-provider quirks, timeouts
  limits.py          header/429 parsing, cooldowns, circuit breaker, pre-flight quota and budget checks
  route.py           candidate filtering and ordering (pure functions, fully unit tested)
  prompt.py          system prompts and output envelopes per task kind
  validate.py        gates G1–G8
  apply.py           parse SEARCH/REPLACE, apply in memory, diff, stage, apply atomically
  scrub.py           secret detection on outgoing content
  service.py         run_job(): the waterfall loop, ties everything together
  mcp_server.py      stdio MCP server (tools: delegate, delegate_status, delegate_result)
  clock.py           injectable clock/sleep so tests never really wait
```

Plus: routes in `app.py`, a `router` and `delegate` subcommand in `cli.py`, checks in `doctor.py`, the UI in
`static/app.js` + `style.css`, and `.claude/skills/delegate/SKILL.md` (section 10).

---

## 3. Configuration and data

### 3.1 `config.json` (owner, hand-edited): only the master switch

```json
"router_enabled": false
```

Default `false` (golden rule 9). When false, every router route returns 409 "The router is off. Turn it on in
config.json (router_enabled) on the computer.", the MCP tools return the same sentence, and the CLI exits 2. Turning
it on is a deliberate act on the computer, not from a phone.

### 3.2 `<data>/router.json` (UI-editable)

Seeded on first use with the providers below **disabled until a key is present**. Model ids, limits and prices in the
seed are placeholders: E0 confirms them (and the current Azure prices) and the UI's **Test connection** button lists
what the key can really use.

```json
{
  "version": 1,
  "defaults": {
    "max_attempts": 4,
    "deadline_seconds": 180,
    "inline_wait_max_seconds": 8,
    "prefer": "auto",
    "temperature": 0.1,
    "keep_prompts": false,
    "job_retention_days": 14
  },
  "providers": [
    {"name": "groq",   "kind": "groq",   "base_url": "https://api.groq.com/openai/v1", "tier": 1,
     "data_policy": "free-tier", "key_env": "GROQ_API_KEY"},
    {"name": "gemini", "kind": "gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "tier": 1,
     "data_policy": "free-tier-may-train", "key_env": "GEMINI_API_KEY"},
    {"name": "azure",  "kind": "azure",  "base_url": "https://<resource>.services.ai.azure.com/models", "tier": 2,
     "data_policy": "paid", "key_env": "AZURE_AI_API_KEY", "api_version": "<from E0>",
     "monthly_budget_usd": 140, "budget_stop_percent": 85}
  ],
  "models": [
    {"id": "groq/llama-3.3-70b-versatile", "provider": "groq", "model": "llama-3.3-70b-versatile",
     "context": 131072, "max_output": 8192, "quality": 2, "speed": 5, "enabled": true,
     "limits": {"rpm": 30, "tpm": 12000, "rpd": 1000}},
    {"id": "groq/openai-gpt-oss-120b", "provider": "groq", "model": "openai/gpt-oss-120b",
     "context": 131072, "max_output": 16384, "quality": 3, "speed": 4, "enabled": true,
     "limits": {"rpm": 30, "tpm": 8000, "rpd": 1000}},
    {"id": "gemini/gemini-2.0-flash", "provider": "gemini", "model": "gemini-2.0-flash",
     "context": 1048576, "max_output": 8192, "quality": 3, "speed": 4, "enabled": true,
     "limits": {"rpm": 15, "tpm": 1000000, "rpd": 200}},
    {"id": "gemini/gemini-2.5-flash", "provider": "gemini", "model": "gemini-2.5-flash",
     "context": 1048576, "max_output": 65536, "quality": 3, "speed": 3, "enabled": true,
     "limits": {"rpm": 10, "tpm": 250000, "rpd": 250}},
    {"id": "azure/phi-4", "provider": "azure", "model": "Phi-4",
     "context": 16384, "max_output": 4096, "quality": 2, "speed": 4, "enabled": true,
     "price_per_mtok": {"in": 0.125, "out": 0.5}},
    {"id": "azure/deepseek-v3", "provider": "azure", "model": "DeepSeek-V3-0324",
     "context": 131072, "max_output": 8192, "quality": 4, "speed": 3, "enabled": true,
     "price_per_mtok": {"in": 1.14, "out": 4.56}},
    {"id": "azure/deepseek-r1", "provider": "azure", "model": "DeepSeek-R1",
     "context": 131072, "max_output": 32768, "quality": 4, "speed": 1, "enabled": false, "reasoning": true,
     "price_per_mtok": {"in": 1.35, "out": 5.4}}
  ],
  "kinds": {
    "summarize":       {"min_quality": 1, "output": "text",  "prefer": "context"},
    "extract":         {"min_quality": 2, "output": "json",  "prefer": "speed"},
    "docs":            {"min_quality": 2, "output": "edits", "prefer": "speed"},
    "generate":        {"min_quality": 2, "output": "files", "prefer": "speed"},
    "mechanical_edit": {"min_quality": 2, "output": "edits", "prefer": "speed"},
    "tests":           {"min_quality": 3, "output": "edits", "prefer": "quality"},
    "port":            {"min_quality": 3, "output": "files", "prefer": "quality"}
  },
  "projects": {
    "my-app": {"allowed_tiers": [1, 2], "checks": {"pytest": ["uv", "run", "pytest", "-q"]}}
  }
}
```

Field rules (enforced by `settings.normalize()`, which never raises and returns `(clean, problems)` like A4/C4):

- `name`, model `id`: `^[a-z0-9][a-z0-9._/-]{0,63}$`. Upstream `model`: `^[A-Za-z0-9._:/@-]{1,120}$`.
- `base_url`: `https://` only, no user-info, no query/fragment, ≤ 300 chars. Exception: `http://127.0.0.1`,
  `http://localhost`, `http://[::1]` (local Ollama / LM Studio).
- `kind`: `groq | gemini | azure | openai` (generic). Only changes quirks, never the URL.
- `tier`: 1 (free) … 3. `quality`: 1–4, `speed`: 1–5, owner-assigned. `limits` and prices optional.
- `projects.<name>.allowed_tiers`: **default `[]` (nothing leaves the computer for that project)**.
- `projects.<name>.checks`: named argv lists, same validation as quick commands (A4). Models never supply commands;
  the caller can only pick a check by name.

### 3.3 Secrets (`secrets.py`)

Lookup order: the provider's `key_env` environment variable → OS keyring (if the optional `keyring` package is
installed; service name `agents-dialpad-router`) → `<data>/router-secrets.json` (created with `0o600` on POSIX; on
Windows it lives in the per-user `%LOCALAPPDATA%` folder). Keys are write-only from the API: the UI only ever sees
`{"set": true, "source": "env|keyring|file", "hint": "…f3a9"}`. Keys never appear in logs, exceptions, job records or
`doctor` output (rule 5 applies to them exactly like the access token). The `httpx` client is created without request
logging, and every error message passes through `scrub_key()` before it is stored.

### 3.4 `router.db` schema (SQLite, WAL, `busy_timeout=5000`)

```sql
model_state(model_id TEXT PRIMARY KEY, cooldown_until REAL, cooldown_reason TEXT,
            rem_requests INTEGER, rem_tokens INTEGER, reset_requests_at REAL, reset_tokens_at REAL,
            consecutive_failures INTEGER, breaker_open_until REAL, disabled_reason TEXT, updated REAL);
jobs(id TEXT PRIMARY KEY, created REAL, finished REAL, source TEXT /* mcp|cli|ui */, project TEXT, kind TEXT,
     status TEXT /* queued|running|ok|failed|staged|applied|discarded */, model_id TEXT,
     est_in INTEGER, tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, saved_tokens_est INTEGER,
     files_json TEXT, checks_json TEXT, error TEXT, prompt_sha256 TEXT);
attempts(job_id TEXT, n INTEGER, model_id TEXT, started REAL, ms INTEGER, http_status INTEGER,
         outcome TEXT /* ok|rate_limited|cooldown_skip|quota_skip|budget_skip|error|invalid|timeout */, detail TEXT);
ledger(ts REAL, provider TEXT, model_id TEXT, tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL);
```

Job payloads that are large (model output, staged files, diff) live in `<data>/router/jobs/<id>/`, never in the DB.
Prompts are stored only if `keep_prompts` is true. Jobs older than `job_retention_days` are pruned at startup.

---

## 4. The job contract

```python
@dataclass
class Job:
    project: str                 # a configured project name; all paths are relative to its root
    kind: str                    # key of router.json "kinds"
    instruction: str             # ≤ 20,000 chars, written by the caller
    files: list[str]             # files the job may change (≤ 50); read and sent as context
    context_files: list[str]     # read-only context (≤ 50); total sent content ≤ 1.5 MB
    output: str | None = None    # override the kind's default: text | json | edits | files
    json_schema: dict | None = None
    new_files_dir: str | None = None   # "generate"/"port" may create files only inside this folder
    per_file: bool = False       # fan out: one sub-job per entry in files (see 6.6)
    check: str | None = None     # name of a project check to run after applying in a temp copy
    apply: bool = False          # write to the project when every gate passes
    prefer: str | None = None    # speed | context | quality | auto
    max_cost_usd: float = 0.50   # per job, paid tiers only
    min_tier: int = 1            # e.g. 2 to skip the free tier for this job
```

`JobResult` (also the MCP response, kept **compact on purpose**, roughly 150–300 tokens):

```json
{
  "job_id": "4f1c…", "status": "applied",
  "model": "gemini/gemini-2.0-flash",
  "attempts": ["groq/llama-3.3-70b-versatile: skipped (needs 41k tokens, TPM window has 12k)",
               "gemini/gemini-2.0-flash: ok in 9.2s"],
  "files": [{"path": "tests/test_export.py", "added": 142, "removed": 3}],
  "checks": {"format": "pass", "paths": "pass", "syntax": "pass", "placeholders": "pass", "pytest": "pass"},
  "tokens": {"in": 41210, "out": 3920}, "cost_usd": 0,
  "saved_tokens_est": 4300,
  "next": "Review with: git diff --stat; git diff tests/test_export.py"
}
```

`status`: `ok` (text/json returned inline, truncated to 8,000 chars with a pointer to the full output), `staged`
(edits ready, not applied), `applied`, `failed` (with `reason` and every attempt). The full diff is fetched only on
request (`delegate_result(job_id, include_diff=true)`), so the caller pays for it only when needed.

---

## 5. Routing (context-aware, deterministic)

`route.candidates(job, est, settings, state, now) -> list[Candidate]` is a pure function. It produces the ordered
waterfall plus a `skipped` list with reasons (shown in the UI and the result).

### 5.1 Estimate the job

- `est_in = ceil(chars(system + instruction + files + context_files) / 3.2) * 1.10` (code tokenises denser than prose;
  3.2 chars/token plus a 10 % margin is deliberately pessimistic). After each success, the ratio of real
  `usage.prompt_tokens` to the estimate is stored per provider and used as a correction factor (bounded 0.7–1.5).
- `est_out`: for `edits` ≈ 35 % of the changed files' size, for `files` ≈ 110 % of the source size (`port`) or
  `max(2k, instruction-based guess)`, for `text`/`json` 2,000. Capped by each model's `max_output`.

### 5.2 Filter (a model is dropped if any rule fails)

1. Model and provider enabled, key present, provider not `auth_failed`.
2. `provider.tier` is in the project's `allowed_tiers` and `≥ job.min_tier`.
3. `model.quality ≥ kinds[kind].min_quality`.
4. **Fits context:** `est_in + est_out ≤ 0.9 × model.context`.
5. **Fits the rate window:** if the last response headers said `rem_tokens < est_in + est_out` and the reset time has
   not passed, skip (`quota_skip`). This is what sends a 40k-token job straight past Groq's small free TPM to Gemini
   without wasting a request.
6. Not cooling down (`cooldown_until > now`) and breaker not open.
7. **Budget (paid tiers):** `month_spend + est_cost ≤ budget × budget_stop_percent` and `est_cost ≤ job.max_cost_usd`.
8. Reasoning models (`"reasoning": true`, e.g. DeepSeek-R1) only for kinds that list them explicitly, because they are
   slow and spend output tokens on thinking.

### 5.3 Order

Sort key: `(tier ascending, prefer-key, position in router.json)`.

| `prefer` | prefer-key inside a tier | Chosen automatically (`auto`) when |
|---|---|---|
| `speed` | higher `speed` first | default for small jobs |
| `context` | larger free headroom (`context − est_in`) first | `est_in > 24,000` or kind prefers it |
| `quality` | higher `quality` first, then `speed` | kind prefers it (`tests`, `port`) |

Resulting default waterfalls:

| Job | Waterfall |
|---|---|
| Docstrings for one 300-line file (~5k tokens) | Groq 70B → Groq gpt-oss → Gemini 2.0 Flash → Gemini 2.5 Flash → Azure Phi-4 → Azure DeepSeek-V3 |
| Summarise a 300k-token log | Gemini 2.0 Flash → Gemini 2.5 Flash (Groq and Azure skipped: context) → fail |
| Tests from an existing pattern (~20k tokens) | Groq gpt-oss (q3) → Gemini 2.0/2.5 Flash → Azure DeepSeek-V3 (Groq 70B dropped: quality 2 < 3) |
| Same, project allows tier 2 only | Azure DeepSeek-V3 → fail |

Free tiers are always tried first unless the project forbids them (privacy) or the job sets `min_tier: 2`. Paid
models are a **failover**, not a preference, so the $140 lasts.

---

## 6. Fallback logic

### 6.1 The loop (`service.run_job`)

```
candidates = route.candidates(...)
for cand in candidates:                                  # at most max_attempts real calls, overall deadline
    re-check cand state in DB (another process may have cooled it down meanwhile)
    reserve: increment an in-flight counter for (model) inside a DB transaction (per-model concurrency limit, default 2)
    resp = client.complete(cand, messages, timeout=min(120, deadline_left))
    record attempt + update model_state from headers (even on success)
    match outcome:
        ok            -> validate (section 7); if invalid and no repair yet: one repair round on the same model
                         with the gate errors appended; if still invalid -> next candidate
        rate_limited  -> 6.2
        transient     -> 6.3
        fatal_model   -> disable model (404 / unsupported param) -> next
        fatal_auth    -> mark provider auth_failed (401/403) -> next provider
        too_long      -> 400 context_length: tighten the estimate factor for that provider -> next
        filtered      -> content filter -> next
        truncated     -> finish_reason == "length": next candidate with a larger max_output, or split (6.6)
all exhausted -> JobResult(status="failed", reason=..., attempts=[...])     # never a silent partial result
```

### 6.2 HTTP 429 handling

`limits.parse_rate_limit(provider_kind, status, headers, body) -> RateInfo(wait_s, scope, remaining…)`.

| Provider | Where the wait comes from (E0 confirms exact shapes) |
|---|---|
| Groq | `retry-after` (seconds); `x-ratelimit-remaining-requests` / `-tokens`; `x-ratelimit-reset-requests` / `-tokens` as durations like `2m59.56s` or `7.66s` |
| Gemini | 429 `RESOURCE_EXHAUSTED`; `RetryInfo.retryDelay` (`"17s"`) and `QuotaFailure` violations whose quota id names the window (`…PerMinute…`, `…PerDay…`). The OpenAI-compatible endpoint may wrap the error in a list: parse both shapes |
| Azure AI Foundry | `retry-after` and/or `retry-after-ms`; `x-ratelimit-remaining-requests` / `-tokens` |
| Generic | `retry-after` (seconds or HTTP date), else default 30 s |

Decision:

```
wait = rate.wait_s (fallback 30s; daily scope fallback: until next reset, else 1h)
if rate.scope != "day" and wait <= inline_wait_max (8s) and deadline_left > wait + p50_latency(model):
    sleep(wait + jitter(0..1s)); retry the same model once          # short bursts: cheaper than falling through
else:
    model_state.cooldown_until = now + wait; reason = "429 per-minute" | "daily quota"
    continue with the next candidate immediately                    # never block the caller on a long wait
```

The cooldown is written to SQLite, so **every** process (other Claude Code sessions, the server, the CLI) skips that
model until it resets. The UI shows "cooling down, 41 s" or "daily quota used, resets ~09:00".

### 6.3 Transient errors (408, 409, 5xx, connect/read timeout, broken stream)

One retry on the same model after `1 s × 2^n + jitter`, then the next candidate. Each counts toward the circuit
breaker: **3 consecutive failures → breaker open for 120 s**, then half-open (one probe job allowed; success closes it,
failure doubles the open time up to 30 min). 429s do not count toward the breaker; they have their own cooldown.

### 6.4 Budget guard (Azure)

Every paid response adds a ledger row using `usage` × `price_per_mtok`. `month_spend` is the sum since the 1st of the
month (local time). At `budget_stop_percent` (default 85 % of $140 = $119) paid models are filtered out and the UI
and `delegate_status` say so; B1 push sends one alert at 70 % (reusing C3's alert pattern). The real Azure bill is the
source of truth: the ledger is an estimate, which is why the stop is below 100 %.

### 6.5 Deadline and attempts

`deadline_seconds` (180) and `max_attempts` (4 real calls, skips do not count) bound every job. A job that hits
either returns `failed` with what was tried. The caller then does the work itself (section 10.4).

### 6.6 Fan-out (`per_file=true`) and splitting

Bulky repetitive work is usually "the same thing to N files". With `per_file`, the job becomes N sub-jobs that share
the instruction and context files. They run concurrently, bounded by per-model concurrency and `rpm`, so they spread
across the free models naturally as each one hits its window. The parent result aggregates: `"files": 27 ok,
2 failed (listed)`. A single sub-job that is truncated is retried once on a model with a larger `max_output`; the
router never splits one file's edit across calls.

---

## 7. Output validation gate (`validate.py`)

The prompt (`prompt.py`) asks for a strict envelope per output type, at temperature 0.1:

```
FILE: agents_dialpad/export.py
<<<<<<< SEARCH
def to_markdown(chat):
=======
def to_markdown(chat: dict) -> str:
    """Render a chat as Markdown."""
>>>>>>> REPLACE

NEW FILE: tests/test_export_extra.py
<<<<<<< CONTENT
…whole file…
>>>>>>> END
```

`text` jobs return plain text; `json` jobs use `response_format: {"type": "json_object"}` where the provider supports
it, plus the schema check below. DeepSeek-R1 `<think>…</think>` blocks are stripped before parsing.

Gates run cheapest first and stop at the first failure. Each failure produces a short, specific message that is fed
back in the single repair round (for example `SEARCH block 2 for export.py matched 0 times; first line was "def
to_md(chat):"`).

| Gate | Checks | Applies to |
|---|---|---|
| **G1 complete** | `finish_reason == "stop"`; not empty; no refusal phrases | all |
| **G2 format** | Envelope parses; JSON parses and matches `json_schema` (small built-in validator: `type`, `properties`, `required`, `items`, `enum`; uses `jsonschema` if installed) | all |
| **G3 paths** | Every path is in `files`, or a new file inside `new_files_dir`; relative; no `..`; resolves inside the project root (rule 3); not git-ignored; not a secret-looking name | edits, files |
| **G4 apply** | Every SEARCH block matches **exactly once** in the original content (whitespace-tolerant second pass on line-trimmed text, reported as a warning); applied in memory only | edits |
| **G5 syntax** | `.py`: `ast.parse`; `.json`: `json.loads`; `.toml`: `tomllib`; `.js`/`.mjs`: `node --check` if `node` is on PATH (via `subprocess.run([...])`, timeout 10 s); others skipped and reported as "not checked" | edits, files |
| **G6 sanity** | No placeholder bodies (`# ... rest of`, `// existing code`, `pass  # TODO`, `...` as a whole function body); a file does not lose more than 40 % of its lines unless the instruction allows deletion; no new top-level imports of modules that are neither stdlib, in `pyproject.toml`, nor in the project | edits, files |
| **G7 secrets** | `scrub.py` patterns on the output (keys, tokens, private-key blocks); output must not contain the instruction's secrets either | all |
| **G8 check** (opt-in) | The named project check (e.g. `pytest`) runs in a **temporary copy** (`git worktree add --detach` on a temp dir when the project is a git repo, else a copy of the touched files over a shallow copy) with the edits applied; timeout 300 s; output tail (≤ 4,000 chars) kept | edits, files, only when `check` is set |

Then `apply.py`:

- **Stage** (default): write `patch.diff` (built with `difflib.unified_diff`) and the new file contents under
  `<data>/router/jobs/<id>/`. Status `staged`.
- **Apply** (`apply=true`, or later via the UI / `delegate_result(apply=true)`): only if every gate passed **and** every
  target file still has the SHA-256 recorded when the job read it (otherwise 409 "changed since the job started").
  Write each file atomically (temp file + `os.replace`). Never deletes, never touches files outside the job.
- Apply is refused when the chat/permission context is read-only: the MCP server takes the mode from
  `AG_ROUTER_MODE` (`stage` | `apply`, default `stage`), and the UI/CLI follow the same rule as chats (rule 6).

---

## 8. Integration surfaces

### 8.1 Python API

```python
from agents_dialpad.router import run_job, status, Job
result = await run_job(Job(project="my-app", kind="docs", instruction="…", files=["agents_dialpad/export.py"]))
```

### 8.2 CLI (added to `cli.py`, listed in `COMMANDS`)

```bash
agents-dialpad delegate --project my-app --kind tests --file agents_dialpad/export.py \
    --context tests/test_export.py --instruction-file task.md --check pytest [--apply] [--json]
agents-dialpad delegate --project my-app --kind summarize --file logs/build.log --instruction "What failed and why?"
agents-dialpad router status          # models, state (ready / cooling 41s / breaker / no key), quotas, month spend
agents-dialpad router test [PROVIDER] # one tiny call per model, prints latency and the rate-limit headers it saw
agents-dialpad router key set groq    # reads the key from a hidden prompt (getpass), never from argv
agents-dialpad router jobs [--limit 20]
agents-dialpad router mcp             # run the stdio MCP server (what Claude Code launches)
```

The instruction is read from a file or stdin when long (Windows 32k command-line limit, rules §8).

### 8.3 MCP server (`router/mcp_server.py`, official `mcp` SDK, stdio)

Registered once per machine (exact syntax confirmed in E0):

```bash
claude mcp add --scope user dialpad-router -- agents-dialpad router mcp
```

Tools:

| Tool | Arguments | Returns |
|---|---|---|
| `delegate` | `project` (or omitted: inferred from the session's cwd if it is a configured project), `kind`, `instruction`, `files`, `context_files`, `output?`, `json_schema?`, `new_files_dir?`, `per_file?`, `check?`, `apply?`, `prefer?`, `max_cost_usd?` | compact `JobResult` (section 4) |
| `delegate_status` | none | which kinds can run right now, models ready / cooling, month spend, today's jobs and tokens saved (≤ 120 tokens) |
| `delegate_result` | `job_id`, `include_diff?`, `apply?` | the diff (capped at 30,000 chars) and/or applies a staged job |

Tool descriptions are short and state the rule of thumb from section 10, so the model sees the criteria at the moment
it decides. The server writes nothing to stdout except protocol messages (log to `<data>/router/mcp.log`, rotated).
The same server works for Codex and Antigravity if they are configured with it.

### 8.4 HTTP API (all on the `api` router, token required, rule 1)

| Route | Purpose |
|---|---|
| `GET /api/router` | overview: enabled, extra installed, models with live state and quota, month spend and budget, today's jobs/success/tokens saved |
| `PATCH /api/router/defaults` | edit `defaults` |
| `POST /api/router/providers` · `PATCH`/`DELETE /api/router/providers/{name}` | add / edit / remove a provider |
| `PUT`/`DELETE /api/router/providers/{name}/key` | set / remove a key (body `{"key"}` ≤ 512 chars) → 204, never echoed |
| `POST /api/router/providers/{name}/test` | calls `GET /models` (timeout 15 s) → model ids (≤ 200) + rate-limit headers seen |
| `POST /api/router/models` · `PATCH`/`DELETE /api/router/models/{id}` · `POST /api/router/models/order` | manage models and waterfall order |
| `PATCH /api/router/kinds/{kind}` | min quality, prefer, output |
| `PATCH /api/router/projects/{project}` | `allowed_tiers` only. `checks` are **not** editable over HTTP: commands stay in the hand-edited file (rule 9) |
| `POST /api/router/models/{id}/reset` | clear cooldown / breaker / disabled flag |
| `GET /api/router/jobs?limit=50` · `GET /api/router/jobs/{id}` · `GET /api/router/jobs/{id}/diff` | job list, detail with attempts, diff |
| `POST /api/router/jobs` (202) · `GET /api/router/jobs/{id}/stream` (SSE) | start a job from the phone and watch attempts live |
| `POST /api/router/jobs/{id}/apply` · `POST /api/router/jobs/{id}/discard` | act on a staged job |

Edits go through `settings.normalize()`; invalid input → 400 with the problem sentence. Body limit 64 KB (jobs: 1 MB).

---

## 9. UI (PWA)

Sidebar **More** menu → **Router** (new icon `route`: `<circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/>
<path d="M8 19h8a3 3 0 0 0 0-6H8a3 3 0 0 1 0-6h8"/>`). It opens a sheet with four segments:

1. **Overview**
   - Status line: "Router on · 3 of 6 models ready · $23.40 of $140 this month" (or the off/extra-missing notice).
   - Today: jobs, success rate, *estimated Claude tokens saved* (sum of `saved_tokens_est`), with a 14-day bar chart
     (reuse the usage chart styles from C3).
   - One card per model in waterfall order: status pill (`Ready`, `Cooling 41 s`, `Daily quota used`, `Paused after
     errors`, `No key`, `Over budget`), requests/tokens remaining bars from the last headers, p50 latency, a **Reset**
     action on a paused model. Azure card shows a spend bar with the stop line at 85 %.
2. **Providers & models**: the waterfall as a list with **Move up / Move down** buttons (no drag: it is unreliable on
   phones and inaccessible). **Add provider** form: name, type (Groq / Gemini / Azure AI Foundry / OpenAI-compatible),
   base URL, API key (password field, write-only, shows "Key set …f3a9 (from keyring)" afterwards), tier, data policy.
   **Test connection** fills a model picker from `/models`. **Add model**: model id (picker or typed), context, max
   output, quality, speed, limits, prices, enabled.
3. **Jobs**: newest first, each row "tests · my-app · Gemini 2.0 Flash · 9 s · applied". Detail shows the attempt
   chain as a vertical list ("Groq 70B: skipped, needs 41k tokens…", "Gemini: ok"), gate results, and the diff using
   the B2 change-viewer diff renderer, with **Apply** / **Discard** for staged jobs (`confirmSheet` before apply).
   **New job** opens a form: project, kind, files (picker from B2's file list for that project), instruction, check,
   apply toggle; progress streams over SSE.
4. **Rules**: per kind (min quality, prefer); per project, which tiers may receive its code (checkboxes "Free models",
   "Paid models"; both off by default) with the provider data-policy labels next to them, e.g. "Gemini free tier:
   Google may use prompts to improve its products".

All text via `esc()`, sentence case, 44 px targets, light/dark tokens, checked at 320/375/768/1280 px (rules §6).

---

## 10. When Claude should delegate (criteria)

This section becomes `.claude/skills/delegate/SKILL.md` (shipped in the repo and copied to the user's skills by
`agents-dialpad router install-skill`), plus the short form in the MCP tool descriptions.

### 10.1 Delegate when all of these hold

1. **Output-heavy, reasoning-light.** You already know *what* the result must look like; producing it is typing.
   Examples: tests that mirror an existing test file, docstrings/type hints across files, fixtures and sample data,
   boilerplate routes/models from a spec, mechanical API migration or rename across many files, porting a module to
   another language with the same structure, i18n strings, summarising a large log/file/diff you would otherwise read.
2. **Big enough to pay off.** Expected output ≥ ~1,500 tokens (~150 lines), or input you would have to read ≥ ~10k
   tokens (summarise jobs). Rule of thumb: delegate when `expected output tokens ≥ 4 × (instruction tokens + review
   tokens)`. Output tokens are the expensive ones, so output-heavy jobs win most.
3. **Fully specified in ≤ ~40 lines of instruction**, with the pattern to copy given as a context file.
4. **Mechanically checkable**: syntax at minimum, ideally a named check (`pytest`) that will catch mistakes.
5. `delegate_status` says the kind can run now (one cheap call at the start of a bulky phase, not before every job).

### 10.2 Never delegate

- Anything security-sensitive: auth, tokens, crypto, permission checks, path validation, approvals, app lock (in this
  repo: `applock.py`, `devices.py`, `approvals.py`, auth parts of `app.py`, the golden rules themselves).
- Design decisions, debugging with an unknown cause, cross-cutting refactors that need judgement, anything where you
  cannot state the expected result precisely.
- Small edits (< ~40 lines): the round trip and review cost more than doing it.
- Files containing secrets, `.env*`, credentials, or projects whose `allowed_tiers` is empty.

### 10.3 How to delegate well

- Pass the closest existing example as a `context_files` entry and say "follow the style of X".
- Prefer `per_file=true` for "same change to N files".
- Use `check` whenever the project has one; ask for `apply=true` only with a check.
- Review with `git diff --stat` plus targeted reads of risky hunks, not the whole diff. You remain responsible.

### 10.4 When it fails

If a job fails, read `reason` and the attempts once. Fix an unclear instruction and retry **at most once**. If the
same kind fails twice in a session, or all models are cooling/over budget, do the work yourself and stop delegating
that kind for the rest of the session. Never loop.

---

## 11. Security and privacy (mandatory for every E task)

- **Code leaves the computer.** This breaks the default of golden rule 8, so it is opt-in three times:
  `router_enabled` in `config.json` (on the computer), a provider key, and per-project `allowed_tiers` (default none).
  SECURITY.md gets a section: what is sent (instruction + listed files), to whom, retention, and that free tiers may
  use prompts for training (owner must check each provider's current terms; prefer the paid tier for proprietary code).
- **Outgoing scrub (`scrub.py`)** before every call: refuse (not silently redact) files named `.env*`, `*.pem`,
  `*.key`, `id_rsa*`, `*credentials*`, git-ignored files, and content matching key patterns (`AKIA…`, `sk-…`,
  `ghp_…`, `AIza…`, `xox[bp]-…`, `-----BEGIN … PRIVATE KEY-----`, long high-entropy values assigned to
  `*_KEY|*_TOKEN|*_SECRET|password`). The refusal lists `file:line` so the caller can exclude it.
- **Endpoint edits are sensitive.** A stolen phone token could add `https://evil.example` and route code there. So:
  adding a provider or changing a `base_url` requires a fresh app-lock verification when app lock is on (D5), sends a
  push "Router endpoint added: <host>" when push is on, and is written to `<data>/router/audit.log`. `doctor` lists
  every configured host.
- **Keys** are handled like the access token (rule 5). They are never in argv (`router key set` uses `getpass`), never
  in URLs, never in job records.
- **No model-chosen commands.** Checks are named argv lists from the hand-edited `router.json` `projects` section,
  run with `subprocess.run([...])`, no shell (rule 2), in a temp copy, with a timeout.
- **Limits everywhere** (rule 4): instruction 20k chars, 50 + 50 files, 1.5 MB sent content, 2 MB response read limit,
  timeouts on every call, 8k/30k caps on returned text/diff, 200 jobs listed, retention 14 days.

---

## 12. Tasks

Each task follows the usual shape: branch from `main`, baseline green, verify first, steps, tests, docs, acceptance.

### E0. Spike: confirm the external facts (S)

**Read first:** this file, `tools/spikes/` (style of earlier spikes).
**Do:** `tools/spikes/router_spike.py`, run by the owner with real keys from environment variables. Record in
`docs/plans/E0-findings.md` (no keys, no resource names):

1. Groq: response headers on success and on a forced 429 (burst a small model); exact header names and formats.
2. Gemini OpenAI-compatible endpoint: success headers (are there rate-limit headers at all?), the exact 429 body
   (list-wrapped or not, where `retryDelay` and the quota id live); whether `gemini-2.0-flash` is still served and
   what the current free-tier limits and data-use terms are; `response_format` support.
3. Azure AI Foundry: the endpoint form for serverless DeepSeek and Phi-4 deployments (`…services.ai.azure.com/models`
   vs `…/openai/v1`), required `api-version`, auth header (`api-key` vs `Authorization: Bearer`), how the model is
   selected (body `model` vs deployment in the URL), 429 headers, `usage` fields, and the R1 `<think>` format.
4. `GET /models` on each, to seed the UI picker.
5. The `mcp` SDK version and its stdio server API; the exact `claude mcp add` syntax; that a stdio server launched
   through the `uv tool` shim works on Windows (`.exe` shim, no console window flash, stdout clean).
6. Real tokens-per-char for Python/JS on two providers (to check the 3.2 estimate).

**Acceptance:** findings file merged; this plan corrected where the findings differ (seed models, 429 table, Azure URL).

### E1. Core library, waterfall and CLI (L)

**Read first:** `config.py`, `devices.py` (mtime reload pattern), `usage.py`, `cli.py`, `doctor.py`, E0 findings.
**Steps:**
1. Add the `router` optional extra (`httpx`, `mcp`), `uv lock`. `config.load()`: `cfg.setdefault("router_enabled", False)`.
2. `clock.py`, `settings.py` (seed, `normalize`, save with mtime check), `secrets.py`, `db.py` (schema, WAL,
   migrations by `PRAGMA user_version`).
3. `client.py`: one `complete()` returning `Response(status, headers, json, text, finish_reason, usage, ms)`; quirks
   per kind from E0; injectable `httpx` transport.
4. `limits.py`: `parse_rate_limit`, `parse_duration("2m59.56s")`, header → `model_state` update, cooldown, breaker.
5. `route.py`: `estimate`, `candidates` exactly as section 5 (pure).
6. `service.py`: the loop of 6.1–6.5 for `text` and `json` outputs (no file edits yet), ledger, jobs, attempts.
7. CLI: `delegate` (text/json kinds), `router status|test|key|jobs`. `doctor`: extra installed, keys present (never
   values), hosts list, db writable.

**Tests** (`tests/test_router_*.py`, `httpx.MockTransport`, fake clock, never the internet):
`test_groq_reset_duration_is_parsed`, `test_gemini_retry_delay_is_parsed_from_list_wrapped_body`,
`test_short_429_waits_inline_then_succeeds_on_same_model`, `test_long_429_cools_model_and_falls_through`,
`test_cooldown_is_shared_between_two_service_instances` (two `run_job` against one db file),
`test_daily_quota_skips_model_until_reset`, `test_job_too_big_for_groq_tpm_goes_to_gemini_without_a_request`,
`test_context_overflow_skips_small_models`, `test_three_failures_open_breaker_and_probe_closes_it`,
`test_401_marks_provider_auth_failed`, `test_budget_stop_filters_paid_models`, `test_project_without_allowed_tiers_is_refused`,
`test_deadline_returns_failed_with_attempts`, `test_key_never_appears_in_job_record_or_error`.

**Acceptance:** `agents-dialpad delegate --kind summarize` works end to end against the fakes; with real keys the
owner sees Groq → Gemini fall-through when Groq is rate limited.

### E2. Validation gate, edits, stage and apply (M–L)

**Read first:** `gitview.py` (git helpers, diff), `quick.py` (named commands), `uploads.py` (path checks).
**Steps:** `prompt.py` envelopes per output; `apply.py` (parse, exact-once match, in-memory apply, `difflib` diff,
stage, atomic apply with SHA check); `validate.py` G1–G8; `scrub.py` (outgoing and G7); repair round; `per_file`
fan-out with per-model concurrency; CLI `--apply`, `--check`.

**Tests:** `test_search_block_matching_twice_fails_the_gate`, `test_path_outside_project_is_rejected`,
`test_gitignored_file_is_never_sent`, `test_env_file_is_refused_with_file_and_line`, `test_python_syntax_error_triggers_one_repair_round`,
`test_placeholder_body_fails_sanity_gate`, `test_truncated_output_moves_to_larger_max_output_model`,
`test_apply_refused_when_file_changed_since_job_start`, `test_check_runs_in_temp_copy_not_project`,
`test_per_file_job_spreads_across_models_when_one_is_rate_limited`, `test_new_file_only_inside_new_files_dir`.

**Acceptance:** a `tests` job on a temp git repo produces a staged diff; with `--check` and `--apply` the files are
written only when the check passes; the working tree is untouched otherwise.

### E3. MCP server and the delegation skill (M)

**Read first:** E0 findings (SDK, `claude mcp add`), section 8.3 and 10.
**Steps:** `mcp_server.py` (three tools, compact results, project inference from cwd against configured project
roots, mode from `AG_ROUTER_MODE`); `agents-dialpad router mcp`; `agents-dialpad router install-skill` (copies
`.claude/skills/delegate/SKILL.md` to the user skills folder, `--dry-run`); README "Use it from Claude Code".

**Tests:** tool functions called in-process (schema of arguments, compact output under 1,200 chars), one real stdio
round trip (`initialize` → `tools/list` → `tools/call delegate_status`) with `sys.executable -m agents_dialpad router mcp`
and a fake provider; `test_mcp_stdout_contains_only_protocol_messages`; `test_stage_mode_never_writes_files`.

**Acceptance:** in a real Claude Code session, the owner asks "add docstrings to every function in export.py" and
Claude calls `delegate`, gets a staged/applied result, and reviews with `git diff --stat`.

### E4. HTTP API (read-only) and the Router dashboard (M)

**Read first:** `app.py` (`/usage`, `/limits`, `/schedules` routes), the C3 usage sheet and B2 diff viewer in `app.js`.
**Steps:** `GET /api/router`, jobs list/detail/diff, model reset, apply/discard of staged jobs; More menu item and the
Overview + Jobs segments (read-only apart from apply/discard/reset).

**Tests:** routes need the token; 409 when `router_enabled` is false; 501 when the extra is missing; jobs created by a
CLI run (separate `run_job`) appear in `GET /api/router/jobs`; `key` never in any response
(`test_router_overview_never_contains_key_material`).

**Acceptance:** UI checks at 320/375/768/1280, light and dark; a cooling model shows a live countdown.

### E5. Editing from the frontend and phone-started jobs (M–L)

**Read first:** `applock.py` and the D5 "recent unlock" check, `push.py`, section 9 and 11.
**Steps:** provider/model/kind/project-tier routes with `normalize`; key PUT/DELETE; Test connection; reorder; the
Providers & models and Rules segments; the New job form with SSE progress; audit log; push on new endpoint host;
app-lock gate on endpoint changes.

**Tests:** `test_http_base_url_is_rejected_except_localhost`, `test_new_provider_host_requires_recent_unlock_when_lock_is_on`,
`test_key_put_returns_204_and_is_never_echoed`, `test_reorder_changes_waterfall`, `test_concurrent_edit_from_cli_is_not_lost`,
`test_project_checks_cannot_be_set_over_http`, `test_job_from_ui_streams_attempt_events`.

**Acceptance:** from the phone, the owner adds an OpenAI-compatible provider (for example a local Ollama on
`http://127.0.0.1:11434/v1`), tests it, adds a model, moves it to the top, runs a job, and sees it used.

### E6. The router as a chat agent (optional, M)

A `RouterProvider` in `providers/` (name `router`, label "Cheap models") so the owner can chat with the waterfall
from the phone for quick questions, using the normal chat UI. Read-only by design: it yields `session`, `text`,
`usage`, `done` events only, no tools, so no permission level applies. Every reply notes which model answered.
Tests extend `test_integration.py` with the fake transport.

---

## 13. Risks and open questions

| Risk | Mitigation |
|---|---|
| Free-tier limits and model names change often (Gemini 2.0 Flash may be retired) | Nothing hard-coded beyond the seed; Test connection lists live models; a 404 disables the model with a visible reason |
| Cheap models produce plausible but wrong code | Gates G1–G8, named checks, stage-by-default, and Claude's review; kinds with `min_quality` |
| Token estimate wrong → 400 or wasted calls | Pessimistic estimate, per-provider learned correction, 400 handling |
| Azure ledger drifts from the real bill | Stop at 85 %, show "estimated", let the owner correct `month_spend` offset in the UI |
| Privacy (free tiers training on code) | Per-project tiers default to none; data-policy labels in the UI; SECURITY.md |
| MCP process per Claude session competing for quotas | Shared SQLite state, per-model concurrency limit across processes |
| Savings are invisible / overestimated | `saved_tokens_est = tokens_out + min(tokens_in, 20k) × 0.2 − instruction_tokens`; labelled as an estimate; real Claude usage from C3 shown next to it for comparison |

Open questions for the owner before E1:

1. Is sending code from your work projects to free-tier Gemini/Groq acceptable, or should tier 1 be limited to
   personal projects (the default "none" per project handles either answer)?
2. Install `keyring` as part of the `router` extra (better key storage on Windows) or keep the file fallback only?
3. Should E6 (router as a chat agent) be built at all?
