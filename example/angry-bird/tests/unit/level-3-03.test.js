import { describe, expect, it } from 'vitest';

import { getEpisodeBackgroundKey } from '../../src/constants/assets.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 3-03 data', () => {
  it('defines Danger Above 6-3 as scattered wood and glass kite structures', () => {
    const level = loadLevelConfig('3-03');

    expect(level.id).toBe('3-03');
    expect(level.name).toBe('Danger Above 6-3');
    expect(getEpisodeBackgroundKey(level.id)).toBe('bg-episode-3');
    expect(level.levelWidth).toBe(1280);
    expect(level.cameraWide).toBe(false);
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.queue.map((entry) => entry.type)).toEqual([
      'chuck',
      'matilda',
      'chuck',
      'chuck'
    ]);

    expect(level.slingshotElevated).toBe(false);
    expect(level.groundY - level.anchor.y).toBeGreaterThanOrEqual(90);
    expect(level.groundY - level.anchor.y).toBeLessThan(130);
    expect(level.platforms).toEqual([]);
    expect(level.mounds).toEqual([]);

    expect(level.pigs.length).toBeGreaterThanOrEqual(3);
    expect(level.pigs.every((pig) => pig.isStatic)).toBe(true);
    const pigXs = level.pigs.map((pig) => pig.x);
    expect(Math.max(...pigXs) - Math.min(...pigXs)).toBeGreaterThanOrEqual(320);
    expect(level.pigs.some((pig) => pig.x < 820)).toBe(true);
    expect(level.pigs.some((pig) => pig.x >= 830 && pig.x <= 1020)).toBe(true);
    expect(level.pigs.some((pig) => pig.x > 1080)).toBe(true);

    const kiteCenters = [760, 940, 1120];
    kiteCenters.forEach((centerX) => {
      const groupBlocks = level.blocks.filter((block) => Math.abs(block.x - centerX) <= 95);
      const angledWood = groupBlocks.filter((block) => (
        block.material === 'wood'
        && Math.abs(block.angle) >= 35
        && Math.abs(block.angle) <= 65
        && block.width >= 80
      ));
      const glassPanels = groupBlocks.filter((block) => block.material === 'glass');

      expect(angledWood.length).toBeGreaterThanOrEqual(4);
      expect(glassPanels.length).toBeGreaterThanOrEqual(1);
    });

    const kiteWood = level.blocks.filter((block) => (
      block.material === 'wood'
      && Math.abs(block.angle) >= 35
      && Math.abs(block.angle) <= 65
    ));
    const kiteGlass = level.blocks.filter((block) => block.material === 'glass');

    expect(kiteWood.length).toBeGreaterThanOrEqual(12);
    expect(kiteGlass.length).toBeGreaterThanOrEqual(6);
  });
});
