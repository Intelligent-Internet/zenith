import { describe, expect, it } from 'vitest';

import { getEpisodeBackgroundKey } from '../../src/constants/assets.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 2-02 data', () => {
  it('defines Mighty Hoax 4-2 as Chuck debut with an elevated stepped slingshot', () => {
    const level = loadLevelConfig('2-02');

    expect(level.id).toBe('2-02');
    expect(level.name).toBe('Mighty Hoax 4-2');
    expect(getEpisodeBackgroundKey(level.id)).toBe('bg-episode-2');
    expect(level.queue.map((entry) => entry.type)).toEqual(['blues', 'blues', 'chuck']);
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.pigs).toHaveLength(5);
    expect(level.pigs.every((pig) => pig.tier === 'small')).toBe(true);

    expect(level.slingshotElevated).toBe(true);
    expect(level.groundY - level.anchor.y).toBeGreaterThanOrEqual(180);
    const slingSteps = level.platforms.filter((platform) => (
      Math.abs(platform.x - level.anchor.x) <= 45
      && platform.y <= level.groundY
    ));
    expect(slingSteps).toHaveLength(3);
    expect(slingSteps.map((platform) => platform.width)).toEqual([330, 245, 160]);
    expect(slingSteps.map((platform) => platform.y - platform.height)).toEqual([552, 488, 488]);
    expect(Math.min(...slingSteps.map((platform) => platform.y - platform.height)))
      .toBeGreaterThanOrEqual(level.anchor.y + 50);

    const targetPlatforms = level.platforms.filter((platform) => platform.x > 700);
    expect(targetPlatforms).toHaveLength(2);
    expect(targetPlatforms.every((platform) => platform.height >= 92)).toBe(true);
    expect(targetPlatforms[0].x).toBeLessThan(targetPlatforms[1].x);

    const minPigX = Math.min(...level.pigs.map((pig) => pig.x));
    const maxPigX = Math.max(...level.pigs.map((pig) => pig.x));
    expect(minPigX).toBeGreaterThan(760);
    expect(maxPigX).toBeLessThan(1300);
    expect(maxPigX - minPigX).toBeGreaterThanOrEqual(220);
    expect(level.pigs.every((pig) => pig.y < level.groundY - 28)).toBe(true);

    const woodBlocks = level.blocks.filter((block) => block.material === 'wood');
    const glassBlocks = level.blocks.filter((block) => block.material === 'glass');
    const stoneBlocks = level.blocks.filter((block) => block.material === 'stone');
    expect(woodBlocks.length).toBeGreaterThanOrEqual(10);
    expect(glassBlocks.length).toBeGreaterThanOrEqual(4);
    expect(stoneBlocks.length).toBeGreaterThanOrEqual(4);
    expect(stoneBlocks.some((block) => block.angle !== 0 && block.y < 430)).toBe(true);
  });
});
