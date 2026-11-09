# D3 Findings: Codex Readiness & Error Behaviors

Recorded from live runs of `codex-cli 0.164.0` (windows-x86_64).

---

## 1. `codex login status`

### Signed in
- **Exit code:** `0`
- **Stdout:** `Logged in using ChatGPT` (or `Logged in using API key`)
- **Stderr:** (empty)

### Signed out (or missing credentials)
- **Exit code:** `1`
- **Stdout:** `Not logged in`
- **Stderr:** (empty)

**Conclusion:** `codex login status` exists and reliably distinguishes signed-in from signed-out via both exit code and stdout string.

---

## 2. `codex --version`
- **Exit code:** `0`
- **Stdout:** `codex-cli 0.164.0`

---

## 3. `codex exec` with Default Model from `~/.codex/config.toml`

When `~/.codex/config.toml` specifies `model = "gpt-6.1-sol"`, running without `-m`:
- **Exit code:** `1`
- **JSONL output:**
  ```json
  {"type":"error","message":"{\"type\":\"error\",\"status\":400,\"error\":{\"type\":\"invalid_request_error\",\"message\":\"The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account.\",\"code\":\"model_not_found\"}}"}
  {"type":"turn.failed","error":{"message":"{\"type\":\"error\",\"status\":400,\"error\":{\"type\":\"invalid_request_error\",\"message\":\"The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account.\",\"code\":\"model_not_found\"}}"}}
  ```
- The inner error object contains:
  - `status`: `400`
  - `error.code`: `"model_not_found"`
  - `error.message`: `"The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."`

---

## 4. State Mapping for `status()`

- Provider not installed (`_exe() is None`): `{"state": "not_installed", "note": "not installed"}`
- `codex login status` exit code `0` and "Logged in" in output: `{"state": "ready", "note": ""}`
- `codex login status` exit code != `0` or "Not logged in" in output: `{"state": "not_signed_in", "note": "Codex isn't signed in on the computer"}`
- Process execution failure / timeout: `{"state": "unknown", "note": ""}`
