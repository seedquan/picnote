import { execFile } from 'child_process';
import { promisify } from 'util';
import type { PhotoAsset } from './watcher.js';
import type { PicNoteConfig } from './config.js';

const execFileAsync = promisify(execFile);

export const Classification = {
  INFORMATIONAL: 'informational',
  CASUAL: 'casual',
  AMBIGUOUS: 'ambiguous',
} as const;

const INFORMATIONAL_SCENES = new Set([
  'document', 'whiteboard', 'text', 'receipt', 'menu', 'sign',
  'poster', 'screen', 'monitor', 'label', 'book', 'newspaper',
  'magazine', 'letter', 'note', 'card', 'ticket', 'map',
  'billboard', 'blackboard', 'chalkboard',
]);

const CASUAL_SCENES = new Set([
  'selfie', 'portrait', 'landscape', 'sunset', 'sunrise', 'beach',
  'mountain', 'sky', 'pet', 'cat', 'dog', 'food', 'meal',
  'flower', 'garden', 'party', 'celebration', 'sport',
]);

export async function classifyImage(asset: PhotoAsset, config: PicNoteConfig): Promise<string> {
  const classConfig = config.classification;

  const result = classifyLocal(asset, classConfig);
  if (result !== Classification.AMBIGUOUS) {
    return result;
  }

  if (classConfig.claude_fallback) {
    return classifyWithClaude(asset, config);
  }

  return Classification.INFORMATIONAL;
}

function classifyLocal(
  asset: PhotoAsset,
  config: PicNoteConfig['classification'],
): string {
  // Rule 1: Screenshots are almost always informational
  if (asset.isScreenshot && config.auto_process_screenshots) {
    return Classification.INFORMATIONAL;
  }

  // Rule 2: Has text → likely informational
  if (asset.hasText) {
    if (asset.faceCount > 0 && !asset.isScreenshot) {
      return Classification.AMBIGUOUS;
    }
    return Classification.INFORMATIONAL;
  }

  // Rule 3: Scene labels
  const infoMatches = asset.sceneLabels.filter((l) => INFORMATIONAL_SCENES.has(l));
  const casualMatches = asset.sceneLabels.filter((l) => CASUAL_SCENES.has(l));

  if (infoMatches.length > 0 && casualMatches.length === 0) {
    return Classification.INFORMATIONAL;
  }
  if (casualMatches.length > 0 && infoMatches.length === 0) {
    return Classification.CASUAL;
  }

  // Rule 4: Faces only, no text → casual
  if (asset.faceCount > 0 && !asset.hasText && config.skip_faces_only) {
    return Classification.CASUAL;
  }

  // Rule 5: No signals
  if (asset.sceneLabels.length === 0 && !asset.hasText && asset.faceCount === 0) {
    return Classification.AMBIGUOUS;
  }

  return Classification.AMBIGUOUS;
}

async function classifyWithClaude(asset: PhotoAsset, config: PicNoteConfig): Promise<string> {
  if (!asset.filePath) return Classification.INFORMATIONAL;

  const prompt =
    'Look at this image. Is it INFORMATIONAL (contains text, schedule, URL, QR code, ' +
    'receipt, document, whiteboard, contact info, event details, or any useful data to remember) ' +
    'or CASUAL (selfie, family photo, scenery, food, pet, social moment)? ' +
    'Reply with exactly one word: INFORMATIONAL or CASUAL';

  const timeout = config.processing.claude_timeout_classify * 1000;

  try {
    const { stdout } = await execFileAsync(
      'claude',
      ['-p', prompt, '--image', asset.filePath, '--output-format', 'text'],
      { timeout, encoding: 'utf-8' },
    );

    const response = stdout.trim().toUpperCase();
    if (/\bINFORMATIONAL\b/.test(response)) {
      return Classification.INFORMATIONAL;
    } else if (/\bCASUAL\b/.test(response)) {
      return Classification.CASUAL;
    }
    console.warn(`Unexpected Claude response for ${asset.uuid}: ${response}`);
    return Classification.INFORMATIONAL;
  } catch (err: any) {
    console.warn(`Claude CLI failed for ${asset.uuid}: ${err.message}`);
    return Classification.INFORMATIONAL;
  }
}
