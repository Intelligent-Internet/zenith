import { describe, expect, it } from 'vitest';

import { getEpisodeBackgroundKey } from '../../src/constants/assets.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 3-02 data', () => {
  it('defines Danger Above 6-2 as a two-story wood and glass house', () => {
    const level = loadLevelConfig('3-02');

    expect(level.id).toBe('3-02');
    expect(level.name).toBe('Danger Above 6-2');
    expect(getEpisodeBackgroundKey(level.id)).toBe('bg-episode-3');
    expect(level.levelWidth).toBe(1280);
    expect(level.cameraWide).toBe(false);
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.queue.map((entry) => entry.type)).toEqual([
      'red',
      'chuck',
      'chuck',
      'chuck'
    ]);

    expect(level.slingshotElevated).toBe(false);
    expect(level.groundY - level.anchor.y).toBeGreaterThanOrEqual(110);
    expect(level.groundY - level.anchor.y).toBeLessThan(150);
    const slingBlock = level.platforms.find((platform) => (
      Math.abs(platform.x - level.anchor.x) <= 30
      && platform.width >= 230
      && platform.width <= 290
      && platform.height >= 70
      && platform.height <= 95
    ));
    expect(slingBlock).toBeDefined();

    expect(level.pigs).toHaveLength(3);
    expect(level.pigs.every((pig) => pig.isStatic)).toBe(true);
    expect(level.pigs.every((pig) => pig.x >= 820 && pig.x <= 1140)).toBe(true);
    expect(level.pigs.every((pig) => pig.y >= 390 && pig.y <= level.groundY - 45)).toBe(true);
    expect(level.pigs.filter((pig) => pig.y < 500)).toHaveLength(1);
    expect(level.pigs.filter((pig) => pig.y >= 500)).toHaveLength(2);

    const houseWood = level.blocks.filter((block) => (
      block.material === 'wood'
      && block.x >= 760
      && block.x <= 1160
    ));
    const houseGlass = level.blocks.filter((block) => (
      block.material === 'glass'
      && block.x >= 780
      && block.x <= 1160
    ));
    const lowerFloor = houseWood.filter((block) => (
      Math.abs(block.angle) <= 5
      && block.y >= 530
      && block.y <= 615
    ));
    const upperFloor = houseWood.filter((block) => (
      Math.abs(block.angle) <= 5
      && block.y >= 430
      && block.y <= 520
    ));
    const roofBeams = houseWood.filter((block) => Math.abs(block.angle) >= 25);
    const verticalPosts = houseWood.filter((block) => block.height >= 100);

    expect(houseWood.length).toBeGreaterThanOrEqual(18);
    expect(verticalPosts.length).toBeGreaterThanOrEqual(6);
    expect(lowerFloor.length).toBeGreaterThanOrEqual(2);
    expect(upperFloor.length).toBeGreaterThanOrEqual(2);
    expect(roofBeams.length).toBeGreaterThanOrEqual(4);
    expect(houseGlass.length).toBeGreaterThanOrEqual(6);
    expect(houseGlass.filter((block) => block.y < 510)).toHaveLength(2);
    expect(houseGlass.filter((block) => block.y >= 520)).toHaveLength(4);
  });
});
