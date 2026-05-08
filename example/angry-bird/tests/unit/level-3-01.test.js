import { describe, expect, it } from 'vitest';

import { getEpisodeBackgroundKey } from '../../src/constants/assets.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 3-01 data', () => {
  it('defines Danger Above 6-1 with the jungle tower layout', () => {
    const level = loadLevelConfig('3-01');

    expect(level.id).toBe('3-01');
    expect(level.name).toBe('Danger Above 6-1');
    expect(getEpisodeBackgroundKey(level.id)).toBe('bg-episode-3');
    expect(level.levelWidth).toBeGreaterThan(1600);
    expect(level.cameraWide).toBe(true);
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.queue.map((entry) => entry.type)).toEqual([
      'red',
      'red',
      'red',
      'chuck'
    ]);

    expect(level.slingshotElevated).toBe(false);
    expect(level.groundY - level.anchor.y).toBeGreaterThanOrEqual(90);
    expect(level.groundY - level.anchor.y).toBeLessThan(150);
    const slingPlatform = level.platforms.find((platform) => (
      Math.abs(platform.x - level.anchor.x) <= 30
      && platform.width <= 260
      && platform.height >= 60
      && platform.height <= 90
    ));
    expect(slingPlatform).toBeDefined();

    expect(level.pigs).toHaveLength(4);
    expect(level.pigs.every((pig) => pig.tier === 'small')).toBe(true);
    expect(level.pigs.every((pig) => pig.isStatic)).toBe(true);
    const groundPigs = level.pigs.filter((pig) => pig.y >= level.groundY - 70);
    const towerPigs = level.pigs.filter((pig) => pig.y < level.groundY - 120);
    expect(groundPigs).toHaveLength(3);
    expect(towerPigs).toHaveLength(1);
    expect(groundPigs.filter((pig) => pig.x < 1120)).toHaveLength(2);
    expect(groundPigs.some((pig) => pig.x > 1450)).toBe(true);

    const woodTower = level.blocks.filter((block) => (
      block.material === 'wood'
      && block.x >= 1120
      && block.x <= 1420
    ));
    const stoneRoof = level.blocks.filter((block) => (
      block.material === 'stone'
      && block.x >= 1160
      && block.x <= 1360
      && block.y < 390
    ));

    expect(woodTower.length).toBeGreaterThanOrEqual(10);
    expect(woodTower.filter((block) => block.height >= 82).length).toBeGreaterThanOrEqual(4);
    expect(woodTower.filter((block) => block.width >= 120).length).toBeGreaterThanOrEqual(3);
    expect(stoneRoof.length).toBeGreaterThanOrEqual(3);
    expect(stoneRoof.filter((block) => Math.abs(block.angle) >= 20).length)
      .toBeGreaterThanOrEqual(2);
  });
});
