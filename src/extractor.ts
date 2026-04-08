import { execFileSync } from 'child_process';
import path from 'path';
import fs from 'fs';

const URL_PATTERN = /https?:\/\/[^\s<>"')\]]+|www\.[^\s<>"')\]]+/gi;
const EMAIL_PATTERN = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g;
const PHONE_PATTERN =
  /(?:\+?1[-.\s]?)?(?:\(?[0-9]{3}\)?[-.\s]?)?[0-9]{3}[-.\s]?[0-9]{4}|(?:\+?86[-.\s]?)?1[3-9][0-9]{9}|(?:\+?[0-9]{1,3}[-.\s]?)?[0-9]{2,4}[-.\s]?[0-9]{3,4}[-.\s]?[0-9]{3,4}/g;
const MONEY_PATTERN = /[$¥€£]\s*[\d,]+\.?\d*|\d+\.?\d*\s*(?:USD|CNY|EUR|GBP|元|块)/gi;

export interface ExtractionResult {
  ocrText: string;
  urls: string[];
  qrCodes: string[];
  emails: string[];
  phones: string[];
  dates: string[];
  amounts: string[];
}

export function emptyExtraction(): ExtractionResult {
  return { ocrText: '', urls: [], qrCodes: [], emails: [], phones: [], dates: [], amounts: [] };
}

export function hasData(result: ExtractionResult): boolean {
  return !!(
    result.urls.length ||
    result.qrCodes.length ||
    result.emails.length ||
    result.phones.length ||
    result.dates.length ||
    result.amounts.length ||
    result.ocrText.trim()
  );
}

export function extractionToDict(result: ExtractionResult): Record<string, string[]> {
  return {
    urls: result.urls,
    qr_codes: result.qrCodes,
    emails: result.emails,
    phones: result.phones,
    dates: result.dates,
    amounts: result.amounts,
  };
}

export function extractFromImage(imagePath: string, swiftCliPath?: string): ExtractionResult {
  const result = emptyExtraction();

  if (!fs.existsSync(imagePath)) {
    return result;
  }

  const visionOutput = runVisionCli(imagePath, swiftCliPath);
  if (visionOutput) {
    result.ocrText = visionOutput.text || '';
    result.qrCodes = visionOutput.qr_codes || [];
  }

  if (result.ocrText) {
    result.urls = extractUrls(result.ocrText);
    result.emails = extractEmails(result.ocrText);
    result.phones = extractPhones(result.ocrText);
    result.amounts = extractAmounts(result.ocrText);
  }

  for (const qr of result.qrCodes) {
    if (qr.startsWith('http') && !result.urls.includes(qr)) {
      result.urls.push(qr);
    }
  }

  return result;
}

interface VisionOutput {
  text: string;
  qr_codes: string[];
  text_blocks: any[];
}

function runVisionCli(imagePath: string, swiftCliPath?: string): VisionOutput | null {
  if (!swiftCliPath) {
    const swiftDir = path.join(path.dirname(path.dirname(import.meta.url.replace('file://', ''))), 'swift');
    swiftCliPath = path.join(swiftDir, 'vision_ocr');
  }

  if (!fs.existsSync(swiftCliPath)) {
    return null;
  }

  try {
    const stdout = execFileSync(swiftCliPath, [imagePath], {
      timeout: 30000,
      encoding: 'utf-8',
    });
    return JSON.parse(stdout);
  } catch {
    return null;
  }
}

export function extractUrls(text: string): string[] {
  const matches = text.match(URL_PATTERN) || [];
  const seen = new Set<string>();
  const unique: string[] = [];
  for (let url of matches) {
    url = url.replace(/[.,;:!?)]+$/, '');
    if (!seen.has(url)) {
      seen.add(url);
      unique.push(url);
    }
  }
  return unique;
}

export function extractEmails(text: string): string[] {
  return [...new Set(text.match(EMAIL_PATTERN) || [])];
}

export function extractPhones(text: string): string[] {
  const matches = text.match(PHONE_PATTERN) || [];
  return [...new Set(matches)].filter((p) => p.replace(/\D/g, '').length >= 7);
}

export function extractAmounts(text: string): string[] {
  return [...new Set(text.match(MONEY_PATTERN) || [])];
}
