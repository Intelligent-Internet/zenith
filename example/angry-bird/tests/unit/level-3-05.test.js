import { describe, expect, it } from 'vitest';

import { getEpisodeBackgroundKey } from '../../src/constants/assets.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 3-05 data', () => {
  it('defines Danger Above 6-10 as the wide elevated finale fort', () => {
    const level = loadLevelConfig('3-05');

    expect(level.id).toBe('3-05');
    expect(level.name).toBe('Danger Above 6-10');
    expect(getEpisodeBackgroundKey(level.id)).toBe('bg-episode-3');
    expect(level.levelWidth).toBeGreaterThan(1800);
    expect(level.cameraWide).toBe(true);
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.queue.map((entry) => entry.type)).toEqual([
      'matilda',
      'bomb',
      'matilda',
      'chuck',
      'blues',
      'red'
    ]);

    expect(level.slingshotElevated).toBe(true);
    expect(level.groundY - level.anchor.y).toBeGreaterThanOrEqual(200);
    const slingPlatform = level.platforms.find((platform) => (
      Math.abs(platform.x - level.anchor.x) <= 35
      && platform.width >= 280
      && platform.height >= 130
    ));
    expect(slingPlatform).toBeDefined();

    expect(level.pigs).toHaveLength(3);
    expect(level.pigs.every((pig) => pig.isStatic)).toBe(true);
    expect(level.pigs.some((pig) => pig.x < 850)).toBe(true);
    expect(level.pigs.some((pig) => pig.x >= 900 && pig.x <= 1150)).toBe(true);
    expect(level.pigs.some((pig) => pig.x > 1400)).toBe(true);

    const glassHutBlocks = level.blocks.filter((block) => (
      block.material === 'glass'
      && block.x >= 620
      && block.x <= 850
    ));
    const woodHutBlocks = level.blocks.filter((block) => (
      block.material === 'wood'
      && block.x >= 860
      && block.x <= 1160
    ));
    const stoneFortBlocks = level.blocks.filter((block) => (
      block.material === 'stone'
      && block.x >= 1280
      && block.x <= 1700
    ));

    expect(glassHutBlocks.length).toBeGreaterThanOrEqual(8);
    expect(glassHutBlocks.some((block) => Math.abs(block.angle) >= 25)).toBe(true);
    expect(woodHutBlocks.length).toBeGreaterThanOrEqual(10);
    expect(woodHutBlocks.some((block) => Math.abs(block.angle) >= 25)).toBe(true);
    expect(stoneFortBlocks.length).toBeGreaterThanOrEqual(14);
    expect(stoneFortBlocks.filter((block) => block.height >= 90).length)
      .toBeGreaterThanOrEqual(4);
    expect(stoneFortBlocks.filter((block) => block.y < 390).length)
      .toBeGreaterThanOrEqual(5);
  });
});
