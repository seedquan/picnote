#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import { execFileSync } from 'child_process';
import { analyzeImage } from './analyzer.js';
import { classifyImage, Classification } from './classifier.js';
import {
  loadConfig, ensureOutputDirs, saveConfig, getHomeDir, getConfigPath,
  isInitialized, expandHome, DEFAULT_CONFIG,
} from './config.js';
import type { PicNoteConfig, OutputPaths } from './config.js';
import { PicNoteDB } from './db.js';
import { extractFromImage, hasData } from './extractor.js';
import { generateNote } from './note_generator.js';
import { APPLE_EPOCH, getNewPhotos } from './watcher.js';
import type { PhotoAsset } from './watcher.js';
import { color, log, Spinner, getVersion, getPackageName, prompt } from './cli.js';

// ─── Command: run (default) ───

async function processSingleImage(
  asset: PhotoAsset,
  db: PicNoteDB,
  config: PicNoteConfig,
  outputPaths: OutputPaths,
): Promise<boolean> {
  const start = Date.now();
  const uuid = asset.uuid;

  if (db.isProcessed(uuid)) return false;

  if (!fs.existsSync(asset.filePath)) {
    log.warn(`Original file not found: ${asset.filePath}`);
    db.logProcessing({ photoUuid: uuid, stage: 'check', status: 'skipped', errorMessage: 'File not found' });
    return false;
  }

  const classification = classifyImage(asset, config);
  db.logProcessing({ photoUuid: uuid, stage: 'classification', status: classification, durationMs: Date.now() - start });

  if (classification === Classification.CASUAL) {
    db.insertProcessedImage({
      photoUuid: uuid, photoPath: asset.filePath, thumbnailPath: null, classification,
      sourceType: asset.isScreenshot ? 'screenshot' : 'photo',
      capturedAt: asset.capturedAt?.toISOString() ?? null,
    });
    return false;
  }

  const extraction = extractFromImage(asset.filePath);
  db.logProcessing({ photoUuid: uuid, stage: 'extraction', status: hasData(extraction) ? 'success' : 'empty', durationMs: Date.now() - start });

  const analysis = analyzeImage(asset.filePath, extraction, config);
  db.logProcessing({ photoUuid: uuid, stage: 'analysis', status: analysis ? 'success' : 'failed', durationMs: Date.now() - start });

  const notePath = await generateNote(asset, extraction, analysis, config, outputPaths);
  db.logProcessing({ photoUuid: uuid, stage: 'note_generation', status: 'success', durationMs: Date.now() - start });

  db.insertProcessedImage({
    photoUuid: uuid, photoPath: asset.filePath, thumbnailPath: null, classification,
    sourceType: asset.isScreenshot ? 'screenshot' : 'photo',
    ocrText: extraction.ocrText,
    structuredData: { urls: extraction.urls, qr_codes: extraction.qrCodes, emails: extraction.emails, phones: extraction.phones, dates: extraction.dates, amounts: extraction.amounts },
    aiSummary: analysis?.summary ?? null, tags: analysis?.tags ?? null, notePath,
    capturedAt: asset.capturedAt?.toISOString() ?? null,
  });

  log.success(`${asset.filename} → ${path.basename(notePath)} [${Date.now() - start}ms]`);
  return true;
}

async function cmdRun(config: PicNoteConfig, jsonOutput: boolean): Promise<void> {
  const outputPaths = ensureOutputDirs(config);
  const db = new PicNoteDB(path.join(outputPaths.data_dir, 'picnote.db'));

  if (!fs.existsSync(config.photos_library)) {
    log.error(`Photos library not found: ${config.photos_library}`);
    log.info('Run "picnote init" to configure your Photos library path.');
    db.close();
    return;
  }

  const stateFile = path.join(outputPaths.data_dir, 'last_timestamp.txt');
  let sinceTimestamp: number | null = null;
  if (fs.existsSync(stateFile)) {
    sinceTimestamp = parseFloat(fs.readFileSync(stateFile, 'utf-8').trim()) || null;
  }

  let assets: PhotoAsset[];
  try {
    assets = getNewPhotos(config.photos_library, sinceTimestamp, config.processing.max_batch_size);
  } catch (err: any) {
    log.error(`Failed to query Photos database: ${err.message}`);
    db.close();
    return;
  }

  if (!assets.length) {
    log.info('No new photos to process.');
    db.close();
    return;
  }

  const spinner = new Spinner(`Processing ${assets.length} photos`).start();
  let notesCreated = 0;
  let latestTimestamp = sinceTimestamp;

  for (const asset of assets) {
    try {
      if (await processSingleImage(asset, db, config, outputPaths)) notesCreated++;
      if (asset.capturedAt) {
        const ts = (asset.capturedAt.getTime() - APPLE_EPOCH.getTime()) / 1000;
        if (latestTimestamp == null || ts > latestTimestamp) latestTimestamp = ts;
      }
    } catch (err: any) {
      log.error(`${asset.uuid}: ${err.message}`);
      db.logProcessing({ photoUuid: asset.uuid, stage: 'pipeline', status: 'error', errorMessage: err.message });
    }
  }

  spinner.stop();

  if (latestTimestamp != null) {
    const tmpPath = stateFile + '.tmp';
    fs.writeFileSync(tmpPath, String(latestTimestamp));
    fs.renameSync(tmpPath, stateFile);
  }

  const stats = db.getStats();
  db.close();

  if (jsonOutput) {
    process.stdout.write(JSON.stringify({ notes_created: notesCreated, processed: assets.length, ...stats }) + '\n');
  } else {
    log.success(`${notesCreated} notes created from ${assets.length} photos. Total: ${stats.total} (${stats.informational} info, ${stats.casual} casual)`);
  }
}

