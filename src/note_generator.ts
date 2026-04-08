import fs from 'fs';
import path from 'path';
import sharp from 'sharp';
import type { ExtractionResult } from './extractor.js';
import type { AnalysisResult } from './analyzer.js';
import type { PhotoAsset } from './watcher.js';
import type { PicNoteConfig, OutputPaths } from './config.js';

export async function generateNote(
  asset: PhotoAsset,
  extraction: ExtractionResult,
  analysis: AnalysisResult | null,
  config: PicNoteConfig,
  outputPaths: OutputPaths,
): Promise<string> {
  const organizeBy = config.notes.organize_by;
  const capturedAt = asset.capturedAt || new Date();

  let noteDir: string;
  if (organizeBy === 'date') {
    const dateDir = formatDatePath(capturedAt);
    noteDir = path.join(outputPaths.vault_dir, 'daily', dateDir);
  } else {
    const noteType = analysis?.type || 'note';
    noteDir = path.join(outputPaths.vault_dir, noteType);
  }
  fs.mkdirSync(noteDir, { recursive: true });

  const title = analysis?.title || defaultTitle(asset);
  const filename = slugify(title) + '.md';
  let notePath = path.join(noteDir, filename);
  notePath = ensureUniquePath(notePath);

  const thumbnailPath = await createThumbnail(asset, capturedAt, config, outputPaths);
  const thumbnailRel = thumbnailPath
    ? path.relative(outputPaths.vault_dir, thumbnailPath)
    : null;

  const content = buildNoteContent(asset, extraction, analysis, title, capturedAt, thumbnailRel);
  fs.writeFileSync(notePath, content, 'utf-8');

  return notePath;
}

function buildNoteContent(
  asset: PhotoAsset,
  extraction: ExtractionResult,
  analysis: AnalysisResult | null,
  title: string,
  capturedAt: Date,
  thumbnailRel: string | null,
): string {
  const lines: string[] = [];

  const noteType = analysis?.type || 'note';
  const tags = analysis?.tags || [];
  const tagStr = tags.map((t) => `#${t}`).join(' ');

  lines.push(`# ${title}`);
  lines.push(`**Captured**: ${formatDateTime(capturedAt)}`);
  lines.push(`**Type**: ${noteType}`);
  if (tagStr) lines.push(`**Tags**: ${tagStr}`);
  lines.push('');

  // Source section
  lines.push('## Source');
  lines.push(`- **Photo UUID**: ${asset.uuid}`);
  lines.push(`- **Original path**: ${asset.filePath}`);
  lines.push(`- **Source type**: ${asset.isScreenshot ? 'screenshot' : 'photo'}`);
  lines.push('');

  // Summary
  if (analysis?.summary) {
    lines.push('## Summary');
    lines.push(analysis.summary);
    lines.push('');
  }

  // Extracted Data
  const hasExtracted =
    extraction.urls.length ||
    extraction.qrCodes.length ||
    extraction.emails.length ||
    extraction.phones.length ||
    extraction.amounts.length ||
    analysis?.dates?.length ||
    analysis?.contacts?.length ||
    analysis?.action_items?.length;

  if (hasExtracted) {
    lines.push('## Extracted Data');

    if (extraction.urls.length) {
      lines.push('**URLs**:');
      for (const url of extraction.urls) lines.push(`- ${url}`);
    }
    if (extraction.qrCodes.length) {
      lines.push('**QR Codes**:');
      for (const qr of extraction.qrCodes) lines.push(`- ${qr}`);
    }
    if (extraction.emails.length) {
      lines.push('**Emails**:');
      for (const email of extraction.emails) lines.push(`- ${email}`);
    }
    if (extraction.phones.length) {
      lines.push('**Phones**:');
      for (const phone of extraction.phones) lines.push(`- ${phone}`);
    }
    if (extraction.amounts.length) {
      lines.push('**Amounts**:');
      for (const amount of extraction.amounts) lines.push(`- ${amount}`);
    }
    if (analysis?.dates?.length) {
      lines.push('**Dates**:');
      for (const d of analysis.dates) lines.push(`- ${d}`);
    }
    if (analysis?.contacts?.length) {
      lines.push('**Contacts**:');
      for (const c of analysis.contacts) lines.push(`- ${c}`);
    }
    if (analysis?.action_items?.length) {
      lines.push('**Action Items**:');
      for (const item of analysis.action_items) lines.push(`- [ ] ${item}`);
    }
    lines.push('');
  }

  // Raw Text
  if (extraction.ocrText.trim()) {
    lines.push('## Raw Text');
    lines.push('```');
    lines.push(extraction.ocrText.trim());
    lines.push('```');
    lines.push('');
  }

  // Thumbnail
  if (thumbnailRel) {
    lines.push('## Thumbnail');
    lines.push(`![[${thumbnailRel}]]`);
    lines.push('');
  }

  return lines.join('\n');
}

async function createThumbnail(
  asset: PhotoAsset,
  capturedAt: Date,
  config: PicNoteConfig,
  outputPaths: OutputPaths,
): Promise<string | null> {
  if (!fs.existsSync(asset.filePath)) return null;

  const dateDir = formatDatePath(capturedAt);
  const thumbDir = path.join(outputPaths.assets_dir, dateDir);
  fs.mkdirSync(thumbDir, { recursive: true });

  const thumbFilename = `${asset.uuid}-thumb.jpg`;
  const thumbPath = path.join(thumbDir, thumbFilename);

  if (fs.existsSync(thumbPath)) return thumbPath;

  const maxSize = config.processing.thumbnail_size;
  const quality = config.processing.thumbnail_quality;

  try {
    await sharp(asset.filePath)
      .resize(maxSize, maxSize, { fit: 'inside' })
      .jpeg({ quality })
      .toFile(thumbPath);
    return thumbPath;
  } catch (err) {
    console.warn(`Thumbnail creation failed for ${asset.uuid}: ${err}`);
    try {
      fs.copyFileSync(asset.filePath, thumbPath);
      console.info(`Fell back to copying original for ${asset.uuid}`);
      return thumbPath;
    } catch (copyErr) {
      console.error(`Thumbnail fallback copy also failed for ${asset.uuid}: ${copyErr}`);
      return null;
    }
  }
}

function defaultTitle(asset: PhotoAsset): string {
  const name = path.parse(asset.filename).name;
  return asset.isScreenshot ? `Screenshot ${name}` : `Photo ${name}`;
}

export function slugify(text: string): string {
  let slug = text
    .replace(/[^\w\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .toLowerCase();
  return (slug || 'untitled').slice(0, 80);
}

export function ensureUniquePath(filePath: string): string {
  if (!fs.existsSync(filePath)) return filePath;
  const { dir, name, ext } = path.parse(filePath);
  let counter = 2;
  while (fs.existsSync(path.join(dir, `${name}-${counter}${ext}`))) {
    counter++;
  }
  return path.join(dir, `${name}-${counter}${ext}`);
}

function formatDatePath(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}/${m}/${d}`;
}

function formatDateTime(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const h = String(date.getHours()).padStart(2, '0');
  const min = String(date.getMinutes()).padStart(2, '0');
  return `${y}-${m}-${d} ${h}:${min}`;
}
