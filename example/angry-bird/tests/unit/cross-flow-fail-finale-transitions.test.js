import { describe, expect, it } from 'vitest';

import { buildLevelSelectCards } from '../../src/systems/selectScreenModels.js';
import { computeUnlocks } from '../../src/systems/progression.js';
import { createFreshScoringSave, recordLevelClear } from '../../src/systems/scoring.js';
import {
  buildClearResult,
  getClearedCardActions,
  getFailedCardActions,
  resolveLevelOutcome
} from '../../src/systems/winLose.js';

function labels(actions) {
  return actions.map((action) => action.label);
}

function cardFor(levelId, save) {
  const [episode] = levelId.split('-').map(Number);
  const unlocks = computeUnlocks(save, { devOverride: false });

  return buildLevelSelectCards(episode, save, unlocks)
    .find((card) => card.levelId === levelId);
}

describe('cross-flow fail and finale transition regressions', () => {
  it('keeps the previous best on level select after a replay failure', () => {
    const bestSave = recordLevelClear(createFreshScoringSave(), {
      levelId: '1-01',
      score: 33000,
      stars: 3
    });

    expect(resolveLevelOutcome({
      settled: true,
      pigsLeft: 1,
      birdsLeft: 0
    })).toBe('failed');

    const failedReplaySave = {
      ...bestSave,
      cleared: [...bestSave.cleared],
      bestScore: { ...bestSave.bestScore },
      bestStars: { ...bestSave.bestStars }
    };

    expect(cardFor('1-01', failedReplaySave)).toMatchObject({
      bestScore: 33000,
      bestStars: 3,
      bestScoreText: 'Best 33,000',
      bestStarsText: '3/3',
      cleared: true
    });
  });

  it('records the second-attempt score after fail retry clear', () => {
    const firstAttemptSave = createFreshScoringSave();

    expect(labels(getFailedCardActions('1-01'))).toEqual([
      'Retry',
      'Level Select'
    ]);
    expect(firstAttemptSave.bestScore['1-01']).toBeUndefined();

    const secondAttempt = buildClearResult({
      levelId: '1-01',
      baseScore: 5000,
      unusedBirdCount: 2,
      save: firstAttemptSave
    });

    expect(secondAttempt.finalScore).toBe(25000);
    expect(secondAttempt.save.bestScore['1-01']).toBe(25000);
    expect(secondAttempt.save.bestStars['1-01']).toBe(2);
    expect(secondAttempt.save.cleared).toContain('1-01');
  });

  it('offers next episode after clearing 1-05 and unlocks episode 2', () => {
    const saveBeforeFinale = {
      ...createFreshScoringSave(),
      cleared: ['1-01', '1-02', '1-03', '1-04'],
      bestScore: { '1-01': 25000, '1-02': 15000, '1-03': 40000, '1-04': 35400 },
      bestStars: { '1-01': 2, '1-02': 1, '1-03': 2, '1-04': 2 }
    };
    const result = buildClearResult({
      levelId: '1-05',
      baseScore: 51200,
      unusedBirdCount: 0,
      save: saveBeforeFinale
    });
    const unlocks = computeUnlocks(result.save, { devOverride: false });

    expect(unlocks.episodes[2]).toBe(true);
    expect(unlocks.levels['2-01']).toBe(true);
    expect(labels(getClearedCardActions({
      levelId: '1-05',
      save: result.save
    }))).toEqual([
      'Replay',
      'Next Episode',
      'Level Select'
    ]);
  });

  it('limits the final game clear card to replay and episode select', () => {
    const allButFinal = {
      ...createFreshScoringSave(),
      cleared: [
        '1-01', '1-02', '1-03', '1-04', '1-05',
        '2-01', '2-02', '2-03', '2-04', '2-05',
        '3-01', '3-02', '3-03', '3-04'
      ]
    };
    const result = buildClearResult({
      levelId: '3-05',
      baseScore: 48600,
      unusedBirdCount: 0,
      save: allButFinal
    });

    expect(result.save.cleared).toHaveLength(15);
    expect(labels(getClearedCardActions({
      levelId: '3-05',
      save: result.save
    }))).toEqual([
      'Replay',
      'Episode Select'
    ]);
  });

  it('keeps finale failure cards on retry and level select without unlocking the next episode', () => {
    const finaleCases = [
      {
        levelId: '1-05',
        clearedBefore: ['1-01', '1-02', '1-03', '1-04'],
        lockedEpisode: 2,
        lockedLevel: '2-01'
      },
      {
        levelId: '2-05',
        clearedBefore: ['1-05', '2-01', '2-02', '2-03', '2-04'],
        lockedEpisode: 3,
        lockedLevel: '3-01'
      },
      {
        levelId: '3-05',
        clearedBefore: [
          '1-05', '2-05', '3-01', '3-02', '3-03', '3-04'
        ],
        lockedEpisode: null,
        lockedLevel: null
      }
    ];

    finaleCases.forEach(({ levelId, clearedBefore, lockedEpisode, lockedLevel }) => {
      const failedSave = {
        ...createFreshScoringSave(),
        cleared: clearedBefore
      };
      const unlocks = computeUnlocks(failedSave, { devOverride: false });

      expect(labels(getFailedCardActions(levelId))).toEqual([
        'Retry',
        'Level Select'
      ]);
      expect(failedSave.cleared).not.toContain(levelId);
      if (lockedEpisode) {
        expect(unlocks.episodes[lockedEpisode]).toBe(false);
        expect(unlocks.levels[lockedLevel]).toBe(false);
      }
    });
  });
});
