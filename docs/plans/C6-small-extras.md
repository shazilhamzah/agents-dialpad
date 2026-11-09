# C6. Per-project instructions

- **Size:** S
- **Needs first:** nothing
- **Branch:** `feat/c6-project-instructions`
- **PR title:** `feat: per-project instruction files`

## Goal

Besides the global `instructions_file`, each project can have its own instructions, added after the global ones. For
example: a terse style for every project, plus "this repo uses pnpm, never npm" for one project.

## Config

A project can stay a plain path, or become an object:

```json
"projects": {
  "workspace": "workspace",
  "my-app": { "path": "C:\\code\\my-app", "instructions_file": "C:\\code\\my-app\\.agents-dialpad.md" }
}
```

## Read first

`agents_dialpad/config.py` (`load`, `read_instructions`, `resolve_instructions_path`), `agents_dialpad/runs.py`
(`get_instructions`), `agents_dialpad/app.py` (where `RunManager` is created), `agents_dialpad/cli.py` (`project` commands),
`agents_dialpad/doctor.py`.

## Steps

1. `config.load()`: when a project value is a dict, take `path` (required string) for `cfg["projects"][name]` (so
   everything that reads `cfg["projects"]` keeps getting a plain path) and store `instructions_file` (optional) in
   `cfg["_project_instructions"][name]`. A dict without `path` is skipped and reported by doctor.
2. `config.read_instructions(cfg, project=None)`: global text, then (if any) the project's text, separated by a blank
   line. Each file is read fresh every turn (as today), missing files are ignored.
3. `RunManager`: `get_instructions` becomes a function of the project. In `_drive`, call
   `self.get_instructions(chat["project"])`. In `app.py`: `lambda project: config.read_instructions(cfg, project)`.
4. `agents-dialpad project add` keeps writing plain paths (no change). `project list` shows the project's instructions
   file when it has one.
5. `doctor`: one check per project instructions file (ok / warn "file not found").
6. UI: none.

## Tests

- `test_project_objects_are_normalised_to_paths` (cfg["projects"] values are strings).
- `test_project_instructions_follow_the_global_ones`.
- `test_missing_project_instructions_are_ignored`.
- `test_projects_without_a_path_are_reported`.
- Integration: a project with its own instructions → fake claude's `--append-system-prompt` contains global text, a blank line, then the project text; another project gets only the global text.

## Docs

README configuration table (`projects` row) and the "Always-on instructions" section. CHANGELOG. `config.example.json`.

## Acceptance checklist

- [x] Old configs (plain paths) work unchanged.
- [x] Project instructions apply only to chats in that project.

## Not planned (and why)

- **Voice input button:** iPhone and Android keyboards already have dictation that works in the message box. A custom
  button would duplicate it and needs microphone permission handling; revisit only if users ask.
