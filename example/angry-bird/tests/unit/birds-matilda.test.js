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
  MatildaBird,
  MATILDA_EGG_DROP
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
    destroy: vi.fn(() => {
      gameObject.destroyed = true;
    })
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
      registerBird: vi.fn(),
      registerMatildaEgg: vi.fn(),
      onMatildaEggExploded: vi.fn()
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
        setPosition: vi.fn().mockReturnThis(),
        setAlpha: vi.fn().mockReturnThis(),
        setVisible: vi.fn().mockReturnThis(),
        setActive: vi.fn().mockReturnThis(),
        setDepth: vi.fn().mockReturnThis(),
        setScale: vi.fn().mockReturnThis(),
        setRotation: vi.fn().mockReturnThis(),
        destroy: vi.fn()
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

function makeGroundBody() {
  return {
    label: 'ground',
    velocity: { x: 0, y: 0 },
    gameObject: null
  };
}

describe('Matilda egg drop and redirect ability', () => {
  it('spawns a falling egg below Matilda and redirects her upward exactly once', () => {
    const scene = makeBirdScene();
    const bird = new MatildaBird(scene, 100, 200);

    bird.launch({ x: 8, y: 5 });
    bird.gameObject.setPosition(320, 240);
    bird.gameObject.setVelocity(12, 6);

    const result = bird.tryFireAbility();
    const after = bird.getVelocity();
    const egg = bird.activeEgg;

    expect(result).toMatchObject({
      fired: true,
      result: {
        audioEvent: 'sfx-matilda-egg-drop',
        egg: {
          x: 320,
          y: 240 + MATILDA_EGG_DROP.spawnYOffset,
          radius: MATILDA_EGG_DROP.eggRadius,
          exploded: false
        }
      }
    });
    expect(after.y).toBe(MATILDA_EGG_DROP.redirectVy);
    expect(after.y).toBeLessThan(0);
    expect(after.x).toBe(12);
    expect(egg.getVelocity()).toMatchObject({ x: 0, y: 0, speed: 0 });
    expect(scene.physicsSystem.registerMatildaEgg).toHaveBeenCalledWith(egg);

    const second = bird.tryFireAbility();
    expect(second).toMatchObject({
      fired: false,
      reason: 'already-fired'
    });
    expect(scene.physicsSystem.registerMatildaEgg).toHaveBeenCalledTimes(1);
  });

  it('routes Matilda ability taps through Slingshot and records the egg-drop audio event', () => {
    const scene = {
      isSlingshotPaused: () => false,
      audioState: { lastAbilityEvent: null },
      recordAbilityEvent: vi.fn((eventName) => {
        scene.audioState.lastAbilityEvent = eventName;
      }),
      refreshDebug: vi.fn()
    };
    const bird = new MatildaBird(makeBirdScene(), 100, 200);

    bird.launch({ x: 10, y: -3 });
    const result = Slingshot.prototype.handleAbilityTap.call({
      scene,
      flyingBird: bird
    }, { x: 400, y: 300 }, { id: 1 });

    expect(result.fired).toBe(true);
    expect(scene.recordAbilityEvent).toHaveBeenCalledWith('sfx-matilda-egg-drop');
    expect(scene.audioState.lastAbilityEvent).toBe('sfx-matilda-egg-drop');
  });

  it('explodes the egg on first non-parent non-slingshot solid contact', () => {
    const scene = makeBirdScene();
    const bird = new MatildaBird(scene, 100, 200);

    bird.launch({ x: 10, y: -3 });
    bird.tryFireAbility();
    const egg = bird.activeEgg;

    expect(egg.explode({ contactBody: bird.body })).toMatchObject({
      exploded: false,
      reason: 'excluded-contact'
    });
    expect(egg.explode({ contactBody: { collisionFilter: { category: 0x0020 } } })).toMatchObject({
      exploded: false,
      reason: 'excluded-contact'
    });

    const result = egg.explode({ contactBody: makeGroundBody() });

    expect(result).toMatchObject({
      exploded: true,
      reason: 'contact',
      contactKind: 'ground'
    });
    expect(scene.physicsSystem.onMatildaEggExploded).toHaveBeenCalledWith(egg, {
      contactBody: expect.any(Object),
      contactEntity: null,
      reason: 'contact'
    });
    expect(egg.gameObject.destroy).toHaveBeenCalledTimes(1);

    const second = egg.explode({ contactBody: makeGroundBody() });
    expect(second).toMatchObject({
      exploded: false,
      reason: 'already-exploded'
    });
  });
});

describe('Matilda block contact', () => {
  it('destroys any block material and drops Matilda to at most 10% pre-collision speed', () => {
    const physicsScene = makePhysicsScene();
    const physics = new PhysicsSystem(physicsScene);
    const bird = new MatildaBird(makeBirdScene(), 100, 200);

    ['wood', 'glass', 'stone'].forEach((material) => {
      const block = makeBlock(material, 80);

      bird.launch({ x: 20, y: 0 });
      physics.bodySpeedSnapshots.set(bird.body, 20);
      physics.handleCollisionStart({
        pairs: [
          {
            bodyA: bird.body,
            bodyB: makeBlockBody(block)
          }
        ]
      });

      expect(block.destroyed).toBe(true);
      expect(MATILDA_EGG_DROP.blockContactSpeedLossFactor).toBeLessThanOrEqual(0.1);
      expect(bird.getVelocity().speed).toBeLessThanOrEqual(20 * 0.1);
      expect(physicsScene.lastMatildaBlockContact).toMatchObject({
        blocks: [
          {
            material,
            hpLoss: 80,
            destroyed: true
          }
        ],
        preSpeed: 20,
        speedRatio: expect.any(Number),
        speedLossFactor: MATILDA_EGG_DROP.blockContactSpeedLossFactor
      });
      expect(physicsScene.lastMatildaBlockContact.speedRatio).toBeLessThanOrEqual(0.1);
      expect(bird.lastAbilityCollision).toMatchObject({
        hpLoss: 80,
        meaningful: true
      });
    });
  });
});
