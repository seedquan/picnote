# PicNote

AI-powered photo intelligence system for macOS.

## Dev Workflow

```bash
npm run build     # Compile TypeScript
npm test          # Run all tests (vitest)
npm start         # Run the CLI
```

## Architecture

- `src/main.ts` — CLI entry point with all commands (init, search, stats, config, export, import, reset, upgrade)
- `src/config.ts` — Config loading from `~/.picnote/config.yaml`, defaults, path expansion
- `src/db.ts` — SQLite database (better-sqlite3) with FTS5 search
- `src/watcher.ts` — Read-only Apple Photos.sqlite reader (NEVER writes)
- `src/classifier.ts` — Image classification (local heuristics + Claude CLI fallback)
- `src/extractor.ts` — OCR via Swift Vision CLI + regex extraction
- `src/analyzer.ts` — Deep analysis via Claude Code CLI
- `src/note_generator.ts` — Markdown note generation with thumbnails (sharp)
- `src/cli.ts` — CLI helpers: colors, spinner, version, prompts

## Conventions

- All subprocess calls use `execFileSync` with argument arrays (never shell strings)
- Status/log messages go to stderr; data output goes to stdout
- Photos.sqlite opened with `{ readonly: true }` — never written to
- Original photos are NEVER deleted or modified
- Config lives in `~/.picnote/config.yaml`
- Data lives in the configurable `output_dir` (default `~/Documents/PicNote/`)

## Testing

Tests use Vitest with temp directories for isolation. Mock Photos.sqlite databases are created per test.
Run: `npm test`
