import { describe, expect, it } from 'vitest';

import { createFreshSave } from '../../src/systems/persistence.js';
import { computeUnlocks } from '../../src/systems/progression.js';
import {
  buildEpisodeSelectCards,
  buildEpisodeSelectSnapshot,
  buildLevelSelectCards
} from '../../src/systems/selectScreenModels.js';

describe('episode and level select models', () => {
  it('builds three horizontal chapter cards with hard debug invariants', () => {
    const save = {
      ...createFreshSave(),
      bestScore: { '1-01': 33000, '1-02': 42060 },
      bestStars: { '1-01': 3, '1-02': 2 }
    };
    const cards = buildEpisodeSelectCards(save, computeUnlocks(save, { env: {} }));
    const snapshot = buildEpisodeSelectSnapshot(cards, { focusIndex: 0 });

    expect(snapshot.cardCount).toBe(3);
    expect(snapshot.leftToRightEpisodes).toEqual([1, 2, 3]);
    expect(snapshot.horizontalFlow).toBe(true);
    expect(snapshot.allStarTalliesMatch).toBe(true);
    expect(cards.map((card) => card.title)).toEqual([
      'Poached Eggs',
      'Mighty Hoax',
      'Danger Above'
    ]);
    expect(cards[0]).toMatchObject({
      scoreTotal: 75060,
      scoreTotalText: 'Score 75,060',
      starTallyText: '5/15',
      locked: false
    });
    expect(cards[1].starTallyText).toMatch(/^\d+\/15$/);
    expect(cards[1]).toMatchObject({
      locked: true,
      visuallyDimmed: true,
      padlockOverlay: true
    });
    expect(snapshot.arrow).toMatchObject({
      visible: true,
      advancesChapters: true
    });
  });

  it('marks seeded unlocked levels as selectable and later levels as dimmed', () => {
    const save = {
      ...createFreshSave(),
      cleared: ['1-01'],
      bestScore: { '1-01': 33000 },
      bestStars: { '1-01': 3 }
    };
    const cards = buildLevelSelectCards(1, save, computeUnlocks(save, { env: {} }));

    expect(cards.find((card) => card.levelId === '1-01')).toMatchObject({
      unlocked: true,
      statusText: 'Cleared',
      bestStarsText: '3/3'
    });
    expect(cards.find((card) => card.levelId === '1-02')).toMatchObject({
      unlocked: true,
      canStart: true
    });
    expect(cards.find((card) => card.levelId === '1-03')).toMatchObject({
      unlocked: false,
      visuallyDimmed: true,
      canStart: false
    });
  });
});
