import fs from 'fs';
import path from 'path';
import os from 'os';
import yaml from 'js-yaml';

export interface PicNoteConfig {
  output_dir: string;
  photos_library: string;
  classification: {
    auto_process_screenshots: boolean;
    skip_faces_only: boolean;
    claude_fallback: boolean;
  };
  notes: {
    format: string;
    organize_by: string;
  };
  sensitive_keywords: string[];
  processing: {
    max_batch_size: number;
    thumbnail_size: number;
    thumbnail_quality: number;
    claude_timeout_classify: number;
    claude_timeout_analyze: number;
    concurrency: number;
  };
}

export const DEFAULT_CONFIG: PicNoteConfig = {
  output_dir: '~/Documents/PicNote',
  photos_library: '~/Pictures/Photos Library.photoslibrary',
  classification: {
    auto_process_screenshots: true,
    skip_faces_only: true,
    claude_fallback: true,
  },
  notes: {
    format: 'markdown',
    organize_by: 'date',
  },
  sensitive_keywords: ['password', 'SSN', 'bank account'],
  processing: {
    max_batch_size: 50,
    thumbnail_size: 800,
    thumbnail_quality: 85,
    claude_timeout_classify: 30,
    claude_timeout_analyze: 60,
    concurrency: 3,
  },
};

/** Home directory: ~/.picnote/ */
export function getHomeDir(): string {
  return path.join(os.homedir(), '.picnote');
}

/** Path to the config file inside the home directory */
export function getConfigPath(): string {
  return path.join(getHomeDir(), 'config.yaml');
}

export function expandHome(p: string): string {
  if (p.startsWith('~/') || p === '~') {
    return path.join(os.homedir(), p.slice(2));
  }
  return p;
}

function deepMerge(base: any, override: any): any {
  const result = { ...base };
  for (const key of Object.keys(override)) {
    if (
      key in result &&
      typeof result[key] === 'object' &&
      !Array.isArray(result[key]) &&
      typeof override[key] === 'object' &&
      !Array.isArray(override[key])
    ) {
      result[key] = deepMerge(result[key], override[key]);
    } else {
      result[key] = override[key];
    }
  }
  return result;
}

export function loadConfig(configPath?: string): PicNoteConfig {
  let config: PicNoteConfig = JSON.parse(JSON.stringify(DEFAULT_CONFIG));

  if (!configPath) {
    // Look in home directory first, then fall back to project dir
    const homeConfig = getConfigPath();
    if (fs.existsSync(homeConfig)) {
      configPath = homeConfig;
    } else {
      configPath = path.join(path.dirname(path.dirname(import.meta.url.replace('file://', ''))), 'config.yaml');
    }
  }

  if (fs.existsSync(configPath)) {
    const raw = fs.readFileSync(configPath, 'utf-8');
    const userConfig = yaml.load(raw) as Record<string, any> | null;
    if (userConfig) {
      config = deepMerge(config, userConfig);
    }
  }

  config.output_dir = expandHome(config.output_dir);
  config.photos_library = expandHome(config.photos_library);

  return config;
}

export function saveConfig(config: PicNoteConfig, configPath?: string): void {
  const p = configPath ?? getConfigPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, yaml.dump(config, { indent: 2 }), 'utf-8');
}

export function isInitialized(): boolean {
  return fs.existsSync(getConfigPath());
}

export interface OutputPaths {
  output_dir: string;
  vault_dir: string;
  assets_dir: string;
  data_dir: string;
  logs_dir: string;
}

export function getOutputPaths(config: PicNoteConfig): OutputPaths {
  const output_dir = config.output_dir;
  return {
    output_dir,
    vault_dir: path.join(output_dir, 'vault'),
    assets_dir: path.join(output_dir, 'vault', 'assets'),
    data_dir: path.join(output_dir, 'data'),
    logs_dir: path.join(output_dir, 'logs'),
  };
}

export function ensureOutputDirs(config: PicNoteConfig): OutputPaths {
  const paths = getOutputPaths(config);
  for (const p of Object.values(paths)) {
    fs.mkdirSync(p, { recursive: true });
  }
  return paths;
}