// ─── Command: search ───

function cmdSearch(config: PicNoteConfig, query: string, jsonOutput: boolean): void {
  const outputPaths = ensureOutputDirs(config);
  const db = new PicNoteDB(path.join(outputPaths.data_dir, 'picnote.db'));
  const results = db.search(query);
  db.close();

  if (jsonOutput) {
    process.stdout.write(JSON.stringify(results, null, 2) + '\n');
    return;
  }

  if (!results.length) {
    log.info(`No results for: ${query}`);
    return;
  }

  log.info(`Found ${color.bold(String(results.length))} results for "${query}":\n`);
  for (const r of results) {
    const badge = r.classification === 'informational' ? color.green('INFO') : color.dim('CASUAL');
    process.stderr.write(`  ${badge} ${r.ai_summary || r.ocr_text?.slice(0, 80) || '(no text)'}\n`);
    if (r.note_path) process.stderr.write(`       ${color.dim(r.note_path)}\n`);
  }
}

// ─── Command: stats ───

function cmdStats(config: PicNoteConfig, jsonOutput: boolean): void {
  const outputPaths = ensureOutputDirs(config);
  const db = new PicNoteDB(path.join(outputPaths.data_dir, 'picnote.db'));
  const stats = db.getStats();
  db.close();

  if (jsonOutput) {
    process.stdout.write(JSON.stringify(stats) + '\n');
    return;
  }

  process.stderr.write(`${color.bold('PicNote Stats')}\n`);
  process.stderr.write(`  Total processed: ${color.bold(String(stats.total))}\n`);
  process.stderr.write(`  Informational:   ${color.green(String(stats.informational))}\n`);
  process.stderr.write(`  Casual:          ${color.dim(String(stats.casual))}\n`);
}

// ─── Command: init ───

async function cmdInit(): Promise<void> {
  const homeDir = getHomeDir();
  const configPath = getConfigPath();

  process.stderr.write(`\n${color.bold('PicNote Setup')}\n\n`);

  if (isInitialized()) {
    const overwrite = await prompt(`  Config already exists at ${color.dim(configPath)}. Overwrite? [y/N] `);
    if (overwrite.toLowerCase() !== 'y') {
      log.info('Keeping existing config.');
      return;
    }
  }

  // Photos library
  const defaultLib = expandHome(DEFAULT_CONFIG.photos_library);
  const libExists = fs.existsSync(defaultLib);
  const libPrompt = libExists
    ? `  Photos library [${color.dim(defaultLib)}]: `
    : `  Photos library path: `;
  const libInput = await prompt(libPrompt);
  const photosLibrary = libInput || (libExists ? DEFAULT_CONFIG.photos_library : '');
  if (!photosLibrary) {
    log.error('Photos library path is required.');
    return;
  }

  // Output directory
  const defaultOut = DEFAULT_CONFIG.output_dir;
  const outInput = await prompt(`  Output directory [${color.dim(defaultOut)}]: `);
  const outputDir = outInput || defaultOut;

  // Build config
  const config: PicNoteConfig = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
  config.photos_library = photosLibrary;
  config.output_dir = outputDir;

  // Save
  fs.mkdirSync(homeDir, { recursive: true });
  saveConfig(config, configPath);
  ensureOutputDirs({ ...config, output_dir: expandHome(config.output_dir), photos_library: expandHome(config.photos_library) });

  // Check dependencies
  process.stderr.write('\n');
  checkDependency('claude', 'Claude Code CLI');
  checkDependency('node', 'Node.js');

  const swiftBin = path.join(path.dirname(path.dirname(import.meta.url.replace('file://', ''))), 'swift', 'vision_ocr');
  if (fs.existsSync(swiftBin)) {
    log.success('Swift Vision OCR helper found.');
  } else {
    log.warn('Swift Vision OCR helper not compiled. Run:');
    process.stderr.write(color.dim('  swiftc -o swift/vision_ocr swift/vision_ocr.swift -framework AppKit -framework Vision\n'));
  }

  process.stderr.write('\n');
  log.success(`Config saved to ${color.dim(configPath)}`);
  log.info(`Run ${color.bold('picnote')} to process new photos.`);
}

