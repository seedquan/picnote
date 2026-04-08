# PicNote

AI-powered photo intelligence system. Monitors your iPhone photos (via iCloud sync), classifies informational vs casual images, extracts text/URLs/QR codes, and generates searchable Markdown notes automatically.

**Zero friction capture** — just take a screenshot or photo. PicNote does the rest.

## How it works

```
iPhone → iCloud sync → Mac Photos Library → PicNote → Markdown notes
```

1. You take a photo or screenshot on your iPhone
2. iCloud syncs it to your Mac's Photos library
3. PicNote detects the new image via `launchd` (watches Photos.sqlite)
4. Classifies: informational (receipt, QR code, whiteboard, event flyer) or casual (selfie, scenery)
5. For informational images: extracts text (OCR), URLs, QR codes, contacts, amounts
6. Generates a structured Markdown note with AI analysis via Claude Code CLI
7. Saves to a configurable output directory (default: `~/Documents/PicNote/vault/`)

## Setup

### Prerequisites

- macOS with iCloud Photos enabled
- Node.js 18+
- [Claude Code CLI](https://claude.ai/code) installed
- Xcode Command Line Tools (for Swift compiler)

### Install

```bash
npm install -g picnote

# Or install from source
cd ~/Projects/picnote
npm install
npm run build

# Compile the Swift Vision OCR helper
swiftc -o swift/vision_ocr swift/vision_ocr.swift -framework AppKit -framework Vision
```

### Configure

Edit `config.yaml`:

```yaml
output_dir: ~/Documents/PicNote    # Where notes are saved
photos_library: ~/Pictures/Photos Library.photoslibrary
```

### Run manually

```bash
# Process new photos
picnote

# Search notes
picnote --search "restaurant"

# View stats
picnote --stats
```

### Auto-run on photo sync

```bash
# Install the launchd watcher (update ProgramArguments to use node + dist/main.js)
cp resources/com.picnote.watcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.picnote.watcher.plist
```

This watches your Photos.sqlite for changes and runs PicNote automatically within 30 seconds of a new photo syncing.

## Architecture

| Component | Purpose |
|-----------|---------|
| `src/watcher.py` | Reads Photos.sqlite (strictly read-only via `?mode=ro`) |
| `src/classifier.py` | Informational vs casual classification (local heuristics + Claude CLI fallback) |
| `src/extractor.py` | OCR via Apple Vision framework + regex extraction (URLs, phones, emails, amounts) |
| `src/analyzer.py` | Deep analysis via Claude Code CLI — titles, summaries, tags |
| `src/note_generator.py` | Generates Markdown notes with source traceability |
| `src/db.py` | SQLite database with FTS5 full-text search index |
| `swift/vision_ocr` | Compiled Swift binary for Apple Vision OCR + QR code detection |

## Safety

- **Photos are NEVER deleted or modified** — strictly read-only access to your Photos library
- Photos.sqlite is opened with SQLite `?mode=ro` (enforced at the VFS level)
- Path traversal protection on all file paths from the Photos database
- Sensitive content detection (passwords, SSN, bank info) skips cloud processing
- All Claude CLI calls use your existing Claude Code tokens — no separate API key needed

## Tests

```bash
npm test
```

105 tests covering all modules, including safety tests that verify read-only guarantees.

## License

Personal project.
