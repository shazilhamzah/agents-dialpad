# C2. Codex as a third agent

- **Size:** M–L
- **Needs first:** nothing
- **Branches:** `spike/c2-codex` then `feat/c2-codex`
- **PR title:** `feat: Codex agent support`

## Goal

"Codex" stops being greyed out. Users can pick it in the new-chat sheet and use it like the other two: streaming
replies, tool calls shown, conversation memory, the three permission levels, and model choice.

## What we know (checked when this plan was written, codex-cli 0.164.0)

- `codex exec` runs non-interactively. `--json` prints events as JSONL.
- `-C, --cd <DIR>` sets the working folder; `-m, --model <MODEL>` picks a model; `--skip-git-repo-check` allows
  folders that are not git repositories; `--ephemeral` exists.
- `-s, --sandbox <MODE>` accepts `read-only`, `workspace-write`, `danger-full-access`.
  `--dangerously-bypass-approvals-and-sandbox` skips everything.
- `codex exec resume [SESSION_ID] [PROMPT]` resumes a previous session by id.
- **Not yet known:** the exact JSONL event names and fields, where the session id appears, and whether the prompt can be
  read from stdin.

## Part 0: spike (no product code)

1. In an empty temp folder run, and save the full output:
   `codex exec --json --skip-git-repo-check -C <folder> -s read-only "Reply with exactly: pong"`
2. Then a prompt that runs a command (`-s workspace-write`, "run `echo hello` and tell me the output").
3. Find the session id in the output, then run `codex exec resume <id> --json "what did I ask before?"` and check it
   remembers. Check which flags `resume` accepts (`codex exec resume --help`).
4. Check whether the prompt can come from stdin (try passing `-` as the prompt and piping text). This matters because
   Windows command lines are limited to about 32,000 characters.
5. Check whether usage (tokens) appears in the events.
6. Write `docs/plans/C2-findings.md` with anonymised example lines for: session start, text output (streamed or whole),
   command start/end with output, errors, the final event, and usage. Save them as `tests/fixtures/codex/*.jsonl`.

Stop and have the owner review.

## Part 1: provider

1. `agents_dialpad/providers/codex.py`, modelled on `claude.py`:
   - `name = "codex"`, `label = "Codex"`, executable from `AG_CODEX` (default `codex`), extra args `AG_CODEX_ARGS`.
   - Modes: `readonly → ["-s", "read-only"]`, `edit → ["-s", "workspace-write"]`,
     `full → ["--dangerously-bypass-approvals-and-sandbox"]` (only reachable when `allow_full_access` is on, as today).
   - Always add `--json --skip-git-repo-check -C <cwd>`; `-m <model>` when set.
   - First turn: `codex exec ...`; later turns: `codex exec resume <session_id> ...` (as recorded in Part 0).
   - Prompt via stdin if Part 0 showed it works; otherwise as an argument with the same length check as Antigravity
     (`MAX_PROMPT_CHARS`), and say so in the README.
   - Instructions: prepend to the first prompt like Antigravity does, unless Part 0 found a dedicated option.
   - A `_Parser` class that turns the recorded JSONL into our normalised events (`session`, `text`, `tool_use`,
     `tool_result`, `done`, `error`). Unknown event types are ignored.
   - `models()`: `[{"id": "", "label": "Default"}]` plus `cfg.get("codex_models", [])` entries (strings).
2. Register it in `providers/__init__.py`; remove Codex from `PLANNED`.
3. `doctor.py`: add Codex to `agent_checks()` (it counts towards "at least one agent").
4. `tests/fake_agents/fake_codex.py` replaying the recorded format (SLOW/TOOL/DENY behaviours like the other fakes).

## Tests

- `tests/test_parsers.py`: feed every fixture from Part 0 through `codex._Parser`.
- `tests/test_integration.py`: `test_codex_turn_and_resume`, `test_codex_modes_map_to_sandbox_flags`,
  `test_codex_full_access_needs_the_flag`, `test_codex_stop`. Extend the `env` fixture with `AG_CODEX`/`AG_CODEX_ARGS`.

## Manual check

Real Codex: read-only question, an edit in a test repo with "Can edit files", resume after a restart of agents-dialpad.

## Docs

README: requirements list, permissions table column for Codex, known gaps. CHANGELOG. `config.example.json`: `"codex_models": []`.

## Acceptance checklist

- [x] Findings file and fixtures exist.
- [x] Codex appears as available when installed, works for all modes, resumes conversations.
- [x] Full access for Codex only when `allow_full_access` is true.
