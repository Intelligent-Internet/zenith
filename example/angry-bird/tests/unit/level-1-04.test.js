import { describe, expect, it } from 'vitest';

import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 1-04 data', () => {
  it('defines Poached Eggs 1-7 as twin glass huts on raised earth platforms', () => {
    const level = loadLevelConfig('1-04');

    expect(level.id).toBe('1-04');
    expect(level.name).toBe('Poached Eggs 1-7');
    expect(level.levelWidth).toBe(1280);
    expect(level.cameraWide).toBe(false);
    expect(level.slingshotElevated).toBe(false);
    expect(level.queue.map((entry) => entry.type)).toEqual(['red', 'red', 'red', 'red']);
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.pigs).toHaveLength(3);
    expect(level.pigs.every((pig) => pig.tier === 'small')).toBe(true);

    expect(level.platforms).toHaveLength(2);
    expect(level.platforms.every((platform) => platform.y === level.groundY)).toBe(true);
    expect(level.platforms.every((platform) => platform.height >= 100)).toBe(true);
    expect(level.platforms[0].x).toBeLessThan(level.platforms[1].x);

    const platformTop = level.groundY - level.platforms[0].height;
    expect(level.pigs.every((pig) => pig.y < platformTop)).toBe(true);

    const glassBlocks = level.blocks.filter((block) => block.material === 'glass');
    expect(glassBlocks.length).toBeGreaterThanOrEqual(8);

    const leftGlass = glassBlocks.filter((block) => block.x < 960);
    const rightGlass = glassBlocks.filter((block) => block.x > 960);
    expect(leftGlass.length).toBeGreaterThanOrEqual(3);
    expect(rightGlass.length).toBeGreaterThanOrEqual(3);

    const woodBeams = level.blocks.filter((block) => (
      block.material === 'wood'
      && block.width >= 300
      && block.height <= 28
    ));
    expect(woodBeams.length).toBeGreaterThanOrEqual(2);
    expect(Math.min(...woodBeams.map((block) => block.y))).toBeLessThan(platformTop - 100);

    const stoneCaps = level.blocks.filter((block) => (
      block.material === 'stone'
      && block.width <= 46
      && block.height <= 46
    ));
    expect(stoneCaps.length).toBeGreaterThanOrEqual(4);
    expect(stoneCaps.some((block) => block.x < 820)).toBe(true);
    expect(stoneCaps.some((block) => block.x > 1100)).toBe(true);
  });
});
