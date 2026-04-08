import { describe, it, expect } from 'vitest';
import { extractUrls, extractEmails, extractPhones, extractAmounts, emptyExtraction, hasData, extractionToDict } from '../src/extractor.js';

describe('URL extraction', () => {
  it('extracts http URL', () => {
    expect(extractUrls('Visit https://example.com for more')).toContain('https://example.com');
  });
  it('extracts multiple URLs', () => {
    expect(extractUrls('https://a.com and https://b.com/path').length).toBe(2);
  });
  it('returns empty for no URLs', () => {
    expect(extractUrls('No links here')).toEqual([]);
  });
  it('deduplicates', () => {
    expect(extractUrls('https://example.com and https://example.com').length).toBe(1);
  });
  it('strips trailing punctuation', () => {
    expect(extractUrls('See https://example.com.')[0]).toBe('https://example.com');
  });
  it('extracts www URL', () => {
    expect(extractUrls('Visit www.example.com').length).toBe(1);
  });
});

describe('Email extraction', () => {
  it('extracts email', () => {
    expect(extractEmails('Contact: user@example.com')).toContain('user@example.com');
  });
  it('returns empty for no emails', () => {
    expect(extractEmails('No emails')).toEqual([]);
  });
});

describe('Phone extraction', () => {
  it('extracts US phone', () => {
    expect(extractPhones('Call 555-123-4567').length).toBeGreaterThanOrEqual(1);
  });
  it('extracts Chinese mobile', () => {
    expect(extractPhones('联系电话 13912345678').length).toBeGreaterThanOrEqual(1);
  });
  it('filters short numbers', () => {
    expect(extractPhones('Room 123')).toEqual([]);
  });
});

describe('Amount extraction', () => {
  it('extracts dollar amount', () => {
    const amounts = extractAmounts('Total: $14.50');
    expect(amounts.some(a => a.includes('14.50'))).toBe(true);
  });
  it('extracts yuan', () => {
    expect(extractAmounts('价格: ¥128.00').length).toBeGreaterThanOrEqual(1);
  });
  it('returns empty for no amounts', () => {
    expect(extractAmounts('No money here')).toEqual([]);
  });
});

describe('ExtractionResult helpers', () => {
  it('empty result has no data', () => {
    expect(hasData(emptyExtraction())).toBe(false);
  });
  it('result with text has data', () => {
    const r = emptyExtraction();
    r.ocrText = 'Some text';
    expect(hasData(r)).toBe(true);
  });
  it('toDict returns correct shape', () => {
    const r = emptyExtraction();
    r.urls = ['https://example.com'];
    const d = extractionToDict(r);
    expect(d.urls).toEqual(['https://example.com']);
    expect(d.phones).toEqual([]);
  });
});
