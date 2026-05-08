import { describe, expect, it } from 'vitest';

import { getEpisodeBackgroundKey } from '../../src/constants/assets.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 2-04 data', () => {
  it('defines Mighty Hoax 4-5 as the wide Bomb debut sampler', () => {
    const level = loadLevelConfig('2-04');

    expect(level.id).toBe('2-04');
    expect(level.name).toBe('Mighty Hoax 4-5');
    expect(getEpisodeBackgroundKey(level.id)).toBe('bg-episode-2');
    expect(level.levelWidth).toBeGreaterThan(1800);
    expect(level.cameraWide).toBe(true);
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.queue.map((entry) => entry.type)).toEqual([
      'red',
      'blues',
      'chuck',
      'bomb'
    ]);

    expect(level.slingshotElevated).toBe(true);
    expect(level.groundY - level.anchor.y).toBeGreaterThanOrEqual(200);
    const slingPedestal = level.platforms.find((platform) => (
      Math.abs(platform.x - level.anchor.x) <= 30
      && platform.width >= 300
      && platform.height >= 120
    ));
    expect(slingPedestal).toBeDefined();
    expect(level.anchor.y).toBeLessThanOrEqual(slingPedestal.y - slingPedestal.height - 70);

    expect(level.pigs).toHaveLength(5);
    expect(level.pigs.every((pig) => pig.tier === 'small')).toBe(true);
    expect(level.pigs.every((pig) => pig.isStatic)).toBe(true);
    expect(level.pigs.some((pig) => pig.x < 850)).toBe(true);
    expect(level.pigs.filter((pig) => pig.x >= 950 && pig.x <= 1260)).toHaveLength(2);
    expect(level.pigs.filter((pig) => pig.x > 1250)).toHaveLength(2);

    const leftGlassCastle = level.blocks.filter((block) => (
      block.material === 'glass'
      && block.x < 900
    ));
    const centralWoodFrame = level.blocks.filter((block) => (
      block.material === 'wood'
      && block.x >= 980
      && block.x <= 1280
    ));
    const centralStoneCaps = level.blocks.filter((block) => (
      block.material === 'stone'
      && block.x >= 980
      && block.x <= 1280
      && block.y < 450
    ));
    const rightGlassColumn = level.blocks.filter((block) => (
      block.material === 'glass'
      && block.x > 1250
    ));

    expect(leftGlassCastle.length).toBeGreaterThanOrEqual(8);
    expect(leftGlassCastle.some((block) => block.y < 500)).toBe(true);
    expect(centralWoodFrame.length).toBeGreaterThanOrEqual(14);
    expect(centralWoodFrame.filter((block) => Math.abs(block.angle) <= 5).length)
      .toBeGreaterThanOrEqual(4);
    expect(centralWoodFrame.filter((block) => block.height >= 90).length)
      .toBeGreaterThanOrEqual(6);
    expect(centralStoneCaps.length).toBeGreaterThanOrEqual(4);
    expect(rightGlassColumn.length).toBeGreaterThanOrEqual(5);
    expect(new Set(rightGlassColumn.map((block) => block.x)).size).toBeLessThanOrEqual(2);
  });
});
