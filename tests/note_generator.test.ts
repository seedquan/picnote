import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import path from 'path';
import { generateNote, slugify, ensureUniquePath } from '../src/note_generator.js';
import { tmpDir, cleanup, testConfig, sampleAsset, screenshotAsset, sampleExtraction, sampleAnalysis } from './helpers.js';
import { ensureOutputDirs } from '../src/config.js';
import { emptyExtraction } from '../src/extractor.js';

let tmp: string;
beforeEach(() => { tmp = tmpDir(); });
afterEach(() => { cleanup(tmp); });

describe('slugify', () => {
  it('basic text', () => {
    expect(slugify('Hello World')).toBe('hello-world');
  });
  it('strips special chars', () => {
    const s = slugify("Receipt: $14.50 @ Store");
    expect(s).not.toContain(':');
    expect(s).not.toContain('$');
  });
  it('preserves CJK', () => {
    expect(slugify('会议记录 Meeting')).toContain('会议记录');
  });
  it('truncates long strings', () => {
    expect(slugify('A'.repeat(200)).length).toBeLessThanOrEqual(80);
  });
  it('returns untitled for empty', () => {
    expect(slugify('')).toBe('untitled');
  });
});

describe('ensureUniquePath', () => {
  it('returns path if no conflict', () => {
    const p = path.join(tmp, 'note.md');
    expect(ensureUniquePath(p)).toBe(p);
  });
  it('appends counter on conflict', () => {
    const p = path.join(tmp, 'note.md');
    fs.writeFileSync(p, 'existing');
    expect(ensureUniquePath(p)).toBe(path.join(tmp, 'note-2.md'));
  });
});

describe('generateNote', () => {
  it('creates note file', async () => {
    const config = testConfig(tmp);
    const outputPaths = ensureOutputDirs(config);
    const asset = sampleAsset(tmp);
    const notePath = await generateNote(asset, sampleExtraction(), sampleAnalysis(), config, outputPaths);
    expect(fs.existsSync(notePath)).toBe(true);
  });

  it('contains title', async () => {
    const config = testConfig(tmp);
    const outputPaths = ensureOutputDirs(config);
    const notePath = await generateNote(sampleAsset(tmp), sampleExtraction(), sampleAnalysis(), config, outputPaths);
    const content = fs.readFileSync(notePath, 'utf-8');
    expect(content).toContain('Meeting Notes - Project Sync');
  });

  it('contains source section with UUID', async () => {
    const config = testConfig(tmp);
    const outputPaths = ensureOutputDirs(config);
    const asset = sampleAsset(tmp);
    const notePath = await generateNote(asset, sampleExtraction(), sampleAnalysis(), config, outputPaths);
    const content = fs.readFileSync(notePath, 'utf-8');
    expect(content).toContain('## Source');
    expect(content).toContain(asset.uuid);
  });

  it('contains screenshot source type', async () => {
    const config = testConfig(tmp);
    const outputPaths = ensureOutputDirs(config);
    const notePath = await generateNote(screenshotAsset(tmp), sampleExtraction(), sampleAnalysis(), config, outputPaths);
    const content = fs.readFileSync(notePath, 'utf-8');
    expect(content).toContain('screenshot');
  });

  it('contains extracted URLs', async () => {
    const config = testConfig(tmp);
    const outputPaths = ensureOutputDirs(config);
    const notePath = await generateNote(sampleAsset(tmp), sampleExtraction(), sampleAnalysis(), config, outputPaths);
    const content = fs.readFileSync(notePath, 'utf-8');
    expect(content).toContain('https://example.com');
  });

  it('contains raw text', async () => {
    const config = testConfig(tmp);
    const outputPaths = ensureOutputDirs(config);
    const notePath = await generateNote(sampleAsset(tmp), sampleExtraction(), sampleAnalysis(), config, outputPaths);
    const content = fs.readFileSync(notePath, 'utf-8');
    expect(content).toContain('Meeting at 2pm');
  });

  it('contains tags', async () => {
    const config = testConfig(tmp);
    const outputPaths = ensureOutputDirs(config);
    const notePath = await generateNote(sampleAsset(tmp), sampleExtraction(), sampleAnalysis(), config, outputPaths);
    const content = fs.readFileSync(notePath, 'utf-8');
    expect(content).toContain('#meeting');
  });

  it('contains action items', async () => {
    const config = testConfig(tmp);
    const outputPaths = ensureOutputDirs(config);
    const notePath = await generateNote(sampleAsset(tmp), sampleExtraction(), sampleAnalysis(), config, outputPaths);
    const content = fs.readFileSync(notePath, 'utf-8');
    expect(content).toContain('- [ ] Follow up on project sync');
  });

  it('works with no analysis', async () => {
    const config = testConfig(tmp);
    const outputPaths = ensureOutputDirs(config);
    const ext = emptyExtraction();
    ext.ocrText = 'Just some text';
    const notePath = await generateNote(sampleAsset(tmp), ext, null, config, outputPaths);
    expect(fs.existsSync(notePath)).toBe(true);
    expect(fs.readFileSync(notePath, 'utf-8')).toContain('Just some text');
  });

  it('handles duplicate filenames', async () => {
    const config = testConfig(tmp);
    const outputPaths = ensureOutputDirs(config);
    const p1 = await generateNote(sampleAsset(tmp), sampleExtraction(), sampleAnalysis(), config, outputPaths);
    const asset2 = sampleAsset(tmp, { uuid: 'UUID-2', filename: 'photo2.jpg' });
    const p2 = await generateNote(asset2, sampleExtraction(), sampleAnalysis(), config, outputPaths);
    expect(p1).not.toBe(p2);
    expect(fs.existsSync(p1)).toBe(true);
    expect(fs.existsSync(p2)).toBe(true);
  });

  it('organized by date', async () => {
    const config = testConfig(tmp);
    const outputPaths = ensureOutputDirs(config);
    const notePath = await generateNote(sampleAsset(tmp), sampleExtraction(), sampleAnalysis(), config, outputPaths);
    expect(notePath).toContain('daily');
    expect(notePath).toContain('2026');
  });
});
