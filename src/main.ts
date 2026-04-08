#!/usr/bin/env node

import fs from 'fs';
import os from 'os';
import path from 'path';
import { analyzeImage } from './analyzer.js';
import { classifyImage, Classification } from './classifier.js';
import { loadConfig, ensureOutputDirs } from './config.js';
import { PicNoteDB } from './db.js';
import { extractFromImage, hasData } from './extractor.js';
import { generateNote } from './note_generator.js';
import { APPLE_EPOCH, getNewPhotos } from './watcher.js';
import type { PhotoAsset } from './watcher.js';
import type { PicNoteConfig, OutputPaths } from './config.js';

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
    console.warn(`Original file not found: ${asset.filePath}`);
    db.logProcessing({ photoUuid: uuid, stage: 'check', status: 'skipped', errorMessage: 'File not found' });
    return false;
  }

  // Stage 1: Classification
  const classification = classifyImage(asset, config);
  db.logProcessing({
    photoUuid: uuid,
    stage: 'classification',
    status: classification,
    durationMs: Date.now() - start,
  });

  if (classification === Classification.CASUAL) {
    db.insertProcessedImage({
      photoUuid: uuid,
      photoPath: asset.filePath,
      thumbnailPath: null,
      classification,
      sourceType: asset.isScreenshot ? 'screenshot' : 'photo',
      capturedAt: asset.capturedAt?.toISOString() ?? null,
    });
    console.info(`Skipped casual image: ${uuid} (${asset.filename})`);
    return false;
  }

  // Stage 2: OCR + Extraction
  const extractStart = Date.now();
  const extraction = extractFromImage(asset.filePath);
  db.logProcessing({
    photoUuid: uuid,
    stage: 'extraction',
    status: hasData(extraction) ? 'success' : 'empty',
    durationMs: Date.now() - extractStart,
  });

  // Stage 3: AI Analysis
  const analysisStart = Date.now();
  const analysis = analyzeImage(asset.filePath, extraction, config);
  db.logProcessing({
    photoUuid: uuid,
    stage: 'analysis',
    status: analysis ? 'success' : 'failed',
    durationMs: Date.now() - analysisStart,
  });

  // Stage 4: Note Generation
  const noteStart = Date.now();
  const notePath = await generateNote(asset, extraction, analysis, config, outputPaths);
  db.logProcessing({
    photoUuid: uuid,
    stage: 'note_generation',
    status: 'success',
    durationMs: Date.now() - noteStart,
  });

  db.insertProcessedImage({
    photoUuid: uuid,
    photoPath: asset.filePath,
    thumbnailPath: null,
    classification,
    sourceType: asset.isScreenshot ? 'screenshot' : 'photo',
    ocrText: extraction.ocrText,
    structuredData: {
      urls: extraction.urls,
      qr_codes: extraction.qrCodes,
      emails: extraction.emails,
      phones: extraction.phones,
      dates: extraction.dates,
      amounts: extraction.amounts,
    },
    aiSummary: analysis?.summary ?? null,
    tags: analysis?.tags ?? null,
    notePath,
    capturedAt: asset.capturedAt?.toISOString() ?? null,
  });

  const totalMs = Date.now() - start;
  console.info(`Processed ${uuid} (${asset.filename}) → ${notePath} [${totalMs}ms]`);
  return true;
}

async function runPipeline(config: PicNoteConfig): Promise<void> {
  const outputPaths = ensureOutputDirs(config);

  console.info('PicNote pipeline starting');

  const db = new PicNoteDB(path.join(outputPaths.data_dir, 'picnote.db'));
  const photosLibrary = config.photos_library;

  if (!fs.existsSync(photosLibrary)) {
    console.error(`Photos library not found: ${photosLibrary}`);
    return;
  }

  // Load last processed timestamp
  const stateFile = path.join(outputPaths.data_dir, 'last_timestamp.txt');
  let sinceTimestamp: number | null = null;
  if (fs.existsSync(stateFile)) {
    const raw = fs.readFileSync(stateFile, 'utf-8').trim();
    sinceTimestamp = parseFloat(raw) || null;
  }

  const maxBatch = config.processing.max_batch_size;
  let assets: PhotoAsset[];
  try {
    assets = getNewPhotos(photosLibrary, sinceTimestamp, maxBatch);
  } catch (err: any) {
    console.error(`Failed to query Photos database: ${err.message}`);
    return;
  }

  if (!assets.length) {
    console.info('No new photos to process');
    return;
  }

  console.info(`Found ${assets.length} new photos to process`);

  let notesCreated = 0;
  let latestTimestamp = sinceTimestamp;

  for (const asset of assets) {
    try {
      const created = await processSingleImage(asset, db, config, outputPaths);
      if (created) notesCreated++;

      if (asset.capturedAt) {
        const ts = (asset.capturedAt.getTime() - APPLE_EPOCH.getTime()) / 1000;
        if (latestTimestamp == null || ts > latestTimestamp) {
          latestTimestamp = ts;
        }
      }
    } catch (err: any) {
      console.error(`Error processing ${asset.uuid}: ${err.message}`);
      db.logProcessing({ photoUuid: asset.uuid, stage: 'pipeline', status: 'error', errorMessage: err.message });
    }
  }

  // Atomic state file write
  if (latestTimestamp != null) {
    const tmpPath = stateFile + '.tmp';
    fs.writeFileSync(tmpPath, String(latestTimestamp));
    fs.renameSync(tmpPath, stateFile);
  }

  const stats = db.getStats();
  console.info(
    `Pipeline complete: ${notesCreated} notes created from ${assets.length} photos. ` +
      `Total: ${stats.total} processed (${stats.informational} informational, ${stats.casual} casual)`,
  );

  db.close();
}

function searchNotes(config: PicNoteConfig, query: string): void {
  const outputPaths = ensureOutputDirs(config);
  const db = new PicNoteDB(path.join(outputPaths.data_dir, 'picnote.db'));

  const results = db.search(query);
  if (!results.length) {
    console.log(`No results for: ${query}`);
    db.close();
    return;
  }

  console.log(`Found ${results.length} results for: ${query}\n`);
  for (const r of results) {
    console.log(`  [${r.classification}] ${r.ai_summary || r.ocr_text?.slice(0, 80)}`);
    if (r.note_path) console.log(`  Note: ${r.note_path}`);
    console.log(`  Captured: ${r.captured_at}\n`);
  }
  db.close();
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);

  let configPath: string | undefined;
  const configIdx = args.indexOf('--config');
  if (configIdx !== -1 && args[configIdx + 1]) {
    configPath = args[configIdx + 1];
  }

  const config = loadConfig(configPath);

  const searchIdx = args.indexOf('--search');
  if (searchIdx !== -1 && args[searchIdx + 1]) {
    searchNotes(config, args[searchIdx + 1]);
    return;
  }

  if (args.includes('--stats')) {
    const outputPaths = ensureOutputDirs(config);
    const db = new PicNoteDB(path.join(outputPaths.data_dir, 'picnote.db'));
    const stats = db.getStats();
    console.log(`Total processed: ${stats.total}`);
    console.log(`  Informational: ${stats.informational}`);
    console.log(`  Casual: ${stats.casual}`);
    db.close();
    return;
  }

  if (args.includes('--help') || args.includes('-h')) {
    console.log('Usage: picnote [options]');
    console.log('  --config <path>   Path to config.yaml');
    console.log('  --search <query>  Search processed notes');
    console.log('  --stats           Show processing statistics');
    console.log('  --help            Show this help message');
    return;
  }

  await runPipeline(config);
}

main().catch(console.error);
