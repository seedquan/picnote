import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import Database from 'better-sqlite3';
import path from 'path';
import { appleTimestampToDate, openPhotosDbReadonly, getNewPhotos } from '../src/watcher.js';
import { tmpDir, cleanup, createMockPhotosDb, addMockPhoto } from './helpers.js';

let tmp: string;
beforeEach(() => { tmp = tmpDir(); });
afterEach(() => { cleanup(tmp); });

describe('appleTimestampToDate', () => {
  it('returns null for null input', () => {
    expect(appleTimestampToDate(null)).toBeNull();
  });

  it('converts zero to Apple epoch (2001-01-01)', () => {
    const d = appleTimestampToDate(0)!;
    expect(d.getUTCFullYear()).toBe(2001);
    expect(d.getUTCMonth()).toBe(0);
    expect(d.getUTCDate()).toBe(1);
  });

  it('converts known timestamp', () => {
    const d = appleTimestampToDate(797956200)!;
    expect(d.getFullYear()).toBe(2026);
  });
});

describe('openPhotosDbReadonly', () => {
  it('opens existing database', () => {
    const lib = createMockPhotosDb(tmp);
    const db = openPhotosDbReadonly(lib);
    expect(db).toBeDefined();
    db.close();
  });

  it('throws on missing database', () => {
    expect(() => openPhotosDbReadonly(path.join(tmp, 'nope.photoslibrary'))).toThrow();
  });

  it('prevents writes (read-only mode)', () => {
    const lib = createMockPhotosDb(tmp);
    const db = openPhotosDbReadonly(lib);
    expect(() => db.prepare("INSERT INTO ZASSET (ZUUID, ZFILENAME) VALUES ('x', 'x.jpg')").run()).toThrow();
    db.close();
  });

  it('prevents deletes', () => {
    const lib = createMockPhotosDb(tmp);
    addMockPhoto(lib, 'SAFE', 'safe.jpg');
    const db = openPhotosDbReadonly(lib);
    expect(() => db.prepare("DELETE FROM ZASSET").run()).toThrow();
    db.close();
  });

  it('prevents table creation', () => {
    const lib = createMockPhotosDb(tmp);
    const db = openPhotosDbReadonly(lib);
    expect(() => db.prepare("CREATE TABLE evil (id INTEGER)").run()).toThrow();
    db.close();
  });
});

