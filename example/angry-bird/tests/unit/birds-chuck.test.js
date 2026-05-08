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
  CHUCK_SPEED_BURST,
  ChuckBird
} from '../../src/entities/Bird.js';
import Slingshot from '../../src/entities/Slingshot.js';
import { PhysicsSystem } from '../../src/systems/physics.js';

function makeChainableGameObject(x = 0, y = 0) {
  const body = {
    velocity: { x: 0, y: 0 },
    position: { x, y }
  };
  const gameObject = {
    body,
    x,
    y,
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
    setAngularVelocity: vi.fn(() => gameObject),
    destroy: vi.fn()
  };

  body.gameObject = gameObject;
  return gameObject;
}

function makeBirdScene() {
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

function makePhysicsScene() {
  return {
    matter: {
      world: {
        localWorld: { bodies: [] },
        setGravity: vi.fn(),
        setBounds: vi.fn(),
        on: vi.fn(),
        off: vi.fn()
      }
    },
    events: {
      once: vi.fn()
    },
    add: {
      image: vi.fn(() => ({
        setVisible: vi.fn().mockReturnThis(),
        setActive: vi.fn().mockReturnThis(),
        setDepth: vi.fn().mockReturnThis(),
        setScale: vi.fn().mockReturnThis()
      }))
    },
    tweens: {
      add: vi.fn()
    },
    recordAudioEvent: vi.fn(),
    addScore: vi.fn()
  };
}

function makeBlock(material, hp) {
  const block = {
    kind: 'block',
    material,
    hp,
    destroyed: false,
    takeDamage: vi.fn((damage) => {
      block.hp = Math.max(0, block.hp - Math.max(0, damage));
      block.destroyed = block.hp <= 0;
      return block;
    })
  };

  return block;
}

function makeBlockBody(block, velocity = { x: 0, y: 0 }) {
  return {
    velocity,
    gameObject: {
      getData: vi.fn((key) => (key === 'physicsEntity' ? block : null))
    }
  };
}

describe('Chuck bird speed burst', () => {
  it('multiplies current speed by at least 2x along the current heading exactly once', () => {
    const bird = new ChuckBird(makeBirdScene(), 100, 200);

    bird.launch({ x: 8, y: -6 });
    const before = bird.getVelocity();
    const result = bird.tryFireAbility();
    const after = bird.getVelocity();

    expect(result).toMatchObject({
      fired: true,
      result: {
        audioEvent: 'sfx-chuck-burst',
        multiplier: CHUCK_SPEED_BURST.multiplier
      }
    });
    expect(CHUCK_SPEED_BURST.multiplier).toBeGreaterThanOrEqual(2);
    expect(after.speed).toBeGreaterThanOrEqual(before.speed * 2);
    expect(after.x / after.speed).toBeCloseTo(before.x / before.speed, 6);
    expect(after.y / after.speed).toBeCloseTo(before.y / before.speed, 6);

    const speedAfterFirstTap = after.speed;
    const second = bird.tryFireAbility();

    expect(second).toMatchObject({
      fired: false,
      reason: 'already-fired'
    });
    expect(bird.getVelocity().speed).toBeCloseTo(speedAfterFirstTap, 6);
  });

  it('routes burst taps through Slingshot and records the Chuck ability audio event', () => {
    const scene = {
      isSlingshotPaused: () => false,
      audioState: { lastAbilityEvent: null },
      recordAbilityEvent: vi.fn((eventName) => {
        scene.audioState.lastAbilityEvent = eventName;
      }),
      refreshDebug: vi.fn()
    };
    const bird = new ChuckBird(makeBirdScene(), 100, 200);

    bird.launch({ x: 10, y: -3 });
    const result = Slingshot.prototype.handleAbilityTap.call({
      scene,
      flyingBird: bird
    }, { x: 400, y: 300 }, { id: 1 });

    expect(result.fired).toBe(true);
    expect(scene.recordAbilityEvent).toHaveBeenCalledWith('sfx-chuck-burst');
    expect(scene.audioState.lastAbilityEvent).toBe('sfx-chuck-burst');
  });
});

describe('Chuck glass speed loss', () => {
  it('drops Chuck to at most 10% pre-collision speed when he destroys glass', () => {
    const physicsScene = makePhysicsScene();
    const physics = new PhysicsSystem(physicsScene);
    const bird = new ChuckBird(makeBirdScene(), 100, 200);
    const glass = makeBlock('glass', 4);

    bird.launch({ x: 20, y: 0 });
    physics.bodySpeedSnapshots.set(bird.body, 20);
    physics.handleCollisionStart({
      pairs: [
        {
          bodyA: bird.body,
          bodyB: makeBlockBody(glass)
        }
      ]
    });

    expect(glass.destroyed).toBe(true);
    expect(CHUCK_SPEED_BURST.glassSpeedLossFactor).toBeLessThanOrEqual(0.1);
    expect(bird.getVelocity().speed).toBeLessThanOrEqual(20 * 0.1);
    expect(bird.lastAbilityCollision).toMatchObject({
      hpLoss: 4,
      meaningful: true
    });
  });

  it('does not apply the glass break speed loss while the glass block survives', () => {
    const physicsScene = makePhysicsScene();
    const physics = new PhysicsSystem(physicsScene);
    const bird = new ChuckBird(makeBirdScene(), 100, 200);
    const glass = makeBlock('glass', 12);

    bird.launch({ x: 10, y: 0 });
    physics.bodySpeedSnapshots.set(bird.body, 10);
    physics.handleCollisionStart({
      pairs: [
        {
          bodyA: bird.body,
          bodyB: makeBlockBody(glass)
        }
      ]
    });

    expect(glass.destroyed).toBe(false);
    expect(bird.getVelocity().speed).toBeCloseTo(10, 6);
  });
});
