import { describe, expect, it } from 'vitest';

import { getEpisodeBackgroundKey } from '../../src/constants/assets.js';
import { BIRD_VISUALS } from '../../src/constants/slingshot.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 2-03 data', () => {
  it('defines Mighty Hoax 4-6 as the Matilda debut lattice with Matilda queue sprites', () => {
    const level = loadLevelConfig('2-03');

    expect(level.id).toBe('2-03');
    expect(level.name).toBe('Mighty Hoax 4-6');
    expect(level.levelWidth).toBe(1280);
    expect(level.cameraWide).toBe(false);
    expect(getEpisodeBackgroundKey(level.id)).toBe('bg-episode-2');
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.queue.map((entry) => entry.type)).toEqual([
      'matilda',
      'matilda',
      'matilda',
      'matilda'
    ]);
    expect(level.queue.map((entry) => BIRD_VISUALS[entry.type].texture)).toEqual([
      'bird-matilda',
      'bird-matilda',
      'bird-matilda',
      'bird-matilda'
    ]);
    expect(level.queue.map((entry) => BIRD_VISUALS[entry.type].texture))
      .not.toContain('bird-chuck');

    expect(level.pigs).toHaveLength(3);
    expect(level.pigs.every((pig) => pig.tier === 'small')).toBe(true);
    expect(level.pigs.every((pig) => pig.isStatic)).toBe(true);
    expect(level.pigs.every((pig) => pig.x >= 830 && pig.x <= 1065)).toBe(true);
    expect(level.pigs.every((pig) => pig.y < level.groundY - 95)).toBe(true);

    expect(level.slingshotElevated).toBe(true);
    expect(level.groundY - level.anchor.y).toBeGreaterThanOrEqual(170);
    const slingBox = level.platforms.find((platform) => Math.abs(platform.x - level.anchor.x) <= 20);
    expect(slingBox).toEqual(expect.objectContaining({
      width: expect.any(Number),
      height: expect.any(Number)
    }));
    expect(slingBox.width).toBeGreaterThanOrEqual(240);
    expect(slingBox.height).toBeGreaterThanOrEqual(110);
    expect(level.anchor.y).toBeLessThanOrEqual(slingBox.y - slingBox.height - 45);

    const woodBlocks = level.blocks.filter((block) => block.material === 'wood');
    const stoneBlocks = level.blocks.filter((block) => block.material === 'stone');
    const glassBlocks = level.blocks.filter((block) => block.material === 'glass');
    expect(glassBlocks).toHaveLength(0);
    expect(woodBlocks.length).toBeGreaterThanOrEqual(20);
    expect(stoneBlocks.length).toBeGreaterThanOrEqual(4);

    const leftLeaningWood = woodBlocks.filter((block) => block.angle <= -25);
    const rightLeaningWood = woodBlocks.filter((block) => block.angle >= 25);
    const horizontalWood = woodBlocks.filter((block) => Math.abs(block.angle) <= 5);
    expect(leftLeaningWood.length).toBeGreaterThanOrEqual(6);
    expect(rightLeaningWood.length).toBeGreaterThanOrEqual(6);
    expect(horizontalWood.length).toBeGreaterThanOrEqual(5);

    const minPigX = Math.min(...level.pigs.map((pig) => pig.x));
    const maxPigX = Math.max(...level.pigs.map((pig) => pig.x));
    const topStoneCaps = stoneBlocks.filter((block) => block.y < 430);
    expect(topStoneCaps.some((block) => block.x < minPigX)).toBe(true);
    expect(topStoneCaps.some((block) => block.x > maxPigX)).toBe(true);
  });
});
