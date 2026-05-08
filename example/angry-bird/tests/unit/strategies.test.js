import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { buildOpenLevelSetupCommands, isClearedEndState } from '../../scripts/run_strategy.js';
import { EPISODE_LEVEL_IDS } from '../../src/constants/scoring.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';

const repoRoot = join(import.meta.dirname, '..', '..');
const strategyDir = join(repoRoot, 'tests', 'strategies');
const runnerPath = join(repoRoot, 'scripts', 'run_strategy.js');
const levelIds = Object.values(EPISODE_LEVEL_IDS).flat();

function readStrategy(levelId) {
  const path = join(strategyDir, `${levelId}.json`);

  expect(existsSync(path), `missing strategy file for ${levelId}`).toBe(true);
  return JSON.parse(readFileSync(path, 'utf8'));
}

describe('level completion strategies', () => {
  it('ships the public-surface strategy runner', () => {
    expect(existsSync(runnerPath)).toBe(true);
  });

  it('clears storage before opening transient level boot URLs', () => {
    const commands = buildOpenLevelSetupCommands('1-01', 'http://127.0.0.1:4100/');
    const storageClearIndex = commands.findIndex((command) => command.join(' ') === 'storage local clear');
    const transientLevelOpenIndex = commands.findIndex(
      ([command, target]) => command === 'open' && target.includes('?level=1-01')
    );

    expect(commands).toEqual([
      ['open', 'http://127.0.0.1:4100/'],
      ['storage', 'local', 'clear'],
      ['open', 'http://127.0.0.1:4100/?level=1-01']
    ]);
    expect(storageClearIndex).toBeGreaterThanOrEqual(0);
    expect(storageClearIndex).toBeLessThan(transientLevelOpenIndex);
    expect(commands.some(([command]) => command === 'reload')).toBe(false);
  });

  it('requires the cleared end card before accepting runner evidence', () => {
    expect(isClearedEndState({
      endCard: { outcome: 'cleared' },
      pigsLeft: 0,
      save: { cleared: ['1-01'] }
    })).toBe(true);
    expect(isClearedEndState({
      endCard: null,
      pigsLeft: 0,
      save: { cleared: ['1-01'] }
    })).toBe(false);
  });

  it('defines one deterministic strategy for every level', () => {
    expect(existsSync(strategyDir)).toBe(true);

    for (const levelId of levelIds) {
      const strategy = readStrategy(levelId);

      expect(Array.isArray(strategy), `${levelId} strategy must be an array`).toBe(true);
      expect(strategy.length, `${levelId} strategy must launch at least one bird`).toBeGreaterThan(0);

      strategy.forEach((step, index) => {
        const dragVector = step?.['drag-vector'];
        const abilityTapTime = step?.['ability-tap-time'];

        expect(Array.isArray(dragVector), `${levelId} step ${index} missing drag-vector`).toBe(true);
        expect(dragVector, `${levelId} step ${index} drag-vector must be [x,y]`).toHaveLength(2);
        expect(Number.isFinite(dragVector[0]), `${levelId} step ${index} drag x must be finite`).toBe(true);
        expect(Number.isFinite(dragVector[1]), `${levelId} step ${index} drag y must be finite`).toBe(true);
        expect(Math.hypot(dragVector[0], dragVector[1]), `${levelId} step ${index} drag must launch`).toBeGreaterThan(8);
        expect(dragVector[0], `${levelId} step ${index} must pull left/back from the slingshot`).toBeLessThanOrEqual(0);
        expect(
          abilityTapTime === null || Number.isFinite(abilityTapTime),
          `${levelId} step ${index} ability-tap-time must be null or finite milliseconds`
        ).toBe(true);
      });
    }
  });

  it('keeps the 2-04 strategy as a full-roster golden path', () => {
    const level = loadLevelConfig('2-04');
    const strategy = readStrategy('2-04');

    expect(level.queue.map((bird) => bird.type)).toEqual(['red', 'blues', 'chuck', 'bomb']);
    expect(strategy).toHaveLength(level.queue.length);
    expect(strategy.map((step) => step['ability-tap-time'] === null)).toEqual([
      true,
      false,
      false,
      false
    ]);
  });
});
