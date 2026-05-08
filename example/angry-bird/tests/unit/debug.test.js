import { describe, expect, it } from 'vitest';

import {
  DEFAULT_SCENE_KEYS,
  registerDebugScene,
  resolveDebugEnabled
} from '../../src/systems/debug.js';

function fakeScene(key, sceneKeys = DEFAULT_SCENE_KEYS) {
  return {
    sys: {
      settings: { key },
      game: {
        scene: {
          keys: Object.fromEntries(sceneKeys.map((sceneKey) => [sceneKey, {}]))
        }
      }
    },
    scene: { key },
    add: {
      container() {
        return {
          setDepth() {
            return this;
          },
          setName() {
            return this;
          },
          add() {
            return this;
          }
        };
      },
      rectangle() {
        return {};
      },
      text() {
        return {};
      }
    }
  };
}

describe('debug hook registration', () => {
  it('stays disabled unless ANGRY_BIRD_DEV is truthy', () => {
    expect(resolveDebugEnabled({})).toBe(false);
    expect(resolveDebugEnabled({ ANGRY_BIRD_DEV: '' })).toBe(false);
    expect(resolveDebugEnabled({ ANGRY_BIRD_DEV: '1' })).toBe(true);
  });

  it('populates the expected __GAME__ shape and preserves scene history', () => {
    const target = {};
    const env = { ANGRY_BIRD_DEV: '1' };

    registerDebugScene(fakeScene('Boot'), {}, { env, target });
    const state = registerDebugScene(fakeScene('Preloader'), {
      score: 1200,
      birdsLeft: 3,
      pigsLeft: 1,
      settled: true,
      mute: true,
      queue: ['red', 'blues'],
      flyingBird: { type: 'red' },
      threeStarThreshold: { '1-01': 33000 },
      slingshot: { clampRadius: 120, anchor: { x: 212, y: 548 } }
    }, { env, target });

    expect(state).toBe(target.__GAME__);
    expect(target.__GAME__).toMatchObject({
      scene: {
        key: 'Preloader',
        score: 1200,
        birdsLeft: 3,
        pigsLeft: 1,
        settled: true,
        queue: ['red', 'blues'],
        flyingBird: { type: 'red' },
        threeStarThreshold: { '1-01': 33000 }
      },
      score: 1200,
      birdsLeft: 3,
      pigsLeft: 1,
      settled: true,
      mute: true,
      audio: {
        lastEvent: null,
        lastAbilityEvent: null,
        muted: true,
        recentEvents: []
      },
      save: {
        schemaVersion: 1,
        cleared: [],
        bestScore: {},
        bestStars: {},
        mute: true
      },
      debug: {
        sceneHistory: ['Boot', 'Preloader'],
        sceneKeys: DEFAULT_SCENE_KEYS,
        slingshot: { clampRadius: 120, anchor: { x: 212, y: 548 } }
      }
    });
    expect(typeof target.__GAME__.debug.showRoster).toBe('function');
  });

  it('does not create a global hook when disabled', () => {
    const target = {};

    const state = registerDebugScene(fakeScene('Boot'), {}, {
      env: {},
      target
    });

    expect(state).toBeNull();
    expect(target.__GAME__).toBeUndefined();
  });
});
