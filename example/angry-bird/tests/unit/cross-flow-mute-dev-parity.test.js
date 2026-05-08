import { describe, expect, it, vi } from 'vitest';

vi.mock('phaser', () => ({
  default: {
    Scene: class {
      constructor(key) {
        this.scene = { key };
      }
    },
    Scenes: {
      Events: {
        SHUTDOWN: 'shutdown'
      }
    }
  }
}));

import Game from '../../src/scenes/Game.js';
import { EPISODE_LEVEL_IDS } from '../../src/constants/scoring.js';
import { createPersistence } from '../../src/systems/persistence.js';
import { computeUnlocks } from '../../src/systems/progression.js';
import { recordLevelClear } from '../../src/systems/scoring.js';
import { buildLevelSelectCards } from '../../src/systems/selectScreenModels.js';
import { setGlobalSoundMute } from '../../src/systems/soundMute.js';

function createMemoryStorage() {
  const values = new Map();

  return {
    getItem: vi.fn((key) => values.get(key) ?? null),
    setItem: vi.fn((key, value) => values.set(key, String(value)))
  };
}

describe('cross-flow mute/dev/parity regressions', () => {
  it('unlocks every shipped level under the dev override for level-select reachability', () => {
    const unlocks = computeUnlocks(undefined, { devOverride: true });
    const allLevelIds = Object.values(EPISODE_LEVEL_IDS).flat();

    expect(allLevelIds).toHaveLength(15);
    expect(allLevelIds.every((levelId) => unlocks.levels[levelId])).toBe(true);
    expect(Object.values(unlocks.episodes).every(Boolean)).toBe(true);
  });

  it('persists mute through save reloads used by menu, level, and reload navigation', () => {
    const storage = createMemoryStorage();
    const firstPersistence = createPersistence({ storage, warn: vi.fn() });

    const mutedSave = firstPersistence.setMute(true);
    const reloadedSave = createPersistence({ storage, warn: vi.fn() }).loadSave();

    expect(mutedSave.mute).toBe(true);
    expect(reloadedSave.mute).toBe(true);
  });

  it('keeps 1-01 clear progress visible when the same save is rendered at mobile level-select', () => {
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
    const cards = buildLevelSelectCards(1, save, unlocks);
    const firstLevel = cards.find((card) => card.levelId === '1-01');
    const secondLevel = cards.find((card) => card.levelId === '1-02');

    expect(secondLevel).toMatchObject({
      unlocked: true,
      canStart: true
    });
    expect(firstLevel).toMatchObject({
      cleared: true,
      bestScore: 25000,
      bestScoreText: 'Best 25,000',
      bestStarsText: '2/3'
    });
  });

  it('suspends active sounds on pause and resumes through the mute state only on resume', () => {
    const pauseAll = vi.fn();
    const resumeAll = vi.fn();
    const stopAll = vi.fn();
    const setMute = vi.fn();
    const game = {
      sound: {
        pauseAll,
        resumeAll,
        stopAll,
        setMute
      },
      audioState: {
        muted: false
      }
    };

    expect(Game.prototype.suspendActiveAudio.call(game)).toBe(true);
    Game.prototype.setMute.call({
      ...game,
      persistence: { setMute: vi.fn(() => ({ mute: true })) },
      events: { emit: vi.fn() },
      refreshDebug: vi.fn(),
      applySoundMute: Game.prototype.applySoundMute
    }, true);
    expect(Game.prototype.resumeActiveAudio.call(game)).toBe(true);
    expect(Game.prototype.stopActiveAudio.call(game)).toBe(true);

    expect(pauseAll).toHaveBeenCalledTimes(1);
    expect(setMute).toHaveBeenCalledWith(true);
    expect(resumeAll).toHaveBeenCalledTimes(1);
    expect(stopAll).toHaveBeenCalledTimes(1);
  });

  it('forces the WebAudio master gain when Phaser leaves the global mute value stale', () => {
    const gain = {
      value: 1,
      cancelScheduledValues: vi.fn(),
      setValueAtTime: vi.fn()
    };
    const soundManager = {
      context: { currentTime: 12.5 },
      get mute() {
        return gain.value === 0;
      },
      set mute(_value) {
        // Mirrors the browser-observed Phaser path where the setter is called
        // but the AudioParam value remains unchanged.
      },
      setMute(value) {
        this.mute = value;
      },
      masterMuteNode: { gain }
    };

    expect(setGlobalSoundMute(soundManager, true)).toBe(true);
    expect(gain.cancelScheduledValues).toHaveBeenCalledWith(12.5);
    expect(gain.setValueAtTime).toHaveBeenCalledWith(0, 12.5);
    expect(gain.value).toBe(0);

    expect(setGlobalSoundMute(soundManager, false)).toBe(true);
    expect(gain.setValueAtTime).toHaveBeenLastCalledWith(1, 12.5);
    expect(gain.value).toBe(1);
  });
});
