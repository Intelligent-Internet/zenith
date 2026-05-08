import { describe, expect, it } from 'vitest';

import level101 from '../../src/data/levels/1-01.json';
import {
  loadLevelConfig,
  resolveLevelConfig,
  resolveLevelId
} from '../../src/systems/levelLoader.js';

describe('level loader', () => {
  it('defines level 1-01 with the contract hard invariants', () => {
    const level = loadLevelConfig('1-01');

    expect(level.id).toBe('1-01');
    expect(level.levelWidth).toBe(1280);
    expect(level.cameraWide).toBe(false);
    expect(level.slingshotElevated).toBe(false);
    expect(level.anchor).toEqual({ x: 210, y: 548 });
    expect(level.queue.map((entry) => entry.type)).toEqual(['red', 'red', 'red']);
    expect(level.pigs).toEqual([
      expect.objectContaining({ tier: 'small' })
    ]);
    expect(level.tntCrates).toEqual([]);
    expect(level.blocks.some((block) => block.material === 'glass')).toBe(true);
    expect(level.blocks.filter((block) => block.material === 'wood').length).toBeGreaterThanOrEqual(4);
  });

  it('normalizes declarative JSON without mutating the source data', () => {
    const level = loadLevelConfig('1-01');

    level.queue[0].type = 'blues';
    expect(level101.birds).toEqual(['red', 'red', 'red']);
    expect(loadLevelConfig('1-01').queue.map((entry) => entry.type)).toEqual(['red', 'red', 'red']);
  });

  it('resolves direct URL level requests and LevelSelect-passed data', () => {
    expect(resolveLevelId({
      sceneData: {},
      search: '?level=1-01'
    })).toBe('1-01');

    const fromUrl = resolveLevelConfig({
      sceneData: {},
      search: '?level=1-01'
    });
    expect(fromUrl.id).toBe('1-01');

    const passedLevel = {
      ...level101,
      id: 'custom-level',
      birds: ['red']
    };
    const fromData = resolveLevelConfig({
      sceneData: { levelConfig: passedLevel },
      search: '?level=1-01'
    });

    expect(fromData.id).toBe('custom-level');
    expect(fromData.queue.map((entry) => entry.type)).toEqual(['red']);
  });

  it('loads authored level 3-05 data instead of its former slingshot fallback', () => {
    const level = loadLevelConfig('3-05');

    expect(level.id).toBe('3-05');
    expect(level.name).toBe('Danger Above 6-10');
    expect(level.cameraWide).toBe(true);
    expect(level.slingshotElevated).toBe(true);
    expect(level.queue.map((entry) => entry.type)).toEqual([
      'matilda',
      'bomb',
      'matilda',
      'chuck',
      'blues',
      'red'
    ]);
    expect(level.pigs).toHaveLength(3);
    expect(level.blocks.some((block) => block.material === 'stone')).toBe(true);
  });
});
