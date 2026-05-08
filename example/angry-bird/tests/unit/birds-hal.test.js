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

import {
  HAL_BOOMERANG,
  HalBird,
  RedBird
} from '../../src/entities/Bird.js';
import Slingshot from '../../src/entities/Slingshot.js';
import { BIRD_MATERIAL_AFFINITY } from '../../src/constants/materials.js';
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
    rotation: 0,
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
    setCollisionCategory: vi.fn(() => gameObject),
    setCollidesWith: vi.fn(() => gameObject),
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
    setAngularVelocity: vi.fn((angularVelocity) => {
      gameObject.angularVelocity = angularVelocity;
      return gameObject;
    }),
    setRotation: vi.fn((rotation) => {
      gameObject.rotation = rotation;
      return gameObject;
    }),
    destroy: vi.fn(() => {
      gameObject.destroyed = true;
    })
  };

  body.gameObject = gameObject;
  return gameObject;
}

function makeBirdScene(now = 0) {
  const created = [];

  return {
    created,
    time: { now },
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

describe('Hal boomerang ability', () => {
  it('reverses horizontal velocity and adds an upward impulse exactly once', () => {
    const bird = new HalBird(makeBirdScene(), 100, 200);

    bird.launch({ x: 8, y: -2 });
    bird.gameObject.setVelocity(12, 4);
    const before = bird.getVelocity();
    const result = bird.tryFireAbility();
    const after = bird.getVelocity();

    expect(result).toMatchObject({
      fired: true,
      result: {
        audioEvent: 'sfx-hal-boomerang',
        vxScale: HAL_BOOMERANG.vxScale,
        vyImpulse: HAL_BOOMERANG.vyImpulse
      }
    });
    expect(Math.sign(after.x)).toBe(-Math.sign(before.x));
    expect(after.x).toBeCloseTo(before.x * HAL_BOOMERANG.vxScale, 6);
    expect(after.y).toBeCloseTo(before.y + HAL_BOOMERANG.vyImpulse, 6);
    expect(after.y).toBeLessThan(before.y);

    const speedAfterFirstTap = bird.getVelocity();
    const second = bird.tryFireAbility();

    expect(second).toMatchObject({
      fired: false,
      reason: 'already-fired'
    });
    expect(bird.getVelocity()).toMatchObject(speedAfterFirstTap);
  });

  it('routes Hal taps through Slingshot and records the boomerang audio event', () => {
    const scene = {
      isSlingshotPaused: () => false,
      audioState: { lastAbilityEvent: null },
      recordAbilityEvent: vi.fn((eventName) => {
        scene.audioState.lastAbilityEvent = eventName;
      }),
      refreshDebug: vi.fn()
    };
    const bird = new HalBird(makeBirdScene(), 100, 200);

    bird.launch({ x: 10, y: -3 });
    const result = Slingshot.prototype.handleAbilityTap.call({
      scene,
      flyingBird: bird
    }, { x: 400, y: 300 }, { id: 1 });

    expect(result.fired).toBe(true);
    expect(scene.recordAbilityEvent).toHaveBeenCalledWith('sfx-hal-boomerang');
    expect(scene.audioState.lastAbilityEvent).toBe('sfx-hal-boomerang');
  });
});

describe('Hal flight tuning', () => {
  it('rotates at least 60 degrees over 0.5 seconds while airborne', () => {
    const scene = makeBirdScene(1000);
    const bird = new HalBird(scene, 100, 200);

    bird.launch({ x: 8, y: -4 });
    const before = bird.getDebugState().rotationRad;
    scene.time.now = 1500;
    bird.updateFlight(1500);
    const after = bird.getDebugState().rotationRad;

    expect(HAL_BOOMERANG.rotateRadPerSec * 0.5).toBeGreaterThanOrEqual(Math.PI / 3);
    expect(after - before).toBeGreaterThanOrEqual(Math.PI / 3);
    expect(bird.gameObject.setAngularVelocity).toHaveBeenLastCalledWith(
      HAL_BOOMERANG.rotateRadPerSec / 60
    );
  });

  it('launches with at least 1.30x Red horizontal travel at equal power', () => {
    const launchVelocity = { x: 12, y: -6 };
    const red = new RedBird(makeBirdScene(), 100, 200);
    const hal = new HalBird(makeBirdScene(), 100, 200);

    red.launch(launchVelocity);
    hal.launch(launchVelocity);

    expect(HAL_BOOMERANG.flightDistanceMultiplier).toBeGreaterThanOrEqual(1.3);
    expect(Math.abs(hal.getVelocity().x)).toBeGreaterThanOrEqual(
      Math.abs(red.getVelocity().x) * 1.3
    );
    expect(hal.getVelocity().y).toBeCloseTo(red.getVelocity().y, 6);
  });

  it('keeps Hal stone damage at no more than five percent of wood damage', () => {
    const impact = 20;
    const woodDamage = calculateCollisionDamage({
      relativeImpulseMagnitude: impact,
      birdType: 'hal',
      material: 'wood'
    });
    const stoneDamage = calculateCollisionDamage({
      relativeImpulseMagnitude: impact,
      birdType: 'hal',
      material: 'stone'
    });

    expect(BIRD_MATERIAL_AFFINITY.hal.stone).toBeLessThanOrEqual(
      BIRD_MATERIAL_AFFINITY.hal.wood * 0.05
    );
    expect(BIRD_MATERIAL_AFFINITY.hal.stone).toBe(HAL_BOOMERANG.stoneDamageRatio);
    expect(stoneDamage).toBeLessThanOrEqual(woodDamage * 0.05);
  });
});
