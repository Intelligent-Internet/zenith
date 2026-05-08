import { describe, expect, it, vi } from 'vitest';

import { PHYSICS_SFX } from '../../src/constants/audio.js';
import {
  BLOCK_MATERIALS,
  BOULDER,
  TNT_EXPLOSION
} from '../../src/constants/materials.js';
import {
  PhysicsSystem,
  calculateBoulderPigDamage
} from '../../src/systems/physics.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';

function makeChainableGameObject() {
  const chain = {
    setVisible: vi.fn(() => chain),
    setActive: vi.fn(() => chain),
    setDepth: vi.fn(() => chain),
    setScale: vi.fn(() => chain),
    setPosition: vi.fn(() => chain),
    setAlpha: vi.fn(() => chain),
    setRotation: vi.fn(() => chain),
    destroy: vi.fn()
  };
  return chain;
}

function makeScene(now = 1000) {
  const delayedCalls = [];

  return {
    time: {
      now,
      delayedCall: vi.fn((delayMs, callback) => {
        delayedCalls.push({ delayMs, callback });
        return { remove: vi.fn() };
      })
    },
    matter: {
      world: {
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
      image: vi.fn(() => makeChainableGameObject())
    },
    tweens: {
      add: vi.fn(({ onComplete }) => {
        onComplete?.();
      })
    },
    addScore: vi.fn(),
    recordAudioEvent: vi.fn(),
    delayedCalls
  };
}

function makeBodyEntity({
  kind,
  x,
  y,
  hp = 1,
  material = null,
  tier = null
}) {
  const entity = {
    id: `${kind}-${x}-${y}`,
    kind,
    material,
    tier,
    hp,
    maxHp: hp,
    destroyed: false,
    defeated: false,
    gameObject: {
      body: {
        position: { x, y },
        velocity: { x: 0, y: 0 }
      },
      setVelocity: vi.fn(),
      destroy: vi.fn()
    },
    takeDamage: vi.fn((damage) => {
      entity.hp = Math.max(0, entity.hp - damage);
      if (entity.hp <= 0) {
        entity.destroyed = kind !== 'pig';
        entity.defeated = kind === 'pig';
      }
      return entity.getDebugState();
    }),
    defeat: vi.fn(() => {
      entity.defeated = true;
      entity.hp = 0;
    }),
    destroy: vi.fn(() => {
      entity.destroyed = true;
      entity.hp = 0;
    }),
    getDebugState: vi.fn(() => ({
      id: entity.id,
      kind: entity.kind,
      material: entity.material,
      tier: entity.tier,
      hp: entity.hp,
      destroyed: entity.destroyed,
      defeated: entity.defeated,
      x,
      y
    }))
  };

  return entity;
}

function makeTnt(x, y) {
  const tnt = makeBodyEntity({ kind: 'tnt', x, y });
  tnt.triggered = false;
  tnt.detonated = false;
  tnt.markTriggered = vi.fn((trigger) => {
    tnt.triggered = true;
    tnt.triggeredAtMs = trigger.triggeredAtMs;
    tnt.scheduledDetonationAtMs = trigger.scheduledDetonationAtMs;
  });
  tnt.markDetonated = vi.fn((timeMs) => {
    tnt.detonated = true;
    tnt.detonatedAtMs = timeMs;
  });
  return tnt;
}

describe('level 1-02 data', () => {
  it('defines Poached Eggs 1-3 hard invariants and boulder/TNT puzzle objects', () => {
    const level = loadLevelConfig('1-02');

    expect(level.id).toBe('1-02');
    expect(level.cameraWide).toBe(true);
    expect(level.levelWidth).toBeGreaterThan(1280);
    expect(level.slingshotElevated).toBe(false);
    expect(level.queue.map((entry) => entry.type)).toEqual(['red', 'red', 'red', 'red']);
    expect(level.pigs).toEqual([
      expect.objectContaining({ tier: 'small', isStatic: false })
    ]);
    expect(level.tntCrates).toEqual([
      expect.objectContaining({ width: 52, height: 52, isStatic: true })
    ]);
    expect(level.boulders).toEqual([
      expect.objectContaining({ hp: 200, isStatic: false })
    ]);
    expect(level.mounds).toHaveLength(1);
  });

  it('pins boulder and TNT constants to the validation contract', () => {
    expect(BOULDER.hp).toBe(200);
    expect(BOULDER.material).toBe('stone');
    expect(TNT_EXPLOSION.audioEvent).toBe(PHYSICS_SFX.tntExplosion);
    expect(TNT_EXPLOSION.radiusPx).toBeGreaterThanOrEqual(88);
    expect(TNT_EXPLOSION.chainDelayMs).toBeLessThanOrEqual(50);
    expect(TNT_EXPLOSION.blockDamage.wood).toBeGreaterThanOrEqual(BLOCK_MATERIALS.wood.hp);
    expect(TNT_EXPLOSION.blockDamage.glass).toBeGreaterThanOrEqual(BLOCK_MATERIALS.glass.hp);
    expect(TNT_EXPLOSION.blockDamage.stone).toBe(40);
  });
});

describe('level 1-02 TNT and boulder physics', () => {
  it('detonates TNT with audio, destroys nearby wood/glass, damages stone, defeats pigs, and chains TNT within 50 ms', () => {
    const scene = makeScene(2500);
    const physics = new PhysicsSystem(scene, { width: 1800, height: 720 });
    const sourceTnt = makeTnt(800, 540);
    const chainedTnt = makeTnt(870, 540);
    const wood = makeBodyEntity({
      kind: 'block',
      material: 'wood',
      x: 835,
      y: 540,
      hp: BLOCK_MATERIALS.wood.hp
    });
    const glass = makeBodyEntity({
      kind: 'block',
      material: 'glass',
      x: 770,
      y: 540,
      hp: BLOCK_MATERIALS.glass.hp
    });
    const stone = makeBodyEntity({
      kind: 'block',
      material: 'stone',
      x: 855,
      y: 540,
      hp: BLOCK_MATERIALS.stone.hp
    });
    const farWood = makeBodyEntity({
      kind: 'block',
      material: 'wood',
      x: 1200,
      y: 540,
      hp: BLOCK_MATERIALS.wood.hp
    });
    const nearPig = makeBodyEntity({
      kind: 'pig',
      tier: 'small',
      x: 805,
      y: 610,
      hp: 10
    });
    const farPig = makeBodyEntity({
      kind: 'pig',
      tier: 'small',
      x: 1200,
      y: 610,
      hp: 10
    });

    physics.tntCrates = [sourceTnt, chainedTnt];
    physics.blocks = [wood, glass, stone, farWood];
    physics.pigs = [nearPig, farPig];

    const result = physics.detonateTnt(sourceTnt, { reason: 'unit-test' });

    expect(scene.recordAudioEvent).toHaveBeenCalledWith(PHYSICS_SFX.tntExplosion);
    expect(sourceTnt.detonated).toBe(true);
    expect(wood.destroyed).toBe(true);
    expect(glass.destroyed).toBe(true);
    expect(stone.hp).toBe(BLOCK_MATERIALS.stone.hp - 40);
    expect(farWood.destroyed).toBe(false);
    expect(nearPig.defeated).toBe(true);
    expect(farPig.defeated).toBe(false);
    expect(chainedTnt.triggered).toBe(true);
    expect(chainedTnt.scheduledDetonationAtMs - sourceTnt.detonatedAtMs).toBeLessThanOrEqual(50);
    expect(scene.time.delayedCall).toHaveBeenCalledWith(expect.any(Number), expect.any(Function));
    expect(result.affectedPigs).toEqual([
      expect.objectContaining({ defeated: true })
    ]);
  });

  it('gives a rolling boulder enough collision damage to defeat the ground pig', () => {
    expect(calculateBoulderPigDamage({ relativeImpulseMagnitude: 3 })).toBeGreaterThanOrEqual(10);
  });
});
