/* global process */

import { existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

describe('asset policy checker', () => {
  function runScript(scriptName, env = {}) {
    const scriptPath = resolve(repoRoot, 'scripts', scriptName);
    return spawnSync(scriptPath, {
      cwd: repoRoot,
      env: {
        ...process.env,
        ...env
      },
      encoding: 'utf8'
    });
  }

  it('passes the current shipped asset set and writes a report', () => {
    const reportPath = resolve(repoRoot, 'tmp/asset-policy-test-report.tsv');
    mkdirSync(dirname(reportPath), { recursive: true });

    const result = runScript('check_no_rovio_assets.sh', {
      ASSET_POLICY_REPORT: reportPath
    });

    expect(result.status, result.stderr || result.stdout).toBe(0);
    expect(result.stdout).toContain(reportPath);
    expect(existsSync(reportPath)).toBe(true);
  });

  it('verifies every shipped audio file has provenance', () => {
    const result = runScript('check_audio_credits.sh');

    expect(result.status, result.stderr || result.stdout).toBe(0);
    expect(result.stdout).toContain('Audio credits OK');
  });

  it('passes audio originality checks and writes a report', () => {
    const reportPath = resolve(repoRoot, 'tmp/audio-originality-test-report.tsv');
    mkdirSync(dirname(reportPath), { recursive: true });

    const result = runScript('check_audio_originality.sh', {
      AUDIO_ORIGINALITY_REPORT: reportPath
    });

    expect(result.status, result.stderr || result.stdout).toBe(0);
    expect(result.stdout).toContain('Audio originality OK');
    expect(result.stdout).toContain(reportPath);
    expect(existsSync(reportPath)).toBe(true);
  });
});
