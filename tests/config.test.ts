import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';
import { loadConfig, getOutputPaths, ensureOutputDirs, DEFAULT_CONFIG } from '../src/config.js';
import { tmpDir, cleanup } from './helpers.js';

let tmp: string;
beforeEach(() => { tmp = tmpDir(); });
afterEach(() => { cleanup(tmp); });

describe('loadConfig', () => {
  it('returns defaults when no config file exists', () => {
    const config = loadConfig(path.join(tmp, 'nonexistent.yaml'));
    expect(config.classification.auto_process_screenshots).toBe(true);
    expect(config.classification.skip_faces_only).toBe(true);
    expect(config.notes.format).toBe('markdown');
  });

  it('loads custom output_dir from config.yaml', () => {
    const p = path.join(tmp, 'config.yaml');
    fs.writeFileSync(p, yaml.dump({ output_dir: '/custom/output' }));
    const config = loadConfig(p);
    expect(config.output_dir).toBe('/custom/output');
  });

  it('expands ~ in paths', () => {
    const p = path.join(tmp, 'config.yaml');
    fs.writeFileSync(p, yaml.dump({ output_dir: '~/Documents/PicNote' }));
    const config = loadConfig(p);
    expect(config.output_dir).not.toContain('~');
  });

  it('handles empty config file', () => {
    const p = path.join(tmp, 'config.yaml');
    fs.writeFileSync(p, '');
    const config = loadConfig(p);
    expect(config.output_dir).toBeDefined();
  });

  it('loads sensitive_keywords', () => {
    const p = path.join(tmp, 'config.yaml');
    fs.writeFileSync(p, yaml.dump({ sensitive_keywords: ['password', 'secret'] }));
    const config = loadConfig(p);
    expect(config.sensitive_keywords).toContain('password');
    expect(config.sensitive_keywords).toContain('secret');
  });

  it('deep merges preserving defaults', () => {
    const p = path.join(tmp, 'config.yaml');
    fs.writeFileSync(p, yaml.dump({ classification: { auto_process_screenshots: false } }));
    const config = loadConfig(p);
    expect(config.classification.auto_process_screenshots).toBe(false);
    expect(config.classification.skip_faces_only).toBe(true); // preserved
  });

  it('has timeout defaults', () => {
    const config = loadConfig(path.join(tmp, 'nonexistent.yaml'));
    expect(config.processing.claude_timeout_classify).toBe(30);
    expect(config.processing.claude_timeout_analyze).toBe(60);
  });

  it('overrides timeout values', () => {
    const p = path.join(tmp, 'config.yaml');
    fs.writeFileSync(p, yaml.dump({ processing: { claude_timeout_classify: 90 } }));
    const config = loadConfig(p);
    expect(config.processing.claude_timeout_classify).toBe(90);
  });
});

describe('getOutputPaths', () => {
  it('returns all required paths', () => {
    const config = loadConfig(path.join(tmp, 'x.yaml'));
    const paths = getOutputPaths(config);
    expect(paths).toHaveProperty('output_dir');
    expect(paths).toHaveProperty('vault_dir');
    expect(paths).toHaveProperty('assets_dir');
    expect(paths).toHaveProperty('data_dir');
    expect(paths).toHaveProperty('logs_dir');
  });

  it('all paths are under output_dir', () => {
    const config = loadConfig(path.join(tmp, 'x.yaml'));
    const paths = getOutputPaths(config);
    for (const [key, p] of Object.entries(paths)) {
      expect(p.startsWith(paths.output_dir)).toBe(true);
    }
  });
});

describe('ensureOutputDirs', () => {
  it('creates all directories', () => {
    const config = loadConfig(path.join(tmp, 'x.yaml'));
    config.output_dir = path.join(tmp, 'out');
    const paths = ensureOutputDirs(config);
    for (const p of Object.values(paths)) {
      expect(fs.existsSync(p)).toBe(true);
    }
  });
});
