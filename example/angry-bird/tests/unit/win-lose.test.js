import { describe, expect, it, vi } from 'vitest';

import { END_STATE_SFX, GAMEPLAY_SFX_VOLUME, PHYSICS_SFX, SLINGSHOT_SFX } from '../../src/constants/audio.js';
import { SCORING_POINTS } from '../../src/constants/scoring.js';
import { resolveSlingshotLevelConfig } from '../../src/constants/slingshot.js';
import Game from '../../src/scenes/Game.js';
import { createFreshScoringSave, recordLevelClear } from '../../src/systems/scoring.js';
import {
  buildClearResult,
  getClearedCardActions,
  getFailedCardActions,
  getNextLevelId,
  isEpisodeUnlocked,
  resolveLevelOutcome
} from '../../src/systems/winLose.js';

vi.mock('phaser', () => ({
  default: {
    Scene: class Scene {
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

describe('win/lose outcome resolution', () => {
  it('waits for settle before showing a win or loss', () => {
    expect(resolveLevelOutcome({
      settled: false,
      pigsLeft: 0,
      birdsLeft: 0
    })).toBeNull();

    expect(resolveLevelOutcome({
      settled: false,
      pigsLeft: 1,
      birdsLeft: 0
    })).toBeNull();
  });

  it('gives win precedence over loss once settled', () => {
    expect(resolveLevelOutcome({
      settled: true,
      pigsLeft: 0,
      birdsLeft: 0
    })).toBe('cleared');
  });

  it('fails only when settled, birds are spent, and pigs remain', () => {
    expect(resolveLevelOutcome({
      settled: true,
      pigsLeft: 1,
      birdsLeft: 0
    })).toBe('failed');

    expect(resolveLevelOutcome({
      settled: true,
      pigsLeft: 1,
      birdsLeft: 2
    })).toBeNull();
  });
});

function createEndCheckScene({
  settled = false,
  pigsLeft = 1,
  birdsLeft = 0
} = {}) {
  const scene = new Game();

  scene.settled = settled;
  scene.pigsLeft = pigsLeft;
  scene.birdsLeft = birdsLeft;
  scene.levelEnded = false;
  scene.endCard = null;
  scene.physicsSystem = null;
  scene.slingshot = {
    getQueueDebug: () => Array.from({ length: birdsLeft }, () => ({ type: 'red' }))
  };
  scene.refreshDebug = () => {};
  scene.showClearedCard = function showClearedCard() {
    this.levelEnded = true;
    this.endCard = { outcome: 'cleared' };
  };
  scene.showFailedCard = function showFailedCard() {
    this.levelEnded = true;
    this.endCard = { outcome: 'failed' };
  };

  return scene;
}

describe('Game scene settle-gated end cards', () => {
  it('does not show the cleared card when the last pig is defeated before settle', () => {
    const scene = createEndCheckScene({
      settled: false,
      pigsLeft: 1,
      birdsLeft: 0
    });

    scene.handlePigDefeated({ reason: 'collision', pigsLeft: 0 });

    expect(scene.settled).toBe(false);
    expect(scene.endCard).toBeNull();
    expect(scene.levelEnded).toBe(false);
  });

  it('shows the cleared card when settle fires after the last pig defeat', () => {
    const scene = createEndCheckScene({
      settled: false,
      pigsLeft: 1,
      birdsLeft: 0
    });

    scene.handlePigDefeated({ reason: 'collision', pigsLeft: 0 });
    scene.settled = true;

    expect(scene.evaluateLevelEnd()).toBe('cleared');
    expect(scene.endCard).toEqual({ outcome: 'cleared' });
  });
});

describe('Game scene audio debug events', () => {
  it('records the loaded slingshot release key before bird flight SFX on launch', () => {
    const scene = new Game();
    const bird = {
      getDebugState: vi.fn(() => ({ type: 'red', canDrag: false })),
      getFlightAudioEvent: vi.fn(() => 'sfx-bird-red-cry')
    };

    scene.birdsLaunched = 0;
    scene.time = { now: 1000 };
    scene.physicsSystem = { markLaunched: vi.fn() };
    scene.recordAudioEvent = vi.fn();
    scene.refreshDebug = vi.fn();

    scene.handleBirdLaunched(bird, { type: 'red' });

    expect(scene.recordAudioEvent).toHaveBeenNthCalledWith(1, SLINGSHOT_SFX.release);
    expect(scene.recordAudioEvent).toHaveBeenNthCalledWith(2, 'sfx-bird-red-cry');
    expect(scene.physicsSystem.markLaunched).toHaveBeenCalledWith(1000);
  });

  it('records recent audio events with validation-contract keys', () => {
    const scene = new Game();

    scene.time = { now: 1234 };
    scene.audioState = {
      lastEvent: null,
      lastAbilityEvent: null,
      muted: false,
      recentEvents: []
    };

    scene.recordAudioEvent(PHYSICS_SFX.pigPop);

    expect(scene.audioState.lastEvent).toBe(PHYSICS_SFX.pigPop);
    expect(scene.audioState.lastAbilityEvent).toBeNull();
    expect(scene.audioState.recentEvents).toEqual([
      { key: PHYSICS_SFX.pigPop, t: 1234 }
    ]);
  });

  it('plays loaded audio assets through Phaser sound while recording debug state', () => {
    const scene = new Game();

    scene.time = { now: 2468 };
    scene.audioState = {
      lastEvent: null,
      lastAbilityEvent: null,
      muted: false,
      recentEvents: []
    };
    scene.cache = {
      audio: {
        exists: vi.fn((key) => key === 'sfx-bird-chuck-zip')
      }
    };
    scene.sound = { play: vi.fn() };

    scene.recordAudioEvent('sfx-bird-chuck-zip');

    expect(scene.sound.play).toHaveBeenCalledWith('sfx-bird-chuck-zip', {
      volume: GAMEPLAY_SFX_VOLUME
    });
    expect(scene.audioState.recentEvents.at(-1)).toEqual({
      key: 'sfx-bird-chuck-zip',
      t: 2468
    });
  });

  it('records the win stinger before launching the cleared card', () => {
    const scene = new Game();

    scene.levelConfig = { id: '1-01' };
    scene.score = 5000;
    scene.save = createFreshScoringSave();
    scene.persistence = { replaceSave: vi.fn((save) => save) };
    scene.updateScoreHud = vi.fn();
    scene.recordAudioEvent = vi.fn();
    scene.refreshDebug = vi.fn();
    scene.pauseForEndCard = vi.fn();
    scene.scene = { launch: vi.fn(), pause: vi.fn() };
    scene.birdsLaunched = 1;
    scene.initialBirdCount = 2;

    scene.showClearedCard(1);

    expect(scene.recordAudioEvent).toHaveBeenCalledWith(END_STATE_SFX.cleared);
    expect(scene.scene.launch).toHaveBeenCalledWith('ClearedCard', expect.objectContaining({
      levelId: '1-01',
      finalScore: 15000
    }));
  });

  it('records the fail jingle before launching the failed card', () => {
    const scene = new Game();

    scene.levelConfig = { id: '1-01' };
    scene.score = 3000;
    scene.save = createFreshScoringSave();
    scene.pigsLeft = 1;
    scene.recordAudioEvent = vi.fn();
    scene.refreshDebug = vi.fn();
    scene.pauseForEndCard = vi.fn();
    scene.scene = { launch: vi.fn(), pause: vi.fn() };

    scene.showFailedCard();

    expect(scene.recordAudioEvent).toHaveBeenCalledWith(END_STATE_SFX.failed);
    expect(scene.scene.launch).toHaveBeenCalledWith('FailedCard', expect.objectContaining({
      levelId: '1-01',
      score: 3000,
      pigsLeft: 1
    }));
  });
});

describe('clear scoring and save mutation', () => {
  it('adds animated unused-bird bonus into the final score and save', () => {
    const result = buildClearResult({
      levelId: '1-01',
      baseScore: 5000,
      unusedBirdCount: 2,
      save: createFreshScoringSave()
    });

    expect(result.bonus).toBe(SCORING_POINTS.unusedBirdBonus * 2);
    expect(result.finalScore).toBe(25000);
    expect(result.save.bestScore['1-01']).toBe(25000);
  });

  it('awards at least one star for every clear regardless of score', () => {
    const result = buildClearResult({
      levelId: '1-01',
      baseScore: 0,
      unusedBirdCount: 0,
      save: createFreshScoringSave()
    });

    expect(result.stars).toBe(1);
    expect(result.save.bestStars['1-01']).toBe(1);
  });

  it('does not mutate save data for failed runs', () => {
    const saved = recordLevelClear(createFreshScoringSave(), {
      levelId: '1-01',
      score: 33000,
      stars: 3
    });

    expect(resolveLevelOutcome({
      settled: true,
      pigsLeft: 1,
      birdsLeft: 0
    })).toBe('failed');
    expect(saved.bestScore['1-01']).toBe(33000);
    expect(saved.bestStars['1-01']).toBe(3);
  });
});

describe('end-card actions', () => {
  it('preserves known level ids even before full level layouts exist', () => {
    expect(resolveSlingshotLevelConfig('1-05').id).toBe('1-05');
    expect(resolveSlingshotLevelConfig('3-05').id).toBe('3-05');
    expect(resolveSlingshotLevelConfig('missing').id).toBe('1-01');
  });

  it('shows next level for non-final episode levels', () => {
    expect(getNextLevelId('1-04')).toBe('1-05');
    expect(getClearedCardActions({
      levelId: '1-04',
      save: createFreshScoringSave()
    }).map((action) => action.label)).toEqual([
      'Replay',
      'Next Level',
      'Level Select'
    ]);
  });

  it('replaces next level with next episode on an unlocked episode finale', () => {
    const save = {
      ...createFreshScoringSave(),
      cleared: ['1-05']
    };

    expect(isEpisodeUnlocked(2, save)).toBe(true);
    expect(getClearedCardActions({
      levelId: '1-05',
      save
    }).map((action) => action.label)).toEqual([
      'Replay',
      'Next Episode',
      'Level Select'
    ]);
  });

  it('uses episode select when the next episode is still locked', () => {
    expect(getClearedCardActions({
      levelId: '2-05',
      save: createFreshScoringSave()
    }).map((action) => action.label)).toEqual([
      'Replay',
      'Episode Select',
      'Level Select'
    ]);
  });

  it('shows only replay and episode select on the final level of the game', () => {
    expect(getClearedCardActions({
      levelId: '3-05',
      save: createFreshScoringSave()
    }).map((action) => action.label)).toEqual([
      'Replay',
      'Episode Select'
    ]);
  });

  it('shows retry and level select on failure', () => {
    expect(getFailedCardActions('2-03').map((action) => action.label)).toEqual([
      'Retry',
      'Level Select'
    ]);
  });
});
