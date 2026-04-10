import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { classifyImage, Classification } from '../src/classifier.js';
import { tmpDir, cleanup, sampleAsset, screenshotAsset, selfieAsset, testConfig } from './helpers.js';

let tmp: string;
let config: ReturnType<typeof testConfig>;

beforeEach(() => {
  tmp = tmpDir();
  config = testConfig(tmp);
});
afterEach(() => { cleanup(tmp); });

describe('Local classification', () => {
  it('screenshot with text → informational', async () => {
    expect(await classifyImage(screenshotAsset(tmp), config)).toBe(Classification.INFORMATIONAL);
  });

  it('selfie → casual', async () => {
    expect(await classifyImage(selfieAsset(tmp), config)).toBe(Classification.CASUAL);
  });

  it('faces only → casual', async () => {
    const asset = sampleAsset(tmp, { faceCount: 3, sceneLabels: ['portrait'] });
    expect(await classifyImage(asset, config)).toBe(Classification.CASUAL);
  });

  it('landscape → casual', async () => {
    const asset = sampleAsset(tmp, { sceneLabels: ['landscape', 'mountain'] });
    expect(await classifyImage(asset, config)).toBe(Classification.CASUAL);
  });

  it('document → informational', async () => {
    const asset = sampleAsset(tmp, { sceneLabels: ['document'], hasText: true });
    expect(await classifyImage(asset, config)).toBe(Classification.INFORMATIONAL);
  });

  it('receipt → informational', async () => {
    const asset = sampleAsset(tmp, { sceneLabels: ['receipt'], hasText: true });
    expect(await classifyImage(asset, config)).toBe(Classification.INFORMATIONAL);
  });

  it('screenshot flag fast-tracks', async () => {
    const asset = sampleAsset(tmp, { isScreenshot: true });
    expect(await classifyImage(asset, config)).toBe(Classification.INFORMATIONAL);
  });

  it('has text → informational', async () => {
    const asset = sampleAsset(tmp, { hasText: true, sceneLabels: ['text'] });
    expect(await classifyImage(asset, config)).toBe(Classification.INFORMATIONAL);
  });

  it('no signals + no fallback → informational (default)', async () => {
    config.classification.claude_fallback = false;
    const asset = sampleAsset(tmp);
    expect(await classifyImage(asset, config)).toBe(Classification.INFORMATIONAL);
  });
});
