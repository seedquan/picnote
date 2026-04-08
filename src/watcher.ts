import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';

// Apple's Core Data epoch: 2001-01-01T00:00:00Z
export const APPLE_EPOCH = new Date('2001-01-01T00:00:00Z');

export interface PhotoAsset {
  uuid: string;
  filename: string;
  directory: string;
  filePath: string;
  isScreenshot: boolean;
  sceneLabels: string[];
  hasText: boolean;
  faceCount: number;
  capturedAt: Date | null;
  width: number;
  height: number;
}

export function appleTimestampToDate(timestamp: number | null): Date | null {
  if (timestamp == null) return null;
  return new Date(APPLE_EPOCH.getTime() + timestamp * 1000);
}

export function openPhotosDbReadonly(photosLibrary: string): Database.Database {
  const dbPath = path.join(photosLibrary, 'database', 'Photos.sqlite');
  if (!fs.existsSync(dbPath)) {
    throw new Error(`Photos database not found: ${dbPath}`);
  }
  return new Database(dbPath, { readonly: true });
}

export function getNewPhotos(
  photosLibrary: string,
  sinceTimestamp?: number | null,
  limit = 50,
): PhotoAsset[] {
  const db = openPhotosDbReadonly(photosLibrary);
  try {
    return queryAssets(db, photosLibrary, sinceTimestamp ?? null, limit);
  } finally {
    db.close();
  }
}

function queryAssets(
  db: Database.Database,
  photosLibrary: string,
  sinceTimestamp: number | null,
  limit: number,
): PhotoAsset[] {
  let query = `
    SELECT
      a.ZUUID,
      a.ZFILENAME,
      a.ZDIRECTORY,
      a.ZDATECREATED,
      a.ZWIDTH,
      a.ZHEIGHT,
      COALESCE(aa.ZISDETECTEDSCREENSHOT, 0) as is_screenshot,
      COALESCE(aa.ZCHARACTERRECOGNITIONATTRIBUTES, 0) as has_ocr
    FROM ZASSET a
    LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON a.Z_PK = aa.ZASSET
    WHERE a.ZTRASHEDSTATE = 0
  `;
  const params: any[] = [];

  if (sinceTimestamp != null) {
    query += ' AND a.ZDATECREATED > ?';
    params.push(sinceTimestamp);
  }

  query += ' ORDER BY a.ZDATECREATED DESC LIMIT ?';
  params.push(limit);

  const rows = db.prepare(query).all(...params) as any[];
  const assets: PhotoAsset[] = [];

  for (const row of rows) {
    const uuid = row.ZUUID as string;
    const filename = row.ZFILENAME as string;
    const directory = (row.ZDIRECTORY as string) || '';

    const filePath = path.join(photosLibrary, 'originals', directory, filename);

    // Defense-in-depth: ensure resolved path stays within library
    const realPath = path.resolve(filePath);
    const realLibrary = path.resolve(photosLibrary);
    if (!realPath.startsWith(realLibrary + path.sep) && realPath !== realLibrary) {
      console.warn(`Path traversal detected for ${uuid}: ${filePath}`);
      continue;
    }

    const sceneLabels = getSceneLabels(db, uuid);
    const faceCount = getFaceCount(db, uuid);

    assets.push({
      uuid,
      filename,
      directory,
      filePath,
      isScreenshot: !!row.is_screenshot,
      sceneLabels,
      hasText: !!row.has_ocr,
      faceCount,
      capturedAt: appleTimestampToDate(row.ZDATECREATED),
      width: row.ZWIDTH || 0,
      height: row.ZHEIGHT || 0,
    });
  }

  return assets;
}

function getSceneLabels(db: Database.Database, assetUuid: string): string[] {
  try {
    const rows = db
      .prepare(
        `SELECT sc.ZLABEL
        FROM ZSCENECLASSIFICATION sc
        JOIN ZASSET a ON sc.ZASSET = a.Z_PK
        WHERE a.ZUUID = ? AND sc.ZCONFIDENCE > 0.5`,
      )
      .all(assetUuid) as any[];
    return rows.map((r) => r.ZLABEL as string);
  } catch {
    return [];
  }
}

function getFaceCount(db: Database.Database, assetUuid: string): number {
  try {
    const row = db
      .prepare(
        `SELECT COUNT(*) as cnt
        FROM ZDETECTEDFACE df
        JOIN ZASSET a ON df.ZASSET = a.Z_PK
        WHERE a.ZUUID = ?`,
      )
      .get(assetUuid) as any;
    return row?.cnt || 0;
  } catch {
    return 0;
  }
}

export function getLastProcessedTimestamp(photosLibrary: string): number | null {
  const db = openPhotosDbReadonly(photosLibrary);
  try {
    const row = db
      .prepare('SELECT MAX(ZDATECREATED) as ts FROM ZASSET WHERE ZTRASHEDSTATE = 0')
      .get() as any;
    return row?.ts ?? null;
  } finally {
    db.close();
  }
}
