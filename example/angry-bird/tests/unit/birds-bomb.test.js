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
  BOMB_EXPLOSION,
  BombBird
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
    time: { now: 500 },
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
      onBombExploded: vi.fn()
    }
  };
}

function makePhysicsScene() {
  return {
    time: { now: 0 },
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
    recordAbilityEvent: vi.fn(),
    addScore: vi.fn()
  };
}

function makeBlock(material, hp, x = 0, y = 0) {
  const block = {
    kind: 'block',
    material,
    hp,
    destroyed: false,
    x,
    y,
    gameObject: makeChainableGameObject(x, y),
    takeDamage: vi.fn((damage) => {
      block.hp = Math.max(0, block.hp - Math.max(0, damage));
      block.destroyed = block.hp <= 0;
      return block;
    })
  };

  block.gameObject.setPosition(x, y);
  return block;
}

function makePig(hp, x = 0, y = 0) {
  const pig = {
    kind: 'pig',
    hp,
    defeated: false,
    x,
    y,
    gameObject: makeChainableGameObject(x, y),
    takeDamage: vi.fn((damage) => {
      pig.hp = Math.max(0, pig.hp - Math.max(0, damage));
      pig.defeated = pig.hp <= 0;
      return pig;
    })
  };

  pig.gameObject.setPosition(x, y);
  return pig;
}

