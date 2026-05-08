import { describe, expect, it, vi } from 'vitest';

import { RedBird } from '../../src/entities/Bird.js';
import Slingshot from '../../src/entities/Slingshot.js';
import Game from '../../src/scenes/Game.js';

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
    },
    Math: {
      Clamp: (value, min, max) => Math.min(Math.max(value, min), max)
    }
  }
}));

function makeChainableGameObject() {
  const body = {
    velocity: { x: 0, y: 0 },
    position: { x: 0, y: 0 }
  };
  const gameObject = {
    body,
    x: 0,
    y: 0,
    setCircle: vi.fn(() => gameObject),
    setDisplaySize: vi.fn(() => gameObject),
    setDepth: vi.fn(() => gameObject),
    setFriction: vi.fn(() => gameObject),
    setFrictionAir: vi.fn(() => gameObject),
    setBounce: vi.fn(() => gameObject),
    setDensity: vi.fn(() => gameObject),
    setIgnoreGravity: vi.fn(() => gameObject),
    setStatic: vi.fn(() => gameObject),
    setData: vi.fn(() => gameObject),
    setPosition: vi.fn((x, y) => {
      gameObject.x = x;
      gameObject.y = y;
      body.position = { x, y };
      return gameObject;
    }),
    setVelocity: vi.fn((x, y) => {
      body.velocity = { x, y };
      return gameObject;
    }),
    setAngularVelocity: vi.fn(() => gameObject),
    destroy: vi.fn()
  };

  return gameObject;
}

function makeScene() {
  const gameObject = makeChainableGameObject();

  return {
    gameObject,
    matter: {
      add: {
        image: vi.fn(() => gameObject)
      }
    },
    physicsSystem: {
      registerBird: vi.fn()
    }
  };
}

function makeGameContext() {
  return {
    audioState: {
      lastEvent: null,
      lastAbilityEvent: null,
      muted: false,
      recentEvents: []
    },
    birdsLaunched: 0,
    time: { now: 1234 },
    physicsSystem: { markLaunched: vi.fn() },
    refreshDebug: vi.fn(),
    recordAudioEvent: Game.prototype.recordAudioEvent
  };
}

describe('Red bird baseline', () => {
  it('records Red flight cry as the launch audio event', () => {
    const game = makeGameContext();
    const bird = new RedBird(makeScene(), 10, 20);

    bird.launch({ x: 6, y: -4 });
    Game.prototype.handleBirdLaunched.call(game, bird, {
      type: 'red',
      velocity: bird.getVelocity()
    });

    expect(game.audioState.lastEvent).toBe('sfx-bird-red-cry');
    expect(game.audioState.lastAbilityEvent).toBeNull();
    expect(game.audioState.recentEvents.at(-1)).toEqual({
      key: 'sfx-bird-red-cry',
      t: 1234
    });
  });

  it('keeps Red tap silent and does not alter trajectory', () => {
    const scene = {
      isSlingshotPaused: () => false,
      audioState: {
        lastAbilityEvent: 'sfx-existing-ability'
      },
      recordAbilityEvent: vi.fn((eventName) => {
        scene.audioState.lastAbilityEvent = eventName;
      }),
      refreshDebug: vi.fn()
    };
    const bird = new RedBird(makeScene(), 10, 20);

    bird.launch({ x: 6, y: -4 });
    const beforeVelocity = bird.getVelocity();
    const beforeAbilityEvent = scene.audioState.lastAbilityEvent;
    const result = Slingshot.prototype.handleAbilityTap.call({
      scene,
      flyingBird: bird
    }, { x: 400, y: 300 }, { id: 1 });

    expect(result).toMatchObject({
      fired: false,
      reason: 'no-ability'
    });
    expect(bird.getVelocity()).toEqual(beforeVelocity);
    expect(scene.recordAbilityEvent).not.toHaveBeenCalled();
    expect(scene.audioState.lastAbilityEvent).toBe(beforeAbilityEvent);
  });
});
