import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

// ── Colors (no dependencies) ──

const isColorSupported = process.env.NO_COLOR == null && process.stdout.isTTY;

const c = (code: number, text: string) =>
  isColorSupported ? `\x1b[${code}m${text}\x1b[0m` : text;

export const color = {
  bold: (s: string) => c(1, s),
  dim: (s: string) => c(2, s),
  green: (s: string) => c(32, s),
  yellow: (s: string) => c(33, s),
  red: (s: string) => c(31, s),
  cyan: (s: string) => c(36, s),
  gray: (s: string) => c(90, s),
};

// ── Stderr logging (keeps stdout clean for piping) ──

export const log = {
  info: (msg: string) => process.stderr.write(color.cyan('ℹ') + ' ' + msg + '\n'),
  success: (msg: string) => process.stderr.write(color.green('✓') + ' ' + msg + '\n'),
  warn: (msg: string) => process.stderr.write(color.yellow('⚠') + ' ' + msg + '\n'),
  error: (msg: string) => process.stderr.write(color.red('✗') + ' ' + msg + '\n'),
};

// ── Spinner ──

const FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

export class Spinner {
  private interval: ReturnType<typeof setInterval> | null = null;
  private frame = 0;
  private msg: string;

  constructor(msg: string) {
    this.msg = msg;
  }

  start(): this {
    if (!process.stderr.isTTY) {
      process.stderr.write(this.msg + '...\n');
      return this;
    }
    this.interval = setInterval(() => {
      const f = color.cyan(FRAMES[this.frame % FRAMES.length]);
      process.stderr.write(`\r${f} ${this.msg}`);
      this.frame++;
    }, 80);
    return this;
  }

  update(msg: string): void {
    this.msg = msg;
  }

  stop(final?: string): void {
    if (this.interval) {
      clearInterval(this.interval);
      this.interval = null;
      if (process.stderr.isTTY) {
        process.stderr.write('\r\x1b[K'); // clear line
      }
    }
    if (final) {
      process.stderr.write(final + '\n');
    }
  }
}

// ── Version ──

export function getVersion(): string {
  // Walk up from the compiled dist/ to find package.json
  const thisFile = fileURLToPath(import.meta.url);
  let dir = path.dirname(thisFile);
  for (let i = 0; i < 5; i++) {
    const pkgPath = path.join(dir, 'package.json');
    if (fs.existsSync(pkgPath)) {
      const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8'));
      return pkg.version;
    }
    dir = path.dirname(dir);
  }
  return '0.0.0';
}

export function getPackageName(): string {
  const thisFile = fileURLToPath(import.meta.url);
  let dir = path.dirname(thisFile);
  for (let i = 0; i < 5; i++) {
    const pkgPath = path.join(dir, 'package.json');
    if (fs.existsSync(pkgPath)) {
      const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8'));
      return pkg.name;
    }
    dir = path.dirname(dir);
  }
  return 'picnote';
}

// ── Readline helper for prompts ──

export async function prompt(question: string): Promise<string> {
  const { createInterface } = await import('readline');
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
  });
}
