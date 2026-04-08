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
  it('screenshot with text → informational', () => {
    expect(classifyImage(screenshotAsset(tmp), config)).toBe(Classification.INFORMATIONAL);
  });

  it('selfie → casual', () => {
    expect(classifyImage(selfieAsset(tmp), config)).toBe(Classification.CASUAL);
  });

  it('faces only → casual', () => {
    const asset = sampleAsset(tmp, { faceCount: 3, sceneLabels: ['portrait'] });
    expect(classifyImage(asset, config)).toBe(Classification.CASUAL);
  });

  it('landscape → casual', () => {
    const asset = sampleAsset(tmp, { sceneLabels: ['landscape', 'mountain'] });
    expect(classifyImage(asset, config)).toBe(Classification.CASUAL);
  });

  it('document → informational', () => {
    const asset = sampleAsset(tmp, { sceneLabels: ['document'], hasText: true });
    expect(classifyImage(asset, config)).toBe(Classification.INFORMATIONAL);
  });

  it('receipt → informational', () => {
    const asset = sampleAsset(tmp, { sceneLabels: ['receipt'], hasText: true });
    expect(classifyImage(asset, config)).toBe(Classification.INFORMATIONAL);
  });

  it('screenshot flag fast-tracks', () => {
    const asset = sampleAsset(tmp, { isScreenshot: true });
    expect(classifyImage(asset, config)).toBe(Classification.INFORMATIONAL);
  });

  it('has text → informational', () => {
    const asset = sampleAsset(tmp, { hasText: true, sceneLabels: ['text'] });
    expect(classifyImage(asset, config)).toBe(Classification.INFORMATIONAL);
  });

  it('no signals + no fallback → informational (default)', () => {
    config.classification.claude_fallback = false;
    const asset = sampleAsset(tmp);
    expect(classifyImage(asset, config)).toBe(Classification.INFORMATIONAL);
  });
});
