import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';

const SCHEMA_VERSION = 1;

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS processed_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_uuid TEXT UNIQUE NOT NULL,
    photo_path TEXT,
    thumbnail_path TEXT,
    classification TEXT NOT NULL,
    source_type TEXT,
    ocr_text TEXT,
    structured_data TEXT,
    ai_summary TEXT,
    tags TEXT,
    note_path TEXT,
    device_name TEXT,
    latitude REAL,
    longitude REAL,
    captured_at TEXT,
    processed_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS processed_images_fts USING fts5(
    ocr_text,
    ai_summary,
    tags,
    content=processed_images,
    content_rowid=id
);

CREATE TABLE IF NOT EXISTS processing_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_uuid TEXT,
    stage TEXT,
    status TEXT,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
`;

const TRIGGERS_SQL = `
CREATE TRIGGER IF NOT EXISTS processed_images_ai AFTER INSERT ON processed_images BEGIN
    INSERT INTO processed_images_fts(rowid, ocr_text, ai_summary, tags)
    VALUES (new.id, new.ocr_text, new.ai_summary, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS processed_images_ad AFTER DELETE ON processed_images BEGIN
    INSERT INTO processed_images_fts(processed_images_fts, rowid, ocr_text, ai_summary, tags)
    VALUES('delete', old.id, old.ocr_text, old.ai_summary, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS processed_images_au AFTER UPDATE ON processed_images BEGIN
    INSERT INTO processed_images_fts(processed_images_fts, rowid, ocr_text, ai_summary, tags)
    VALUES('delete', old.id, old.ocr_text, old.ai_summary, old.tags);
    INSERT INTO processed_images_fts(rowid, ocr_text, ai_summary, tags)
    VALUES (new.id, new.ocr_text, new.ai_summary, new.tags);
END;
`;

export interface ProcessedImage {
  id: number;
  photo_uuid: string;
  photo_path: string | null;
  thumbnail_path: string | null;
  classification: string;
  source_type: string | null;
  ocr_text: string | null;
  structured_data: string | null;
  ai_summary: string | null;
  tags: string | null;
  note_path: string | null;
  device_name: string | null;
  latitude: number | null;
  longitude: number | null;
  captured_at: string | null;
  processed_at: string;
  created_at: string;
}

export class PicNoteDB {
  private db: Database.Database;

  constructor(dbPath: string) {
    fs.mkdirSync(path.dirname(dbPath), { recursive: true });
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this._initDb();
  }

  private _initDb(): void {
    const hasSchema = this.db
      .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
      .get();

    if (!hasSchema) {
      this.db.exec(SCHEMA_SQL);
      this.db.exec(TRIGGERS_SQL);
      this.db
        .prepare('INSERT OR REPLACE INTO schema_version (version) VALUES (?)')
        .run(SCHEMA_VERSION);
    }
  }

  isProcessed(photoUuid: string): boolean {
    const row = this.db
      .prepare('SELECT 1 FROM processed_images WHERE photo_uuid = ?')
      .get(photoUuid);
    return !!row;
  }

  insertProcessedImage(params: {
    photoUuid: string;
    photoPath: string;
    thumbnailPath: string | null;
    classification: string;
    sourceType?: string | null;
    ocrText?: string | null;
    structuredData?: Record<string, any> | null;
    aiSummary?: string | null;
    tags?: string[] | null;
    notePath?: string | null;
    deviceName?: string | null;
    latitude?: number | null;
    longitude?: number | null;
    capturedAt?: string | null;
  }): number {
    const stmt = this.db.prepare(`
      INSERT INTO processed_images
      (photo_uuid, photo_path, thumbnail_path, classification, source_type,
       ocr_text, structured_data, ai_summary, tags, note_path,
       device_name, latitude, longitude, captured_at, processed_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    const result = stmt.run(
      params.photoUuid,
      params.photoPath,
      params.thumbnailPath,
      params.classification,
      params.sourceType ?? null,
      params.ocrText ?? null,
      params.structuredData ? JSON.stringify(params.structuredData) : null,
      params.aiSummary ?? null,
      params.tags?.length ? JSON.stringify(params.tags) : null,
      params.notePath ?? null,
      params.deviceName ?? null,
      params.latitude ?? null,
      params.longitude ?? null,
      params.capturedAt ?? null,
      new Date().toISOString(),
    );

    return Number(result.lastInsertRowid);
  }

  getByUuid(photoUuid: string): ProcessedImage | undefined {
    return this.db
      .prepare('SELECT * FROM processed_images WHERE photo_uuid = ?')
      .get(photoUuid) as ProcessedImage | undefined;
  }

  getSince(since: string): ProcessedImage[] {
    return this.db
      .prepare('SELECT * FROM processed_images WHERE processed_at > ? ORDER BY processed_at')
      .all(since) as ProcessedImage[];
  }

  search(query: string, limit = 20): (ProcessedImage & { rank: number })[] {
    const safeQuery = '"' + query.replace(/"/g, '""') + '"';
    return this.db
      .prepare(`
        SELECT p.*, rank
        FROM processed_images_fts fts
        JOIN processed_images p ON p.id = fts.rowid
        WHERE processed_images_fts MATCH ?
        ORDER BY rank
        LIMIT ?
      `)
      .all(safeQuery, limit) as (ProcessedImage & { rank: number })[];
  }

  logProcessing(params: {
    photoUuid: string;
    stage: string;
    status: string;
    errorMessage?: string | null;
    durationMs?: number | null;
  }): void {
    this.db
      .prepare(`
        INSERT INTO processing_log (photo_uuid, stage, status, error_message, duration_ms)
        VALUES (?, ?, ?, ?, ?)
      `)
      .run(
        params.photoUuid,
        params.stage,
        params.status,
        params.errorMessage ?? null,
        params.durationMs ?? null,
      );
  }

  getStats(): { total: number; informational: number; casual: number } {
    const total = (this.db.prepare('SELECT COUNT(*) as c FROM processed_images').get() as any).c;
    const informational = (
      this.db
        .prepare("SELECT COUNT(*) as c FROM processed_images WHERE classification = 'informational'")
        .get() as any
    ).c;
    const casual = (
      this.db
        .prepare("SELECT COUNT(*) as c FROM processed_images WHERE classification = 'casual'")
        .get() as any
    ).c;
    return { total, informational, casual };
  }

  close(): void {
    this.db.close();
  }
}
