import { describe, expect, it } from 'vitest';

import { getEpisodeBackgroundKey } from '../../src/constants/assets.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 2-01 data', () => {
  it('defines Mighty Hoax 4-1 as the Episode 2 glass-roof fortress opener', () => {
    const level = loadLevelConfig('2-01');

    expect(level.id).toBe('2-01');
    expect(level.name).toBe('Mighty Hoax 4-1');
    expect(level.levelWidth).toBe(1280);
    expect(level.cameraWide).toBe(false);
    expect(getEpisodeBackgroundKey(level.id)).toBe('bg-episode-2');
    expect(level.queue.map((entry) => entry.type)).toEqual(['red', 'red', 'red']);
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.pigs).toHaveLength(3);
    expect(level.pigs.every((pig) => pig.tier === 'small')).toBe(true);

    const minPigX = Math.min(...level.pigs.map((pig) => pig.x));
    const maxPigX = Math.max(...level.pigs.map((pig) => pig.x));
    const minPigY = Math.min(...level.pigs.map((pig) => pig.y));
    const maxPigY = Math.max(...level.pigs.map((pig) => pig.y));

    expect(maxPigX - minPigX).toBeLessThanOrEqual(170);
    expect(level.pigs.every((pig) => pig.isStatic)).toBe(true);

    expect(level.platforms).toHaveLength(1);
    expect(level.platforms[0]).toEqual(expect.objectContaining({
      y: level.groundY,
      width: expect.any(Number),
      height: expect.any(Number)
    }));
    expect(level.platforms[0].height).toBeGreaterThanOrEqual(48);
    expect(level.platforms[0].height).toBeLessThanOrEqual(90);
    expect(Math.abs(level.platforms[0].x - level.anchor.x)).toBeLessThanOrEqual(20);
    expect(level.anchor.y).toBeLessThan(level.groundY - 90);
    expect(level.anchor.y).toBeGreaterThan(level.groundY - 150);
    expect(level.slingshotElevated).toBe(false);

    const glassBlocks = level.blocks.filter((block) => block.material === 'glass');
    const roofGlass = glassBlocks.filter((block) => (
      block.y < minPigY - 18
      && block.x >= minPigX - 90
      && block.x <= maxPigX + 90
    ));
    const baseGlass = glassBlocks.filter((block) => (
      block.y > maxPigY + 20
      && block.x >= minPigX - 80
      && block.x <= maxPigX + 80
    ));

    expect(roofGlass.length).toBeGreaterThanOrEqual(3);
    expect(roofGlass.some((block) => block.angle !== 0)).toBe(true);
    expect(baseGlass.length).toBeGreaterThanOrEqual(3);

    const fortressSpan = Math.max(...level.blocks.map((block) => block.y + block.height / 2))
      - Math.min(...level.blocks.map((block) => block.y - block.height / 2));
    expect(fortressSpan).toBeGreaterThanOrEqual(300);

    const centralWoodColumn = level.blocks.find((block) => (
      block.material === 'wood'
      && block.height >= 190
      && block.width <= 48
      && Math.abs(block.x - (minPigX + maxPigX) / 2) <= 35
      && block.y < minPigY - 70
    ));
    expect(centralWoodColumn).toBeDefined();

    const stoneWedgeCaps = level.blocks.filter((block) => (
      block.material === 'stone'
      && block.angle !== 0
      && block.y < minPigY
    ));
    expect(stoneWedgeCaps.some((block) => block.x < minPigX)).toBe(true);
    expect(stoneWedgeCaps.some((block) => block.x > maxPigX)).toBe(true);
  });
});