function checkDependency(cmd: string, label: string): void {
  try {
    execFileSync('which', [cmd], { encoding: 'utf-8', stdio: 'pipe' });
    log.success(`${label} found.`);
  } catch {
    log.warn(`${label} (${cmd}) not found in PATH.`);
  }
}

// ─── Command: config ───

function cmdConfig(config: PicNoteConfig, jsonOutput: boolean): void {
  if (jsonOutput) {
    process.stdout.write(JSON.stringify(config, null, 2) + '\n');
    return;
  }

  process.stderr.write(`${color.bold('PicNote Configuration')}\n`);
  process.stderr.write(`  Config file: ${color.dim(getConfigPath())}\n`);
  process.stderr.write(`  Home dir:    ${color.dim(getHomeDir())}\n\n`);
  process.stderr.write(`  Output:      ${config.output_dir}\n`);
  process.stderr.write(`  Photos lib:  ${config.photos_library}\n`);
  process.stderr.write(`  Batch size:  ${config.processing.max_batch_size}\n`);
  process.stderr.write(`  Screenshots: ${config.classification.auto_process_screenshots ? color.green('auto-process') : color.dim('skip')}\n`);
  process.stderr.write(`  Claude:      ${config.classification.claude_fallback ? color.green('enabled') : color.dim('disabled')}\n`);

  process.stderr.write(`\n${color.bold('Dependencies')}\n`);
  checkDependency('claude', 'Claude Code CLI');
  const libExists = fs.existsSync(config.photos_library);
  if (libExists) log.success('Photos library found.');
  else log.warn(`Photos library not found: ${config.photos_library}`);
}

// ─── Command: upgrade ───

function cmdUpgrade(): void {
  const currentVersion = getVersion();
  const pkgName = getPackageName();
  log.info(`Current version: ${color.bold(currentVersion)}`);

  let latest: string;
  try {
    latest = execFileSync('npm', ['view', pkgName, 'version'], { encoding: 'utf-8', timeout: 10000 }).trim();
  } catch {
    log.error('Failed to check for updates. Are you online?');
    return;
  }

  if (latest === currentVersion) {
    log.success('Already up to date.');
    return;
  }

  log.info(`Latest version: ${color.bold(latest)}`);
  const spinner = new Spinner('Installing update').start();
  try {
    execFileSync('npm', ['install', '-g', `${pkgName}@latest`], { encoding: 'utf-8', timeout: 60000, stdio: 'pipe' });
    spinner.stop(color.green('✓') + ` Updated to ${latest}`);
  } catch (err: any) {
    spinner.stop();
    log.error(`Update failed: ${err.message}`);
  }
}

// ─── Command: reset ───

async function cmdReset(config: PicNoteConfig, force: boolean): Promise<void> {
  const homeDir = getHomeDir();
  const outputPaths = ensureOutputDirs(config);

  if (!force) {
    log.warn('This will delete ALL PicNote data (database, notes, config).');
    log.warn(`Directories: ${homeDir}, ${config.output_dir}`);
    const answer = await prompt('  Type "yes" to confirm: ');
    if (answer !== 'yes') {
      log.info('Reset cancelled.');
      return;
    }
  }

  for (const dir of [homeDir, config.output_dir]) {
    if (fs.existsSync(dir)) {
      fs.rmSync(dir, { recursive: true, force: true });
      log.success(`Deleted ${dir}`);
    }
  }
  log.success('Reset complete. Run "picnote init" to set up again.');
}

// ─── Command: export ───

function cmdExport(config: PicNoteConfig): void {
  const outputPaths = ensureOutputDirs(config);
  const db = new PicNoteDB(path.join(outputPaths.data_dir, 'picnote.db'));
  const stats = db.getStats();
  const all = db.getSince('1970-01-01T00:00:00');
  db.close();

  const backup = {
    version: getVersion(),
    exported_at: new Date().toISOString(),
    stats,
    images: all,
  };

  process.stdout.write(JSON.stringify(backup, null, 2) + '\n');
}

// ─── Command: import ───

