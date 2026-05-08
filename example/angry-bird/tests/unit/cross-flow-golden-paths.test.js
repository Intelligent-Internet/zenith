import { describe, expect, it } from 'vitest';

import { recordLevelClear } from '../../src/systems/scoring.js';
import { computeUnlocks } from '../../src/systems/progression.js';
import { buildLevelSelectCards } from '../../src/systems/selectScreenModels.js';

describe('cross-flow golden path regressions', () => {
  it('surfaces the max replay result on level select after 1-star, 3-star, 2-star clears', () => {
    const freshSave = {
      schemaVersion: 1,
      cleared: [],
      bestScore: {},
      bestStars: {},
      mute: false
    };

    const lowClear = recordLevelClear(freshSave, {
      levelId: '1-01',
      score: 17000,
      stars: 1
    });
    const highClear = recordLevelClear(lowClear, {
      levelId: '1-01',
      score: 33000,
      stars: 3
    });
    const finalClear = recordLevelClear(highClear, {
      levelId: '1-01',
      score: 25000,
      stars: 2
    });
    const unlocks = computeUnlocks(finalClear, { devOverride: false });
    const card = buildLevelSelectCards(1, finalClear, unlocks)
      .find((levelCard) => levelCard.levelId === '1-01');

    expect(finalClear.bestScore['1-01']).toBe(33000);
    expect(finalClear.bestStars['1-01']).toBe(3);
    expect(card).toMatchObject({
      bestScore: 33000,
      bestStars: 3,
      bestScoreText: 'Best 33,000',
      bestStarsText: '3/3',
      cleared: true
    });
  });

  it('unlocks 1-02 from the same save after clearing 1-01', () => {
    const save = recordLevelClear({
      schemaVersion: 1,
      cleared: [],
      bestScore: {},
      bestStars: {},
      mute: false
    }, {
      levelId: '1-01',
      score: 25000,
      stars: 2
    });
    const unlocks = computeUnlocks(save, { devOverride: false });

    expect(unlocks.levels['1-01']).toBe(true);
    expect(unlocks.levels['1-02']).toBe(true);
    expect(unlocks.levels['1-03']).toBe(false);
  });
});
