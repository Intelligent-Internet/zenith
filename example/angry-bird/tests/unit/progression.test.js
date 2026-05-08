import { describe, expect, it } from 'vitest';

import { createFreshSave } from '../../src/systems/persistence.js';
import { computeUnlocks } from '../../src/systems/progression.js';
import {
  buildEpisodeSelectCards,
  buildLevelSelectCards
} from '../../src/systems/selectScreenModels.js';
import viteConfig from '../../vite.config.js';

function prodUnlocks(save) {
  return computeUnlocks(save, { env: {} });
}

function expectOnlyLevels(unlocks, unlockedLevelIds) {
  expect(Object.entries(unlocks.levels).filter(([, unlocked]) => unlocked).map(([levelId]) => levelId))
    .toEqual(unlockedLevelIds);
}

describe('progression unlock graph', () => {
  it('fresh save unlocks only episode 1 and level 1-01', () => {
    const unlocks = prodUnlocks(createFreshSave());

    expect(unlocks.episodes).toEqual({ 1: true, 2: false, 3: false });
    expectOnlyLevels(unlocks, ['1-01']);
  });

  it('clearing a level unlocks the immediate next level only', () => {
    const unlocks = prodUnlocks({
      ...createFreshSave(),
      cleared: ['1-01']
    });

    expect(unlocks.episodes[2]).toBe(false);
    expectOnlyLevels(unlocks, ['1-01', '1-02']);
  });

  it('clearing an episode finale unlocks the next episode card and first level', () => {
    const unlocks = prodUnlocks({
      ...createFreshSave(),
      cleared: ['1-01', '1-02', '1-03', '1-04', '1-05']
    });

    expect(unlocks.episodes).toEqual({ 1: true, 2: true, 3: false });
    expect(unlocks.levels['2-01']).toBe(true);
    expect(unlocks.levels['2-02']).toBe(false);
  });

  it('clearing the second episode finale unlocks episode 3 without unlocking 3-02', () => {
    const unlocks = prodUnlocks({
      ...createFreshSave(),
      cleared: [
        '1-01',
        '1-02',
        '1-03',
        '1-04',
        '1-05',
        '2-01',
        '2-02',
        '2-03',
        '2-04',
        '2-05'
      ]
    });

    expect(unlocks.episodes).toEqual({ 1: true, 2: true, 3: true });
    expect(unlocks.levels['3-01']).toBe(true);
    expect(unlocks.levels['3-02']).toBe(false);
  });

  it('uses the cleared set authoritatively for inconsistent saves', () => {
    const unlocks = prodUnlocks({
      ...createFreshSave(),
      cleared: ['1-05']
    });

    expect(unlocks.episodes).toEqual({ 1: true, 2: true, 3: false });
    expect(unlocks.levels['1-01']).toBe(true);
    expect(unlocks.levels['1-02']).toBe(false);
    expect(unlocks.levels['1-03']).toBe(false);
    expect(unlocks.levels['1-04']).toBe(false);
    expect(unlocks.levels['2-01']).toBe(true);
    expect(unlocks.levels['2-02']).toBe(false);
  });

  it('does not unlock levels from best score or star records', () => {
    const unlocks = prodUnlocks({
      ...createFreshSave(),
      bestScore: { '1-02': 42060, '2-01': 62100 },
      bestStars: { '1-02': 3, '2-01': 3 }
    });

    expect(unlocks.episodes).toEqual({ 1: true, 2: false, 3: false });
    expectOnlyLevels(unlocks, ['1-01']);
  });

  it('keeps a dev-cleared episode reachable in prod without unlocking its chain', () => {
    const save = {
      ...createFreshSave(),
      cleared: ['3-05'],
      bestScore: { '3-05': 92350 },
      bestStars: { '3-05': 3 }
    };
    const unlocks = prodUnlocks(save);
    const episodeCards = buildEpisodeSelectCards(save, unlocks);
    const levelCards = buildLevelSelectCards(3, save, unlocks);

    expect(unlocks.episodes).toEqual({ 1: true, 2: false, 3: true });
    expectOnlyLevels(unlocks, ['1-01', '3-01']);
    expect(episodeCards.find((card) => card.episode === 3)).toMatchObject({
      locked: false,
      scoreTotal: 92350,
      starTally: 3
    });
    expect(levelCards.find((card) => card.levelId === '3-05')).toMatchObject({
      locked: true,
      cleared: true,
      bestScore: 92350,
      bestStars: 3
    });
  });

  it('marks locked chapter and level cards as click-feedback targets', () => {
    const save = createFreshSave();
    const unlocks = prodUnlocks(save);
    const episodeCards = buildEpisodeSelectCards(save, unlocks);
    const levelCards = buildLevelSelectCards(1, save, unlocks);

    expect(episodeCards.find((card) => card.episode === 2)).toMatchObject({
      locked: true,
      lockedClickFeedback: 'shake-highlight'
    });
    expect(levelCards.find((card) => card.levelId === '1-02')).toMatchObject({
      locked: true,
      lockedClickFeedback: 'shake-highlight'
    });
  });

  it('exposes ANGRY_BIRD_* variables to Vite client code', () => {
    expect(viteConfig.envPrefix).toContain('ANGRY_BIRD_');
  });
});