async function cmdImport(config: PicNoteConfig, filePath: string): Promise<void> {
  if (!fs.existsSync(filePath)) {
    log.error(`File not found: ${filePath}`);
    return;
  }

  let backup: any;
  try {
    backup = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
  } catch {
    log.error('Invalid JSON file.');
    return;
  }

  if (!backup.images || !Array.isArray(backup.images)) {
    log.error('Invalid backup format (missing "images" array).');
    return;
  }

  const outputPaths = ensureOutputDirs(config);
  const db = new PicNoteDB(path.join(outputPaths.data_dir, 'picnote.db'));

  let imported = 0;
  let skipped = 0;
  for (const img of backup.images) {
    if (db.isProcessed(img.photo_uuid)) {
      skipped++;
      continue;
    }
    try {
      db.insertProcessedImage({
        photoUuid: img.photo_uuid,
        photoPath: img.photo_path,
        thumbnailPath: img.thumbnail_path,
        classification: img.classification,
        sourceType: img.source_type,
        ocrText: img.ocr_text,
        structuredData: img.structured_data ? JSON.parse(img.structured_data) : null,
        aiSummary: img.ai_summary,
        tags: img.tags ? JSON.parse(img.tags) : null,
        notePath: img.note_path,
        deviceName: img.device_name,
        latitude: img.latitude,
        longitude: img.longitude,
        capturedAt: img.captured_at,
      });
      imported++;
    } catch {
      skipped++;
    }
  }
  db.close();

  log.success(`Imported ${imported} records (${skipped} skipped).`);
}

// ─── Help ───

function showHelp(): void {
  const v = getVersion();
  process.stderr.write(`
${color.bold('picnote')} ${color.dim(`v${v}`)} — AI-powered photo intelligence

${color.bold('Usage:')}
  picnote [command] [options]

${color.bold('Commands:')}
  ${color.cyan('(default)')}     Process new photos from iCloud library
  ${color.cyan('init')}          Interactive first-time setup
  ${color.cyan('search')} <q>    Search processed notes
  ${color.cyan('stats')}         Show processing statistics
  ${color.cyan('config')}        View current configuration
  ${color.cyan('export')}        Export all data as JSON (to stdout)
  ${color.cyan('import')} <f>    Import data from JSON backup file
  ${color.cyan('reset')}         Delete all data and start fresh
  ${color.cyan('upgrade')}       Update to the latest version

${color.bold('Options:')}
  --config <path>   Custom config file path
  --json            Machine-readable JSON output
  -y                Skip confirmation prompts
  -v, --version     Show version number
  -h, --help        Show this help message

${color.bold('Examples:')}
  picnote                          Process new photos
  picnote search "restaurant"      Find notes mentioning restaurants
  picnote stats --json             Get stats as JSON
  picnote export > backup.json     Backup all data
  picnote import backup.json       Restore from backup
`);
}

// ─── Main ───

async function main(): Promise<void> {
  const args = process.argv.slice(2);

  // Flags
  const jsonOutput = args.includes('--json');
  const forceYes = args.includes('-y');

  if (args.includes('-v') || args.includes('--version')) {
    process.stdout.write(getVersion() + '\n');
    return;
  }

  if (args.includes('-h') || args.includes('--help')) {
    showHelp();
    return;
  }

  // Config path
  let configPath: string | undefined;
  const configIdx = args.indexOf('--config');
  if (configIdx !== -1 && args[configIdx + 1]) {
    configPath = args[configIdx + 1];
  }

  // Get command (first non-flag argument)
  const command = args.find((a) => !a.startsWith('-') && a !== args[configIdx + 1]);

  try {
    switch (command) {
      case 'init':
        await cmdInit();
        break;

      case 'upgrade':
        cmdUpgrade();
        break;

      case 'reset':
        await cmdReset(loadConfig(configPath), forceYes);
        break;

      case 'search': {
        const query = args[args.indexOf('search') + 1];
        if (!query || query.startsWith('-')) {
          log.error('Usage: picnote search <query>');
          process.exitCode = 1;
          return;
        }
        cmdSearch(loadConfig(configPath), query, jsonOutput);
        break;
      }

      case 'stats':
        cmdStats(loadConfig(configPath), jsonOutput);
        break;

      case 'config':
        cmdConfig(loadConfig(configPath), jsonOutput);
        break;

      case 'export':
        cmdExport(loadConfig(configPath));
        break;

      case 'import': {
        const filePath = args[args.indexOf('import') + 1];
        if (!filePath || filePath.startsWith('-')) {
          log.error('Usage: picnote import <file.json>');
          process.exitCode = 1;
          return;
        }
        await cmdImport(loadConfig(configPath), filePath);
        break;
      }

      default:
        // Default: run pipeline
        await cmdRun(loadConfig(configPath), jsonOutput);
        break;
    }
  } catch (err: any) {
    log.error(err.message);
    process.exitCode = 1;
  }
}

main();