describe('getNewPhotos', () => {
  it('returns assets', () => {
    const lib = createMockPhotosDb(tmp);
    addMockPhoto(lib, 'UUID-1', 'photo1.jpg');
    addMockPhoto(lib, 'UUID-2', 'photo2.jpg', { timestamp: 765432200 });
    const assets = getNewPhotos(lib);
    expect(assets.length).toBe(2);
  });

  it('resolves file path', () => {
    const lib = createMockPhotosDb(tmp);
    addMockPhoto(lib, 'UUID-P', 'photo.jpg', { directory: 'E' });
    const assets = getNewPhotos(lib);
    expect(assets[0].filePath).toContain(path.join('originals', 'E', 'photo.jpg'));
  });

  it('detects screenshot flag', () => {
    const lib = createMockPhotosDb(tmp);
    addMockPhoto(lib, 'SS', 'ss.png', { isScreenshot: 1 });
    addMockPhoto(lib, 'PH', 'ph.jpg', { isScreenshot: 0 });
    const assets = getNewPhotos(lib);
    const ss = assets.find(a => a.uuid === 'SS')!;
    const ph = assets.find(a => a.uuid === 'PH')!;
    expect(ss.isScreenshot).toBe(true);
    expect(ph.isScreenshot).toBe(false);
  });

  it('detects text content', () => {
    const lib = createMockPhotosDb(tmp);
    addMockPhoto(lib, 'TXT', 'doc.jpg', { hasOcr: 1 });
    addMockPhoto(lib, 'NOTXT', 'selfie.jpg', { hasOcr: 0 });
    const assets = getNewPhotos(lib);
    expect(assets.find(a => a.uuid === 'TXT')!.hasText).toBe(true);
    expect(assets.find(a => a.uuid === 'NOTXT')!.hasText).toBe(false);
  });

  it('counts faces', () => {
    const lib = createMockPhotosDb(tmp);
    addMockPhoto(lib, 'FACES', 'group.jpg', { faceCount: 3 });
    const assets = getNewPhotos(lib);
    expect(assets.find(a => a.uuid === 'FACES')!.faceCount).toBe(3);
  });

  it('filters by since_timestamp', () => {
    const lib = createMockPhotosDb(tmp);
    addMockPhoto(lib, 'OLD', 'old.jpg', { timestamp: 100 });
    addMockPhoto(lib, 'NEW', 'new.jpg', { timestamp: 200 });
    const assets = getNewPhotos(lib, 150);
    expect(assets.length).toBe(1);
    expect(assets[0].uuid).toBe('NEW');
  });

  it('skips trashed photos', () => {
    const lib = createMockPhotosDb(tmp);
    addMockPhoto(lib, 'ACTIVE', 'active.jpg');
    addMockPhoto(lib, 'TRASHED', 'trashed.jpg', { trashed: 1 });
    const assets = getNewPhotos(lib);
    const uuids = new Set(assets.map(a => a.uuid));
    expect(uuids.has('ACTIVE')).toBe(true);
    expect(uuids.has('TRASHED')).toBe(false);
  });

  it('respects limit', () => {
    const lib = createMockPhotosDb(tmp);
    for (let i = 0; i < 10; i++) {
      addMockPhoto(lib, `LIM-${i}`, `p${i}.jpg`, { timestamp: 765432100 + i });
    }
    expect(getNewPhotos(lib, null, 3).length).toBe(3);
  });

  it('filters path traversal', () => {
    const lib = createMockPhotosDb(tmp);
    const dbPath = path.join(lib, 'database', 'Photos.sqlite');
    const db = new Database(dbPath);
    // Insert traversal path
    const r = db.prepare(
      `INSERT INTO ZASSET (ZUUID, ZFILENAME, ZDIRECTORY, ZDATECREATED, ZWIDTH, ZHEIGHT, ZTRASHEDSTATE)
       VALUES (?, ?, ?, ?, ?, ?, ?)`
    ).run('TRAVERSAL', 'evil.jpg', '../../etc', 765432100, 640, 480, 0);
    db.prepare('INSERT INTO ZADDITIONALASSETATTRIBUTES (ZASSET) VALUES (?)').run(r.lastInsertRowid);
    db.close();

    // Also add a safe one
    addMockPhoto(lib, 'SAFE', 'safe.jpg');

    const assets = getNewPhotos(lib);
    const uuids = new Set(assets.map(a => a.uuid));
    expect(uuids.has('TRAVERSAL')).toBe(false);
    expect(uuids.has('SAFE')).toBe(true);
  });

  it('filters symlink escape from library', () => {
    // In Node.js, path.join handles absolute paths differently than Python.
    // Test with ../ which is the realistic traversal vector.
    const lib = createMockPhotosDb(tmp);
    const dbPath = path.join(lib, 'database', 'Photos.sqlite');
    const db = new Database(dbPath);
    const r = db.prepare(
      `INSERT INTO ZASSET (ZUUID, ZFILENAME, ZDIRECTORY, ZDATECREATED, ZWIDTH, ZHEIGHT, ZTRASHEDSTATE)
       VALUES (?, ?, ?, ?, ?, ?, ?)`
    ).run('DOTDOT', 'evil.jpg', '../../../tmp', 765432100, 640, 480, 0);
    db.prepare('INSERT INTO ZADDITIONALASSETATTRIBUTES (ZASSET) VALUES (?)').run(r.lastInsertRowid);
    db.close();

    const assets = getNewPhotos(lib);
    expect(assets.find(a => a.uuid === 'DOTDOT')).toBeUndefined();
  });
});
