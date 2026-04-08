import fs from 'fs';
import path from 'path';
import os from 'os';
import Database from 'better-sqlite3';
import { PicNoteDB } from '../src/db.js';
import type { PicNoteConfig } from '../src/config.js';
import type { PhotoAsset } from '../src/watcher.js';
import type { ExtractionResult } from '../src/extractor.js';
import type { AnalysisResult } from '../src/analyzer.js';
import { DEFAULT_CONFIG, ensureOutputDirs } from '../src/config.js';

export function tmpDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'picnote-test-'));
  return dir;
}

export function testConfig(tmpPath: string): PicNoteConfig {
  const config = JSON.parse(JSON.stringify(DEFAULT_CONFIG)) as PicNoteConfig;
  config.output_dir = path.join(tmpPath, 'output');
  config.photos_library = path.join(tmpPath, 'Photos.photoslibrary');
  return config;
}

export function testDb(tmpPath: string): PicNoteDB {
  return new PicNoteDB(path.join(tmpPath, 'test_picnote.db'));
}

export function createTestImage(filePath: string, width = 640, height = 480): void {
  // Create a minimal valid JPEG (smallest valid JPEG is ~107 bytes)
  // Using a simple 1x1 pixel BMP-like approach won't work for sharp,
  // so write a minimal PNG instead
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });

  // Minimal 1x1 red PNG (67 bytes)
  const pngData = Buffer.from(
    '89504e470d0a1a0a0000000d49484452000000010000000108020000009001' +
      '2e00000000c4944415478016360f8cf00000001010000180dd8eb0000000049454e44ae426082',
    'hex',
  );
  fs.writeFileSync(filePath, pngData);
}

export function sampleAsset(tmpPath: string, overrides: Partial<PhotoAsset> = {}): PhotoAsset {
  const imgPath = path.join(tmpPath, 'test_photo.jpg');
  createTestImage(imgPath);

  return {
    uuid: 'TEST-UUID-12345',
    filename: 'test_photo.jpg',
    directory: 'A',
    filePath: imgPath,
    isScreenshot: false,
    sceneLabels: [],
    hasText: false,
    faceCount: 0,
    capturedAt: new Date('2026-04-08T14:30:00Z'),
    width: 640,
    height: 480,
    ...overrides,
  };
}

export function screenshotAsset(tmpPath: string): PhotoAsset {
  const imgPath = path.join(tmpPath, 'screenshot.png');
  createTestImage(imgPath);

  return {
    uuid: 'SCREENSHOT-UUID-001',
    filename: 'screenshot.png',
    directory: 'B',
    filePath: imgPath,
    isScreenshot: true,
    sceneLabels: ['text', 'screen'],
    hasText: true,
    faceCount: 0,
    capturedAt: new Date('2026-04-08T15:00:00Z'),
    width: 390,
    height: 844,
  };
}

export function selfieAsset(tmpPath: string): PhotoAsset {
  const imgPath = path.join(tmpPath, 'selfie.jpg');
  createTestImage(imgPath);

  return {
    uuid: 'SELFIE-UUID-001',
    filename: 'selfie.jpg',
    directory: 'C',
    filePath: imgPath,
    isScreenshot: false,
    sceneLabels: ['selfie', 'portrait'],
    hasText: false,
    faceCount: 2,
    capturedAt: new Date('2026-04-08T12:00:00Z'),
    width: 640,
    height: 480,
  };
}

export function sampleExtraction(): ExtractionResult {
  return {
    ocrText: 'Meeting at 2pm\nhttps://example.com\nCall: 555-0123',
    urls: ['https://example.com'],
    emails: [],
    phones: ['555-0123'],
    dates: ['2pm'],
    amounts: [],
    qrCodes: [],
  };
}

export function sampleAnalysis(): AnalysisResult {
  return {
    title: 'Meeting Notes - Project Sync',
    summary: 'Meeting notes with a link to project resources and a contact number.',
    type: 'note',
    tags: ['meeting', 'work'],
    urls: ['https://example.com'],
    dates: ['2pm'],
    contacts: ['555-0123'],
    action_items: ['Follow up on project sync'],
  };
}

export function createMockPhotosDb(tmpPath: string): string {
  const dbDir = path.join(tmpPath, 'Photos.photoslibrary', 'database');
  fs.mkdirSync(dbDir, { recursive: true });
  const dbPath = path.join(dbDir, 'Photos.sqlite');

  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE ZASSET (
      Z_PK INTEGER PRIMARY KEY,
      ZUUID TEXT,
      ZFILENAME TEXT,
      ZDIRECTORY TEXT,
      ZDATECREATED REAL,
      ZWIDTH INTEGER,
      ZHEIGHT INTEGER,
      ZTRASHEDSTATE INTEGER DEFAULT 0
    );
    CREATE TABLE ZADDITIONALASSETATTRIBUTES (
      Z_PK INTEGER PRIMARY KEY,
      ZASSET INTEGER,
      ZISDETECTEDSCREENSHOT INTEGER DEFAULT 0,
      ZCHARACTERRECOGNITIONATTRIBUTES INTEGER DEFAULT 0
    );
    CREATE TABLE ZDETECTEDFACE (
      Z_PK INTEGER PRIMARY KEY,
      ZASSET INTEGER
    );
  `);
  db.close();

  return path.join(tmpPath, 'Photos.photoslibrary');
}

export function addMockPhoto(
  photosLibrary: string,
  uuid: string,
  filename: string,
  opts: {
    directory?: string;
    timestamp?: number;
    width?: number;
    height?: number;
    isScreenshot?: number;
    hasOcr?: number;
    faceCount?: number;
    trashed?: number;
  } = {},
): string {
  const dbPath = path.join(photosLibrary, 'database', 'Photos.sqlite');
  const db = new Database(dbPath);

  const dir = opts.directory ?? 'A';
  const ts = opts.timestamp ?? 765432100.0;

  const result = db
    .prepare(
      `INSERT INTO ZASSET (ZUUID, ZFILENAME, ZDIRECTORY, ZDATECREATED, ZWIDTH, ZHEIGHT, ZTRASHEDSTATE)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    )
    .run(uuid, filename, dir, ts, opts.width ?? 640, opts.height ?? 480, opts.trashed ?? 0);

  const pk = result.lastInsertRowid;

  db.prepare(
    `INSERT INTO ZADDITIONALASSETATTRIBUTES (ZASSET, ZISDETECTEDSCREENSHOT, ZCHARACTERRECOGNITIONATTRIBUTES)
     VALUES (?, ?, ?)`,
  ).run(pk, opts.isScreenshot ?? 0, opts.hasOcr ?? 0);

  for (let i = 0; i < (opts.faceCount ?? 0); i++) {
    db.prepare('INSERT INTO ZDETECTEDFACE (ZASSET) VALUES (?)').run(pk);
  }

  db.close();

  // Create dummy image file
  const originalsDir = path.join(photosLibrary, 'originals', dir);
  fs.mkdirSync(originalsDir, { recursive: true });
  const imgPath = path.join(originalsDir, filename);
  createTestImage(imgPath);

  return imgPath;
}

export function cleanup(dir: string): void {
  fs.rmSync(dir, { recursive: true, force: true });
}
