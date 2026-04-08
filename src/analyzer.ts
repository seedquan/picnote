import { execFileSync } from 'child_process';
import type { ExtractionResult } from './extractor.js';
import { extractionToDict } from './extractor.js';
import type { PicNoteConfig } from './config.js';

const ANALYSIS_PROMPT = `Analyze this image and extract structured information. You are given OCR text that was already extracted from the image.

OCR Text:
{ocr_text}

Already extracted data:
{extracted_data}

Based on the image and the OCR text, provide a JSON response with these fields:
{
    "title": "A concise descriptive title for this capture (under 60 chars)",
    "summary": "2-3 sentence summary of what this image contains and why it might be useful",
    "type": "one of: receipt, event, link, contact, note, code, document",
    "tags": ["list", "of", "relevant", "tags"],
    "urls": ["any additional URLs found"],
    "dates": ["any dates/times found, in ISO format when possible"],
    "contacts": ["any contact info found"],
    "action_items": ["any action items or things to remember"]
}

Respond with ONLY the JSON object, no other text.`;

export interface AnalysisResult {
  title: string;
  summary: string;
  type: string;
  tags: string[];
  urls: string[];
  dates: string[];
  contacts: string[];
  action_items: string[];
}

export function analyzeImage(
  imagePath: string,
  extraction: ExtractionResult,
  config: PicNoteConfig,
): AnalysisResult | null {
  // Check for sensitive content (normalize OCR text for robust matching)
  const sensitiveKeywords = config.sensitive_keywords || [];
  const ocrNormalized = extraction.ocrText.toLowerCase().replace(/[\s\u200b\u200c\u200d\ufeff]+/g, '');
  const ocrLower = extraction.ocrText.toLowerCase();

  for (const keyword of sensitiveKeywords) {
    const kwLower = keyword.toLowerCase();
    const kwCollapsed = kwLower.replace(/\s+/g, '');
    if (ocrLower.includes(kwLower) || ocrNormalized.includes(kwCollapsed)) {
      console.info(`Sensitive content detected ('${keyword}'), skipping cloud analysis`);
      return generateLocalAnalysis(extraction);
    }
  }

  const prompt = ANALYSIS_PROMPT
    .replace('{ocr_text}', extraction.ocrText.slice(0, 2000))
    .replace('{extracted_data}', JSON.stringify(extractionToDict(extraction), null, 2));

  const timeout = config.processing.claude_timeout_analyze * 1000;

  try {
    const stdout = execFileSync(
      'claude',
      ['-p', prompt, '--image', imagePath, '--output-format', 'text'],
      { timeout, encoding: 'utf-8' },
    );

    return parseJsonResponse(stdout.trim());
  } catch (err: any) {
    console.warn(`Claude CLI analysis failed: ${err.message}`);
    return generateLocalAnalysis(extraction);
  }
}

export function parseJsonResponse(response: string): AnalysisResult | null {
  const match = response.match(/```(?:json)?\s*\n?(.*?)```/s);
  const candidate = match ? match[1].trim() : response.trim();

  try {
    return JSON.parse(candidate);
  } catch {
    console.warn(`Failed to parse Claude response as JSON: ${response.slice(0, 200)}`);
    return null;
  }
}

export function generateLocalAnalysis(extraction: ExtractionResult): AnalysisResult {
  let type = 'note';
  if (extraction.amounts.length) type = 'receipt';
  else if (extraction.qrCodes.length) type = 'code';
  else if (extraction.urls.length) type = 'link';
  else if (extraction.emails.length || extraction.phones.length) type = 'contact';

  const firstLine = extraction.ocrText.split('\n')[0]?.slice(0, 60) || 'Untitled capture';

  return {
    title: firstLine,
    summary: `Captured ${type} with extracted text content.`,
    type,
    tags: [type],
    urls: extraction.urls,
    dates: extraction.dates,
    contacts: [...extraction.emails, ...extraction.phones],
    action_items: [],
  };
}
