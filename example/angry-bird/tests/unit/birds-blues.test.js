import { describe, expect, it, vi } from 'vitest';

vi.mock('phaser', () => ({
  default: {
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

import { BluesBird } from '../../src/entities/Bird.js';
import Slingshot from '../../src/entities/Slingshot.js';
import { BIRD_MATERIAL_AFFINITY } from '../../src/constants/materials.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';
import { calculateCollisionDamage } from '../../src/systems/physics.js';

function makeChainableGameObject(x = 0, y = 0) {
  const body = {
    velocity: { x: 0, y: 0 },
    position: { x, y }
  };
  const gameObject = {
    body,
    x,
    y,
    destroyed: false,
    data: new Map(),
    setCircle: vi.fn((radius) => {
      gameObject.circleRadius = radius;
      return gameObject;
    }),
    setDisplaySize: vi.fn((width, height) => {
      gameObject.displaySize = { width, height };
      return gameObject;
    }),
    setDepth: vi.fn(() => gameObject),
    setFriction: vi.fn(() => gameObject),
    setFrictionAir: vi.fn(() => gameObject),
    setBounce: vi.fn(() => gameObject),
    setDensity: vi.fn(() => gameObject),
    setIgnoreGravity: vi.fn(() => gameObject),
    setStatic: vi.fn(() => gameObject),
    setData: vi.fn((key, value) => {
      gameObject.data.set(key, value);
      return gameObject;
    }),
    getData: vi.fn((key) => gameObject.data.get(key)),
    setPosition: vi.fn((nextX, nextY) => {
      gameObject.x = nextX;
      gameObject.y = nextY;
      body.position = { x: nextX, y: nextY };
      return gameObject;
    }),
    setVelocity: vi.fn((xVelocity, yVelocity) => {
      body.velocity = { x: xVelocity, y: yVelocity };
      return gameObject;
    }),
    setAngularVelocity: vi.fn(() => gameObject),
    destroy: vi.fn(() => {
      gameObject.destroyed = true;
    })
  };

  return gameObject;
}

function makeScene() {
  const created = [];

  return {
    created,
    matter: {
      add: {
        image: vi.fn((x, y) => {
          const gameObject = makeChainableGameObject(x, y);
          created.push(gameObject);
          return gameObject;
        })
      }
    },
    physicsSystem: {
      registerBird: vi.fn()
    }
  };
}

describe('Blues bird split ability', () => {
  it('replaces the parent with three smaller Blues bodies at the parent position', () => {
    const scene = makeScene();
    const bird = new BluesBird(scene, 100, 200);

    bird.launch({ x: 12, y: -4 });
    bird.gameObject.setPosition(320, 240);
    bird.gameObject.setVelocity(14, -2);

    const preSplit = bird.getDebugState();
    const result = bird.tryFireAbility();
    const postSplit = bird.getDebugState();

    expect(preSplit).toMatchObject({
      type: 'blues',
      bodyCount: 1,
      radius: 18
    });
    expect(result).toMatchObject({
      fired: true,
      result: {
        audioEvent: 'sfx-blues-split',
        bodyCount: 3
      }
    });
    expect(scene.created[0].destroy).toHaveBeenCalledTimes(1);
    expect(postSplit).toMatchObject({
      type: 'blues',
      bodyCount: 3,
      abilityFired: true,
      windowOpen: true
    });
    expect(postSplit.bodies.map((body) => body.role)).toEqual(['straight', 'up', 'down']);
    expect(postSplit.bodies.every((body) => body.radius < preSplit.radius)).toBe(true);
    expect(postSplit.bodies.map((body) => ({ x: body.x, y: body.y }))).toEqual([
      { x: 320, y: 240 },
      { x: 320, y: 240 },
      { x: 320, y: 240 }
    ]);
    expect(postSplit.bodies[0].velocity).toMatchObject({ x: 14, y: -2 });
    expect(postSplit.bodies[1].velocity.y).toBeLessThan(postSplit.bodies[0].velocity.y);
    expect(postSplit.bodies[2].velocity.y).toBeGreaterThan(postSplit.bodies[0].velocity.y);
    expect(scene.physicsSystem.registerBird).toHaveBeenCalledTimes(4);
  });

  it('routes split taps through Slingshot and records the Blues ability audio event', () => {
    const scene = {
      isSlingshotPaused: () => false,
      audioState: { lastAbilityEvent: null },
      recordAbilityEvent: vi.fn((eventName) => {
        scene.audioState.lastAbilityEvent = eventName;
      }),
      refreshDebug: vi.fn()
    };
    const bird = new BluesBird(makeScene(), 100, 200);

    bird.launch({ x: 10, y: -3 });
    const result = Slingshot.prototype.handleAbilityTap.call({
      scene,
      flyingBird: bird
    }, { x: 400, y: 300 }, { id: 1 });

    expect(result.fired).toBe(true);
    expect(scene.recordAbilityEvent).toHaveBeenCalledWith('sfx-blues-split');
    expect(scene.audioState.lastAbilityEvent).toBe('sfx-blues-split');
  });

  it('keeps split available after a graze but blocks it after a meaningful collision', () => {
    const grazed = new BluesBird(makeScene(), 100, 200);
    grazed.launch({ x: 10, y: -3 });
    grazed.recordCollision({ hpLoss: 0, preSpeed: 12, postSpeed: 8 });

    expect(grazed.tryFireAbility().fired).toBe(true);
    expect(grazed.getDebugState().bodyCount).toBe(3);

    const collided = new BluesBird(makeScene(), 100, 200);
    collided.launch({ x: 10, y: -3 });
    collided.recordCollision({ hpLoss: 1, preSpeed: 12, postSpeed: 11 });

    expect(collided.tryFireAbility()).toMatchObject({
      fired: false,
      reason: 'window-closed'
    });
    expect(collided.getDebugState()).toMatchObject({
      bodyCount: 1,
      abilityFired: false,
      windowOpen: false
    });
  });

  it('keeps Blues glass damage at least five times stone damage', () => {
    const impact = 10;
    const glassDamage = calculateCollisionDamage({
      relativeImpulseMagnitude: impact,
      birdType: 'blues',
      material: 'glass'
    });
    const stoneDamage = calculateCollisionDamage({
      relativeImpulseMagnitude: impact,
      birdType: 'blues',
      material: 'stone'
    });

    expect(BIRD_MATERIAL_AFFINITY.blues.glass).toBeGreaterThanOrEqual(
      BIRD_MATERIAL_AFFINITY.blues.stone * 5
    );
    expect(glassDamage).toBeGreaterThanOrEqual(stoneDamage * 5);
  });

  it('loads unauthored level 1-05 with a five-Blues queue for manual split validation', () => {
    const level = loadLevelConfig('1-05');

    expect(level.id).toBe('1-05');
    expect(level.cameraWide).toBe(true);
    expect(level.queue.map((entry) => entry.type)).toEqual([
      'blues',
      'blues',
      'blues',
      'blues',
      'blues'
    ]);
  });
});
