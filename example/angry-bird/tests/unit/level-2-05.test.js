import { describe, expect, it } from 'vitest';

import { getEpisodeBackgroundKey } from '../../src/constants/assets.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 2-05 data', () => {
  it('defines Mighty Hoax 4-10 as a wide long-mound debris field', () => {
    const level = loadLevelConfig('2-05');

    expect(level.id).toBe('2-05');
    expect(level.name).toBe('Mighty Hoax 4-10');
    expect(getEpisodeBackgroundKey(level.id)).toBe('bg-episode-2');
    expect(level.levelWidth).toBeGreaterThan(1800);
    expect(level.cameraWide).toBe(true);
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.queue.map((entry) => entry.type)).toEqual([
      'red',
      'blues',
      'chuck',
      'red'
    ]);

    expect(level.slingshotElevated).toBe(false);
    expect(level.groundY - level.anchor.y).toBeLessThan(150);

    expect(level.pigs.length).toBeGreaterThanOrEqual(2);
    expect(level.pigs.length).toBeLessThanOrEqual(3);
    expect(level.pigs.every((pig) => pig.tier === 'small')).toBe(true);
    expect(level.pigs.every((pig) => pig.isStatic)).toBe(true);
    expect(level.pigs.every((pig) => pig.x >= 760 && pig.x <= 1500)).toBe(true);
    expect(level.pigs.every((pig) => pig.y < level.groundY - 45)).toBe(true);

    expect(level.mounds).toHaveLength(1);
    expect(level.mounds[0]).toEqual(expect.objectContaining({
      x: expect.any(Number),
      y: level.groundY,
      width: expect.any(Number),
      height: expect.any(Number)
    }));
    expect(level.mounds[0].width).toBeGreaterThanOrEqual(900);
    expect(level.mounds[0].height).toBeGreaterThanOrEqual(140);

    const woodBlocks = level.blocks.filter((block) => block.material === 'wood');
    const stoneBlocks = level.blocks.filter((block) => block.material === 'stone');
    const glassBlocks = level.blocks.filter((block) => block.material === 'glass');
    expect(glassBlocks).toHaveLength(0);
    expect(woodBlocks.length).toBeGreaterThanOrEqual(8);
    expect(stoneBlocks.length).toBeGreaterThanOrEqual(6);

    expect(stoneBlocks.some((block) => block.x < 930)).toBe(true);
    expect(stoneBlocks.some((block) => block.x > 1400)).toBe(true);
    expect(woodBlocks.some((block) => block.x >= 1000 && block.x <= 1380)).toBe(true);
    expect(woodBlocks.filter((block) => Math.abs(block.angle) >= 15).length)
      .toBeGreaterThanOrEqual(4);
    expect(stoneBlocks.filter((block) => Math.abs(block.angle) >= 10).length)
      .toBeGreaterThanOrEqual(2);
  });
});