function makeBlockBody(block, velocity = { x: 0, y: 0 }) {
  block.gameObject.body.velocity = velocity;

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

describe('Bomb tap explosion ability', () => {
  it('detonates immediately on tap, damages nearby targets, and removes the bird', () => {
    const physicsScene = makePhysicsScene();
    const physics = new PhysicsSystem(physicsScene);
    const bird = new BombBird(makeBirdScene(), 100, 200);
    const stone = makeBlock('stone', 80, 126, 200);
    const pig = makePig(10, 154, 200);

    bird.scene = physicsScene;
    physics.blocks.push(stone);
    physics.pigs.push(pig);
    bird.launch({ x: 8, y: 0 });
    bird.gameObject.setPosition(100, 200);

    const result = bird.tryFireAbility({ reason: 'tap' });

    expect(result).toMatchObject({
      fired: true,
      result: {
        exploded: true,
        reason: 'tap',
        audioEvent: 'sfx-bomb-fuse-explode'
      }
    });
    expect(stone.destroyed).toBe(true);
    expect(pig.defeated).toBe(true);
    expect(stone.gameObject.body.velocity.x).toBeGreaterThan(0);
    expect(bird.exploded).toBe(true);
    expect(bird.gameObject.destroy).toHaveBeenCalledTimes(1);
    expect(physicsScene.recordAudioEvent).not.toHaveBeenCalled();
    expect(physicsScene.lastBombExplosion).toMatchObject({
      reason: 'tap',
      affectedBlocks: expect.arrayContaining([
        expect.objectContaining({ material: 'stone', destroyed: true })
      ]),
      affectedPigs: expect.arrayContaining([
        expect.objectContaining({ defeated: true })
      ])
    });
  });

  it('routes Bomb taps through Slingshot and records the ability audio event', () => {
    const scene = {
      isSlingshotPaused: () => false,
      audioState: { lastAbilityEvent: null },
      recordAbilityEvent: vi.fn((eventName) => {
        scene.audioState.lastAbilityEvent = eventName;
      }),
      refreshDebug: vi.fn()
    };
    const bird = new BombBird(makeBirdScene(), 100, 200);
    const slingshot = {
      scene,
      flyingBird: bird,
      resolveFlyingBird: vi.fn()
    };

    bird.launch({ x: 10, y: -3 });
    const result = Slingshot.prototype.handleAbilityTap.call(slingshot, { x: 400, y: 300 }, { id: 1 });

    expect(result.fired).toBe(true);
    expect(scene.recordAbilityEvent).toHaveBeenCalledWith('sfx-bomb-fuse-explode');
    expect(scene.audioState.lastAbilityEvent).toBe('sfx-bomb-fuse-explode');
    expect(slingshot.resolveFlyingBird).toHaveBeenCalledWith('bomb-tap-explosion');
  });
});

describe('Bomb post-collision auto explosion', () => {
  it('arms on the first solid collision and auto-explodes after 1.0s', () => {
    const physicsScene = makePhysicsScene();
    const physics = new PhysicsSystem(physicsScene);
    const bird = new BombBird(makeBirdScene(), 100, 200);

    bird.scene = physicsScene;
    bird.launch({ x: 12, y: 0 });
    physicsScene.time.now = 2000;
    physics.bodySpeedSnapshots.set(bird.body, 12);
    physics.handleCollisionStart({
      pairs: [
        {
          bodyA: bird.body,
          bodyB: makeGroundBody()
        }
      ]
    });

    expect(bird.exploded).toBe(false);
    expect(bird.autoExplosionDueAt).toBe(2000 + BOMB_EXPLOSION.autoDelayMs);
    expect(bird.updateFlight(2999)).toMatchObject({
      exploded: false,
      reason: 'auto-pending'
    });

    const result = bird.updateFlight(3000);

    expect(result).toMatchObject({
      exploded: true,
      reason: 'auto'
    });
    expect(physicsScene.lastBombExplosion).toMatchObject({
      reason: 'auto',
      delayMs: BOMB_EXPLOSION.autoDelayMs
    });
    expect(physicsScene.recordAudioEvent).toHaveBeenCalledWith('sfx-bomb-fuse-explode');
  });

  it('tap during the post-collision timer detonates immediately and later taps are silent', () => {
    const physicsScene = makePhysicsScene();
    const physics = new PhysicsSystem(physicsScene);
    const bird = new BombBird(makeBirdScene(), 100, 200);

    bird.scene = physicsScene;
    bird.launch({ x: 12, y: 0 });
    physicsScene.time.now = 4000;
    physics.bodySpeedSnapshots.set(bird.body, 12);
    physics.handleCollisionStart({
      pairs: [
        {
          bodyA: bird.body,
          bodyB: makeGroundBody()
        }
      ]
    });
    physicsScene.time.now = 4300;

    const result = bird.tryFireAbility({ reason: 'tap-during-auto-timer' });
    const after = bird.tryFireAbility({ reason: 'post-explosion-tap' });

    expect(result).toMatchObject({
      fired: true,
      result: {
        exploded: true,
        reason: 'tap-during-auto-timer'
      }
    });
    expect(physicsScene.lastBombExplosion).toMatchObject({
      reason: 'tap-during-auto-timer',
      elapsedSinceArmedMs: 300
    });
    expect(physicsScene.recordAudioEvent).not.toHaveBeenCalled();
    expect(after).toMatchObject({
      fired: false,
      reason: 'already-exploded'
    });
  });
});

describe('Bomb direct wood break speed loss', () => {
  it('drops Bomb to at most 10% pre-collision speed when he destroys wood without exploding', () => {
    const physicsScene = makePhysicsScene();
    const physics = new PhysicsSystem(physicsScene);
    const bird = new BombBird(makeBirdScene(), 100, 200);
    const wood = makeBlock('wood', 4);

    bird.launch({ x: 20, y: 0 });
    physics.bodySpeedSnapshots.set(bird.body, 20);
    physics.handleCollisionStart({
      pairs: [
        {
          bodyA: bird.body,
          bodyB: makeBlockBody(wood)
        }
      ]
    });

    expect(wood.destroyed).toBe(true);
    expect(BOMB_EXPLOSION.woodSpeedLossFactor).toBeLessThanOrEqual(0.1);
    expect(bird.getVelocity().speed).toBeLessThanOrEqual(20 * 0.1);
    expect(physicsScene.lastBombWoodContact).toMatchObject({
      material: 'wood',
      hpLoss: 4,
      destroyed: true,
      preSpeed: 20,
      speedLossFactor: BOMB_EXPLOSION.woodSpeedLossFactor
    });
  });
});
