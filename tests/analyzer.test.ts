import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { parseJsonResponse, generateLocalAnalysis } from '../src/analyzer.js';
import { emptyExtraction } from '../src/extractor.js';

describe('parseJsonResponse', () => {
  it('parses clean JSON', () => {
    const r = parseJsonResponse('{"title": "Test", "type": "note"}');
    expect(r?.title).toBe('Test');
  });

  it('parses JSON with code fences', () => {
    const r = parseJsonResponse('```json\n{"title": "Test"}\n```');
    expect(r?.title).toBe('Test');
  });

  it('parses generic code fences', () => {
    const r = parseJsonResponse('```\n{"title": "Test"}\n```');
    expect(r?.title).toBe('Test');
  });

  it('returns null for invalid JSON', () => {
    expect(parseJsonResponse('not json')).toBeNull();
  });

  it('returns null for empty response', () => {
    expect(parseJsonResponse('')).toBeNull();
  });

  it('handles text around fences', () => {
    const r = parseJsonResponse('Here:\n```json\n{"title": "X"}\n```\nDone.');
    expect(r?.title).toBe('X');
  });

  it('takes first code block when multiple', () => {
    const r = parseJsonResponse('```json\n{"title": "First"}\n```\n```json\n{"title": "Second"}\n```');
    expect(r?.title).toBe('First');
  });

  it('handles unclosed fence by finding JSON object', () => {
    const r = parseJsonResponse('```json\n{"title": "X", "type": "note"}');
    expect(r?.title).toBe('X');
  });

  it('extracts JSON from surrounding text without fences', () => {
    const r = parseJsonResponse('Here is the result:\n{"title": "Test", "type": "note"}\nHope this helps!');
    expect(r?.title).toBe('Test');
  });

  it('handles trailing commas', () => {
    const r = parseJsonResponse('{"title": "Test", "tags": ["a", "b"]}');
    expect(r?.title).toBe('Test');
  });

  it('returns null for completely invalid input', () => {
    expect(parseJsonResponse('no json here at all')).toBeNull();
  });
});

describe('generateLocalAnalysis', () => {
  it('detects receipt type', () => {
    const ext = emptyExtraction();
    ext.ocrText = 'Store receipt';
    ext.amounts = ['$14.50'];
    expect(generateLocalAnalysis(ext).type).toBe('receipt');
  });

  it('detects link type', () => {
    const ext = emptyExtraction();
    ext.ocrText = 'Visit site';
    ext.urls = ['https://example.com'];
    expect(generateLocalAnalysis(ext).type).toBe('link');
  });

  it('detects contact type', () => {
    const ext = emptyExtraction();
    ext.ocrText = 'Contact info';
    ext.emails = ['a@b.com'];
    expect(generateLocalAnalysis(ext).type).toBe('contact');
  });

  it('detects code type (QR)', () => {
    const ext = emptyExtraction();
    ext.qrCodes = ['https://qr.example.com'];
    expect(generateLocalAnalysis(ext).type).toBe('code');
  });

  it('defaults to note type', () => {
    const ext = emptyExtraction();
    ext.ocrText = 'Some text';
    expect(generateLocalAnalysis(ext).type).toBe('note');
  });

  it('uses first line as title', () => {
    const ext = emptyExtraction();
    ext.ocrText = 'Meeting Notes\nLine two';
    expect(generateLocalAnalysis(ext).title).toBe('Meeting Notes');
  });
});
