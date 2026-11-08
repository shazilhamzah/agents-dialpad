# Contributing

Thanks for helping. agents-dialpad is small on purpose: plain Python (FastAPI) and a dependency-free PWA.

## Setup

```powershell
git clone https://github.com/shazilhamzah/agents-dialpad.git
cd agents-dialpad
uv sync                      # installs runtime + dev dependencies
uv run pytest                # Python unit tests (no agent CLIs needed)
node --test tests/js/markdown.test.js   # Markdown renderer tests (Node 20+)
uv run python -m gateway     # run it; use AG_DATA=<dir> to keep test data away from ./data
```

To try UI changes without touching the copy you normally run, point a second instance at a UI folder:
`AG_STATIC=<folder> AG_DATA=<scratch dir> uv run python -m gateway` (set `"port"` in that dir's `config.json`).

Running the app for real needs an agent CLI (`claude` and/or `agy`) logged in on your machine. The tests do not.

## Guidelines

- Keep it small: no UI framework or build step unless there is a strong reason.
- Never read, copy or proxy provider credentials. agents-dialpad only launches the official CLIs.
- Don't weaken defaults: "Full access" stays opt-in, the server stays loopback-only, project folders stay an
  allowlist, and every API route stays behind the token.
- Validate anything that ends up as a command-line argument (model names, ids). Arguments are passed as a list,
  never through a shell.
- Don't commit personal data: tokens, chats, `data/`, hostnames, local paths.

## Adding an agent (provider)

Copy `gateway/providers/antigravity.py` or `claude.py` and implement the same shape: `name`, `label`,
`available()`, `models()`, optional `limits()`, and `stream(chat, prompt, cwd, run, instructions)` which yields
normalised events (`session`, `text`, `tool_use`, `tool_result`, `usage`, `done`, `error`; see the docstring in
`claude.py`). Register it in `gateway/providers/__init__.py`. Put the parsing of the CLI's output in a small
class so it can be unit tested with sample lines (see `tests/test_parsers.py`).

## Pull requests

- One focused change per PR, with tests for parsing/config/storage logic when you touch it.
- Describe what you tested and on which OS. UI changes: a phone-width screenshot helps.
- By contributing you agree your work is released under the project's [MIT license](LICENSE).
