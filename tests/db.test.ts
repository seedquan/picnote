import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import path from 'path';
import { PicNoteDB } from '../src/db.js';
import { tmpDir, cleanup } from './helpers.js';

let tmp: string;
let db: PicNoteDB;

beforeEach(() => {
  tmp = tmpDir();
  db = new PicNoteDB(path.join(tmp, 'test.db'));
});
afterEach(() => {
  db.close();
  cleanup(tmp);
});

describe('Database Init', () => {
  it('creates database file', () => {
    expect(require('fs').existsSync(path.join(tmp, 'test.db'))).toBe(true);
  });

  it('is idempotent', () => {
    const db2 = new PicNoteDB(path.join(tmp, 'test.db'));
    expect(db2.isProcessed('nonexistent')).toBe(false);
    db2.close();
  });
});

describe('Insert and Query', () => {
  it('inserts and retrieves by UUID', () => {
    db.insertProcessedImage({
      photoUuid: 'UUID-001',
      photoPath: '/p/test.jpg',
      thumbnailPath: null,
      classification: 'informational',
    });
    const result = db.getByUuid('UUID-001');
    expect(result).toBeDefined();
    expect(result!.classification).toBe('informational');
  });

  it('returns undefined for nonexistent UUID', () => {
    expect(db.getByUuid('NOPE')).toBeUndefined();
  });

  it('isProcessed returns true for existing', () => {
    db.insertProcessedImage({ photoUuid: 'UUID-002', photoPath: '/p', thumbnailPath: null, classification: 'casual' });
    expect(db.isProcessed('UUID-002')).toBe(true);
  });

  it('isProcessed returns false for missing', () => {
    expect(db.isProcessed('MISSING')).toBe(false);
  });

  it('rejects duplicate UUIDs', () => {
    db.insertProcessedImage({ photoUuid: 'DUP', photoPath: '/p', thumbnailPath: null, classification: 'casual' });
    expect(() =>
      db.insertProcessedImage({ photoUuid: 'DUP', photoPath: '/p2', thumbnailPath: null, classification: 'casual' }),
    ).toThrow();
  });

  it('stores tags as JSON array', () => {
    db.insertProcessedImage({
      photoUuid: 'TAGS',
      photoPath: '/p',
      thumbnailPath: null,
      classification: 'informational',
      tags: ['tag,with,commas', 'normal'],
    });
    const result = db.getByUuid('TAGS')!;
    expect(JSON.parse(result.tags!)).toEqual(['tag,with,commas', 'normal']);
  });

  it('stores null tags for empty array', () => {
    db.insertProcessedImage({
      photoUuid: 'EMPTY-TAGS',
      photoPath: '/p',
      thumbnailPath: null,
      classification: 'informational',
      tags: [],
    });
    const result = db.getByUuid('EMPTY-TAGS')!;
    expect(result.tags).toBeNull();
  });

  it('stores all fields', () => {
    db.insertProcessedImage({
      photoUuid: 'FULL',
      photoPath: '/p/full.jpg',
      thumbnailPath: '/t/full.jpg',
      classification: 'informational',
      sourceType: 'screenshot',
      ocrText: 'Hello World',
      structuredData: { urls: ['https://example.com'] },
      aiSummary: 'A screenshot',
      tags: ['link'],
      notePath: '/vault/note.md',
      deviceName: 'iPhone 15 Pro',
      latitude: 39.9,
      longitude: 116.4,
      capturedAt: '2026-04-08T14:30:00',
    });
    const r = db.getByUuid('FULL')!;
    expect(r.source_type).toBe('screenshot');
    expect(r.ocr_text).toBe('Hello World');
    expect(JSON.parse(r.structured_data!)).toEqual({ urls: ['https://example.com'] });
    expect(r.device_name).toBe('iPhone 15 Pro');
    expect(r.latitude).toBe(39.9);
  });
});

describe('Search', () => {
  beforeEach(() => {
    db.insertProcessedImage({
      photoUuid: 'S1', photoPath: '/p', thumbnailPath: null, classification: 'informational',
      ocrText: 'Important meeting about machine learning',
    });
    db.insertProcessedImage({
      photoUuid: 'S2', photoPath: '/p', thumbnailPath: null, classification: 'informational',
      aiSummary: 'Receipt from Blue Bottle Coffee',
      tags: ['receipt', 'coffee'],
    });
  });

  it('searches OCR text', () => {
    const results = db.search('machine learning');
    expect(results.length).toBeGreaterThanOrEqual(1);
  });

  it('searches tags', () => {
    const results = db.search('coffee');
    expect(results.length).toBeGreaterThanOrEqual(1);
  });

  it('searches summary', () => {
    const results = db.search('Blue Bottle');
    expect(results.length).toBeGreaterThanOrEqual(1);
  });

  it('returns empty for no match', () => {
    expect(db.search('xyznonexistent')).toEqual([]);
  });

  it('handles special chars in query (email)', () => {
    db.insertProcessedImage({
      photoUuid: 'EMAIL', photoPath: '/p', thumbnailPath: null, classification: 'informational',
      ocrText: 'Contact: user@example.com',
    });
    const results = db.search('user@example.com');
    expect(results.length).toBeGreaterThanOrEqual(1);
  });

  it('respects limit', () => {
    for (let i = 0; i < 10; i++) {
      db.insertProcessedImage({
        photoUuid: `LIM-${i}`, photoPath: '/p', thumbnailPath: null, classification: 'informational',
        ocrText: `common search term ${i}`,
      });
    }
    expect(db.search('common search term', 3).length).toBe(3);
  });
});

describe('Stats', () => {
  it('returns zeros for empty db', () => {
    expect(db.getStats()).toEqual({ total: 0, informational: 0, casual: 0 });
  });

  it('counts correctly', () => {
    db.insertProcessedImage({ photoUuid: 'A', photoPath: '/p', thumbnailPath: null, classification: 'informational' });
    db.insertProcessedImage({ photoUuid: 'B', photoPath: '/p', thumbnailPath: null, classification: 'casual' });
    db.insertProcessedImage({ photoUuid: 'C', photoPath: '/p', thumbnailPath: null, classification: 'informational' });
    expect(db.getStats()).toEqual({ total: 3, informational: 2, casual: 1 });
  });
});
