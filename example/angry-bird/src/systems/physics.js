import {
  BIRD_MATERIAL_AFFINITY,
  BOULDER,
  BOMB_EXPLOSION,
  BLOCK_MATERIALS,
  ENVIRONMENT_MATERIAL_AFFINITY,
  MATILDA_EGG_EXPLOSION,
  PIG_PARTICLE,
  TNT_EXPLOSION
} from '../constants/materials.js';
import { PHYSICS_SFX } from '../constants/audio.js';

export const PHYSICS_CONFIG = {
  gravity: { x: 0, y: 1, scale: 0.00036 },
  settleSpeedPxPerSecond: 5,
  settleDurationMs: 500,
  settleTimeoutMs: 8000,
  offWorldCleanupMs: 2000,
  birdOffWorldCleanupMs: 1000,
  stuckBirdRestMs: 3000,
  stuckSpeedPxPerSecond: 5,
  minDamageImpulse: 3
};

export const COLLISION_CATEGORIES = {
  BIRD: 0x0001,
  PIG: 0x0002,
  BLOCK: 0x0004,
  TNT: 0x0008,
  GROUND: 0x0010,
  SLINGSHOT: 0x0020
};

const ALL_COLLIDABLE = Object.values(COLLISION_CATEGORIES);
const STRUCTURAL_COLLAPSE_MARGIN = 120;
const STRUCTURAL_COLLAPSE_HP_RATIO = 0.75;

export function applyCollisionCategory(gameObject, category, collidesWith = ALL_COLLIDABLE) {
  gameObject.setCollisionCategory?.(category);
  gameObject.setCollidesWith?.(collidesWith);
  return gameObject;
}

export function applyDamageToHp(currentHp, damage) {
  const remainingHp = Math.max(0, currentHp - Math.max(0, damage));

  return {
    remainingHp,
    destroyed: remainingHp <= 0
  };
}

export function calculateCollisionDamage({
  relativeImpulseMagnitude,
  birdType = 'environment',
  material
}) {
  const affinity = BIRD_MATERIAL_AFFINITY[birdType]?.[material]
    ?? ENVIRONMENT_MATERIAL_AFFINITY[material]
    ?? 0;

  return Math.max(0, relativeImpulseMagnitude) * affinity;
}

export function calculatePigDamage({
  relativeImpulseMagnitude,
  birdType = 'environment'
}) {
  if (birdType === 'boulder') {
    return calculateBoulderPigDamage({ relativeImpulseMagnitude });
  }

  const multiplier = birdType === 'environment' ? 0.5 : 1;

  return Math.max(0, relativeImpulseMagnitude) * multiplier;
}

export function calculateBoulderPigDamage({
  relativeImpulseMagnitude
}) {
  return Math.max(0, relativeImpulseMagnitude) * 4;
}

export function calculateStructuralCollapseRadius(entity = {}, pigRadius = 0) {
  const span = Math.max(
    Number(entity.width) || 0,
    Number(entity.height) || 0,
    (Number(entity.radius) || 0) * 2
  );

  return span * 0.55 + Math.max(0, Number(pigRadius) || 0) + STRUCTURAL_COLLAPSE_MARGIN;
}

export function crossesStructuralCollapseThreshold({
  previousHp,
  remainingHp,
  maxHp
}) {
  const threshold = Math.max(0, Number(maxHp) || 0) * STRUCTURAL_COLLAPSE_HP_RATIO;

  return Number(previousHp) > threshold && Number(remainingHp) <= threshold;
}

export class SettleStateMachine {
  constructor({
    speedThresholdPxPerSecond = PHYSICS_CONFIG.settleSpeedPxPerSecond,
    settleDurationMs = PHYSICS_CONFIG.settleDurationMs,
    timeoutMs = PHYSICS_CONFIG.settleTimeoutMs
  } = {}) {
    this.speedThresholdPxPerSecond = speedThresholdPxPerSecond;
    this.settleDurationMs = settleDurationMs;
    this.timeoutMs = timeoutMs;
    this.launchedAtMs = null;
    this.stillSinceMs = null;
    this.settled = true;
    this.reason = 'initial';
  }

  markLaunched(timeMs) {
    this.launchedAtMs = timeMs;
    this.stillSinceMs = null;
    this.settled = false;
    this.reason = null;
    return this.getState();
  }

  update(timeMs, speedsPxPerSecond = []) {
    if (this.settled) {
      return this.getState();
    }

    if (this.launchedAtMs !== null && timeMs - this.launchedAtMs >= this.timeoutMs) {
      return this.forceSettled('timeout', timeMs);
    }

    const allStill = speedsPxPerSecond.every((speed) => Math.abs(speed) < this.speedThresholdPxPerSecond);
    if (!allStill) {
      this.stillSinceMs = null;
      return this.getState();
    }

    this.stillSinceMs ??= timeMs;
    if (timeMs - this.stillSinceMs >= this.settleDurationMs) {
      return this.forceSettled('all-bodies-still', timeMs);
    }

    return this.getState();
  }

  forceSettled(reason, timeMs) {
    this.settled = true;
    this.reason = reason;
    this.settledAtMs = timeMs;
    return this.getState();
  }

  getState() {
    return {
      settled: this.settled,
      reason: this.reason,
      launchedAtMs: this.launchedAtMs,
      stillSinceMs: this.stillSinceMs,
      settledAtMs: this.settledAtMs ?? null
    };
  }
}

function normalizeWorldBounds({ width = 1280, height = 720 } = {}) {
  return {
    left: 0,
    top: 0,
    right: width,
    bottom: height,
    width,
    height
  };
}

function getBodyVelocity(body) {
  return body?.velocity ?? { x: 0, y: 0 };
}

function bodySpeed(body) {
  const velocity = getBodyVelocity(body);
  return Math.hypot(velocity.x, velocity.y);
}

function bodySpeedPxPerSecond(body) {
  return bodySpeed(body) * 60;
}

function relativeImpulseMagnitude(bodyA, bodyB) {
  const a = getBodyVelocity(bodyA);
  const b = getBodyVelocity(bodyB);

  return Math.hypot(a.x - b.x, a.y - b.y);
}

function getBodyEntity(body) {
  const bodies = [body, body?.parent].filter(Boolean);

  for (const candidate of bodies) {
    const gameObject = candidate.gameObject ?? candidate.plugin?.gameObject;
    const entity = gameObject?.getData?.('physicsEntity');
    if (entity) {
      return entity;
    }
  }

  return null;
}

function entityPosition(entity) {
  const position = entity?.gameObject?.body?.position;

  return {
    x: position?.x ?? entity?.x ?? 0,
    y: position?.y ?? entity?.y ?? 0
  };
}

function setEntityVelocity(entity, velocity) {
  if (typeof entity?.gameObject?.setVelocity === 'function') {
    entity.gameObject.setVelocity(velocity.x, velocity.y);
    return;
  }

  if (entity?.gameObject?.body?.velocity) {
    entity.gameObject.body.velocity = { x: velocity.x, y: velocity.y };
  }
}

function getEntityVelocity(entity) {
  return entity?.gameObject?.body?.velocity ?? { x: 0, y: 0 };
}

export function calculateBombExplosionFalloff(distance) {
  if (distance > BOMB_EXPLOSION.radiusPx) {
    return 0;
  }

  const linearFalloff = 1 - distance / BOMB_EXPLOSION.radiusPx;
  return BOMB_EXPLOSION.minDamageFalloff
    + (1 - BOMB_EXPLOSION.minDamageFalloff) * linearFalloff;
}

export function calculateTntExplosionFalloff(distance) {
  if (distance > TNT_EXPLOSION.radiusPx) {
    return 0;
  }

  return Math.max(0.35, 1 - distance / TNT_EXPLOSION.radiusPx);
}

function distanceBetween(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function getOtherBodyForEntity(pair, entity) {
  if (getBodyEntity(pair.bodyA) === entity) {
    return pair.bodyB;
  }

  if (getBodyEntity(pair.bodyB) === entity) {
    return pair.bodyA;
  }

  return null;
}

function getContactKind(contactBody, contactEntity) {
  if (contactEntity?.kind) {
    return contactEntity.kind;
  }

  if (contactBody?.label === 'ground') {
    return 'ground';
  }

  return contactBody ? 'solid' : null;
}

class BurstPool {
  constructor(scene, key, size = 64) {
    this.scene = scene;
    this.key = key;
    this.pool = Array.from({ length: size }, () => (
      scene.add.image(0, 0, key)
        .setVisible(false)
        .setActive(false)
        .setDepth(30)
        .setScale(0.35)
    ));
    this.nextIndex = 0;
  }

  explode(x, y, {
    count,
    lifespanMs,
    distance = 50
  }) {
    for (let index = 0; index < count; index += 1) {
      const sprite = this.pool[this.nextIndex];
      this.nextIndex = (this.nextIndex + 1) % this.pool.length;

      const angle = (Math.PI * 2 * index) / count;
      sprite.setPosition(x, y)
        .setAlpha(0.9)
        .setScale(0.35)
        .setRotation(angle)
        .setVisible(true)
        .setActive(true);

      this.scene.tweens.add({
        targets: sprite,
        x: x + Math.cos(angle) * distance,
        y: y + Math.sin(angle) * distance,
        alpha: 0,
        scale: 0.08,
        duration: lifespanMs,
        onComplete: () => {
          sprite.setVisible(false).setActive(false);
        }
      });
    }
  }

  destroy() {
    this.pool.forEach((sprite) => sprite.destroy());
  }
}

export class PhysicsSystem {
  constructor(scene, {
    width = 1280,
    height = 720,
    onSettledChange
  } = {}) {
    this.scene = scene;
    this.worldBounds = normalizeWorldBounds({ width, height });
    this.onSettledChange = onSettledChange;
    this.blocks = [];
    this.pigs = [];
    this.boulders = [];
    this.tntCrates = [];
    this.eggs = [];
    this.offWorldSince = new Map();
    this.settle = new SettleStateMachine();
    this.lastSettleState = this.settle.getState();
    this.particlePools = new Map();
    this.bodySpeedSnapshots = new WeakMap();
    this.scene.physicsSystem ??= this;

    this.configureMatterWorld();
    this.handleCollisionStart = this.handleCollisionStart.bind(this);
    scene.matter.world.on('collisionstart', this.handleCollisionStart);
    scene.events.once('shutdown', () => this.destroy());
  }

  configureMatterWorld() {
    const { width, height } = this.worldBounds;
    this.scene.matter.world.setGravity(
      PHYSICS_CONFIG.gravity.x,
      PHYSICS_CONFIG.gravity.y,
      PHYSICS_CONFIG.gravity.scale
    );
    this.scene.matter.world.setBounds(0, 0, width, height, 64, false, false, false, false);
  }

  registerBlock(block) {
    if (!this.blocks.includes(block)) {
      this.blocks.push(block);
    }
    applyCollisionCategory(block.gameObject, COLLISION_CATEGORIES.BLOCK);
  }

  registerBoulder(boulder) {
    if (!this.boulders.includes(boulder)) {
      this.boulders.push(boulder);
    }
    if (!this.blocks.includes(boulder)) {
      this.blocks.push(boulder);
    }
    applyCollisionCategory(boulder.gameObject, COLLISION_CATEGORIES.BLOCK);
  }

  registerPig(pig) {
    if (!this.pigs.includes(pig)) {
      this.pigs.push(pig);
    }
    applyCollisionCategory(pig.gameObject, COLLISION_CATEGORIES.PIG);
    this.updateScenePigCount();
  }

  registerBird(bird, gameObject = bird.gameObject) {
    applyCollisionCategory(gameObject, COLLISION_CATEGORIES.BIRD);
  }

  registerTnt(tnt) {
    if (!this.tntCrates.includes(tnt)) {
      this.tntCrates.push(tnt);
    }
    applyCollisionCategory(tnt.gameObject, COLLISION_CATEGORIES.TNT);
  }

  registerMatildaEgg(egg) {
    if (!this.eggs.includes(egg)) {
      this.eggs.push(egg);
    }
    applyCollisionCategory(egg.gameObject, COLLISION_CATEGORIES.BIRD, [
      COLLISION_CATEGORIES.PIG,
      COLLISION_CATEGORIES.BLOCK,
      COLLISION_CATEGORIES.TNT,
      COLLISION_CATEGORIES.GROUND
    ]);
  }

  markLaunched(timeMs) {
    this.lastSettleState = this.settle.markLaunched(timeMs);
    this.scene.settled = false;
    this.scene.lastSettleReason = null;
    this.snapshotDynamicBodySpeeds();
    this.onSettledChange?.(this.lastSettleState);
  }

  update(timeMs) {
    this.cleanupOffWorldEntities(timeMs);
    const speeds = this.getDynamicBodies().map((body) => bodySpeedPxPerSecond(body));
    const state = this.settle.update(timeMs, speeds);

    if (state !== this.lastSettleState || state.settled !== this.scene.settled) {
      this.lastSettleState = state;
      this.scene.settled = state.settled;
      this.scene.lastSettleReason = state.reason;
      this.onSettledChange?.(state);
    }

    this.snapshotDynamicBodySpeeds();
  }

  getDynamicBodies() {
    const bodies = this.scene.matter.world.localWorld?.bodies ?? [];
    return bodies.filter((body) => (
      !body.isStatic
      && !body.isSensor
      && !body.gameObject?.ignoreDestroy
    ));
  }

  snapshotDynamicBodySpeeds() {
    this.getDynamicBodies().forEach((body) => {
      this.bodySpeedSnapshots.set(body, bodySpeed(body));
    });
  }

  getPreviousBodySpeed(body) {
    return this.bodySpeedSnapshots.get(body) ?? bodySpeed(body);
  }

  handleCollisionStart(event) {
    for (const pair of event.pairs) {
      const impact = relativeImpulseMagnitude(pair.bodyA, pair.bodyB);
      const entities = [
        getBodyEntity(pair.bodyA),
        getBodyEntity(pair.bodyB)
      ].filter(Boolean);
      const egg = entities.find((entity) => entity.kind === 'matildaEgg');
      const tnt = entities.find((entity) => entity.kind === 'tnt');

      if (egg) {
        const contactBody = getOtherBodyForEntity(pair, egg);
        egg.explode?.({
          contactBody,
          contactEntity: getBodyEntity(contactBody),
          reason: 'contact'
        });
        continue;
      }

      if (tnt) {
        this.triggerTnt(tnt, {
          reason: 'contact',
          impact,
          timeMs: this.scene.time?.now ?? 0,
          sourceId: entities.find((entity) => entity !== tnt)?.id ?? null
        });
      }

      const bird = entities.find((entity) => entity.kind === 'bird');
      const boulder = entities.find((entity) => entity.kind === 'boulder');
      const birdType = bird?.type ?? (boulder ? 'boulder' : 'environment');
      const birdPreSpeed = bird ? this.getPreviousBodySpeed(bird.body) : 0;
      const birdContactBody = bird ? getOtherBodyForEntity(pair, bird) : null;
      const birdContactEntity = birdContactBody ? getBodyEntity(birdContactBody) : null;
      let hpLoss = 0;
      let chuckDestroyedGlass = false;
      const matildaDestroyedBlocks = [];
      const bombDestroyedWoodBlocks = [];

      if (!bird && impact < PHYSICS_CONFIG.minDamageImpulse) {
        continue;
      }

      if (impact >= PHYSICS_CONFIG.minDamageImpulse || birdType === 'matilda') {
        entities
          .filter((entity) => entity.kind === 'block' || entity.kind === 'boulder')
          .forEach((block) => {
            const previousHp = block.hp;
            const damage = birdType === 'matilda'
              ? previousHp
              : calculateCollisionDamage({
                relativeImpulseMagnitude: impact,
                birdType,
                material: block.material
              });

            block.takeDamage(damage, { reason: 'collision', birdType, impact });
            const blockHpLoss = Math.max(0, previousHp - block.hp);
            hpLoss += blockHpLoss;
            if (
              !block.destroyed
              && crossesStructuralCollapseThreshold({
                previousHp,
                remainingHp: block.hp,
                maxHp: block.maxHp
              })
            ) {
              this.defeatPigsFromStructuralCollapse(block, 'structural-collapse-weakened');
            }
            if (
              birdType === 'chuck'
              && block.material === 'glass'
              && previousHp > 0
              && block.hp <= 0
            ) {
              chuckDestroyedGlass = true;
            }
            if (
              birdType === 'matilda'
              && previousHp > 0
              && block.hp <= 0
            ) {
              matildaDestroyedBlocks.push({
                material: block.material,
                hpLoss: blockHpLoss,
                destroyed: true
              });
            }
            if (
              birdType === 'bomb'
              && block.material === 'wood'
              && previousHp > 0
              && block.hp <= 0
            ) {
              bombDestroyedWoodBlocks.push({
                material: block.material,
                hpLoss: blockHpLoss,
                destroyed: true
              });
            }
            if (damage > 0) {
              this.scene.recordAudioEvent?.(BLOCK_MATERIALS[block.material].impactSfx);
            }
          });

        if (impact >= PHYSICS_CONFIG.minDamageImpulse) {
          entities
            .filter((entity) => entity.kind === 'pig')
            .forEach((pig) => {
              const previousHp = pig.hp;

              pig.takeDamage(calculatePigDamage({
                relativeImpulseMagnitude: impact,
                birdType
              }), { reason: 'collision', birdType, impact });
              hpLoss += Math.max(0, previousHp - pig.hp);
            });
        }
      }

      if (bird && chuckDestroyedGlass) {
        bird.applyGlassBreakSpeedLoss?.({ preSpeed: birdPreSpeed });
      }

      if (bird && matildaDestroyedBlocks.length > 0) {
        const speedLoss = bird.applyBlockContactSpeedLoss?.({ preSpeed: birdPreSpeed });
        this.scene.lastMatildaBlockContact = {
          blocks: matildaDestroyedBlocks,
          preSpeed: birdPreSpeed,
          postSpeed: bird.getVelocity().speed,
          speedRatio: birdPreSpeed > 0 ? bird.getVelocity().speed / birdPreSpeed : 0,
          speedLossFactor: speedLoss?.factor ?? null
        };
      }

      if (bird && bombDestroyedWoodBlocks.length > 0) {
        const speedLoss = bird.applyWoodBreakSpeedLoss?.({ preSpeed: birdPreSpeed });
        this.scene.lastBombWoodContact = {
          ...bombDestroyedWoodBlocks[0],
          preSpeed: birdPreSpeed,
          postSpeed: bird.getVelocity().speed,
          speedRatio: birdPreSpeed > 0 ? bird.getVelocity().speed / birdPreSpeed : 0,
          speedLossFactor: speedLoss?.factor ?? null
        };
      }

      if (bird) {
        bird.recordCollision?.({
          hpLoss,
          preSpeed: birdPreSpeed,
          postSpeed: bird.getVelocity().speed,
          impact,
          contactKind: getContactKind(birdContactBody, birdContactEntity),
          contactMaterial: birdContactEntity?.material ?? null,
          timeMs: this.scene.time?.now ?? null
        });
      }
    }
  }

  triggerTnt(tnt, {
    reason = 'triggered',
    impact = 0,
    delayMs = 0,
    timeMs = this.scene.time?.now ?? 0,
    sourceId = null
  } = {}) {
    if (!tnt || tnt.destroyed || tnt.detonated) {
      return null;
    }

    if (tnt.triggered && delayMs > 0) {
      return null;
    }

    const safeDelayMs = Math.max(0, Math.min(TNT_EXPLOSION.chainDelayMs, Number(delayMs) || 0));
    const scheduledDetonationAtMs = timeMs + safeDelayMs;
    tnt.markTriggered?.({
      reason,
      impact,
      triggeredAtMs: timeMs,
      scheduledDetonationAtMs,
      sourceId
    });

    if (safeDelayMs === 0) {
      return this.detonateTnt(tnt, {
        reason,
        impact,
        timeMs,
        sourceId
      });
    }

    this.scene.time?.delayedCall?.(safeDelayMs, () => {
      this.detonateTnt(tnt, {
        reason,
        impact,
        timeMs: this.scene.time?.now ?? scheduledDetonationAtMs,
        sourceId
      });
    });

    return {
      tnt,
      reason,
      impact,
      delayMs: safeDelayMs,
      scheduledDetonationAtMs
    };
  }

  detonateTnt(tnt, {
    reason = 'detonated',
    impact = 0,
    timeMs = this.scene.time?.now ?? 0,
    sourceId = null
  } = {}) {
    if (!tnt || tnt.detonated || tnt.destroyed) {
      return null;
    }

    const origin = entityPosition(tnt);
    tnt.markTriggered?.({
      reason,
      impact,
      triggeredAtMs: tnt.triggeredAtMs ?? timeMs,
      scheduledDetonationAtMs: tnt.scheduledDetonationAtMs ?? timeMs,
      sourceId
    });
    tnt.markDetonated?.(timeMs);
    if (!tnt.destroyed) {
      tnt.destroy?.('detonated');
    }
    this.tntCrates = this.tntCrates.filter((entry) => entry !== tnt);
    this.offWorldSince.delete(tnt.id);

    const affectedBlocks = [];
    const affectedPigs = [];
    const chainedTnt = [];

    this.scene.addScore?.(TNT_EXPLOSION.score);
    this.scene.recordAudioEvent?.(TNT_EXPLOSION.audioEvent);

    [...this.blocks].forEach((block, index) => {
      if (block.destroyed) {
        return;
      }

      const position = entityPosition(block);
      const distance = distanceBetween(origin, position);
      if (distance > TNT_EXPLOSION.radiusPx) {
        return;
      }

      const previousHp = block.hp;
      const damage = TNT_EXPLOSION.blockDamage[block.material] ?? 0;

      this.applyTntImpulse(block, origin, distance, index);
      block.takeDamage(damage, {
        reason: 'tnt-explosion',
        impact: 0,
        sourceId: tnt.id
      });

      affectedBlocks.push({
        id: block.id ?? null,
        kind: block.kind ?? 'block',
        material: block.material,
        distance,
        damage,
        hpLoss: Math.max(0, previousHp - block.hp),
        destroyed: Boolean(block.destroyed)
      });
    });

    [...this.pigs].forEach((pig, index) => {
      if (pig.defeated) {
        return;
      }

      const position = entityPosition(pig);
      const distance = distanceBetween(origin, position);
      if (distance > TNT_EXPLOSION.radiusPx) {
        return;
      }

      this.applyTntImpulse(pig, origin, distance, index + affectedBlocks.length);
      pig.defeat?.('tnt-explosion');
      affectedPigs.push({
        id: pig.id ?? null,
        tier: pig.tier ?? null,
        distance,
        damage: TNT_EXPLOSION.pigDamage,
        defeated: Boolean(pig.defeated)
      });
    });

    [...this.tntCrates].forEach((otherTnt) => {
      if (otherTnt === tnt || otherTnt.destroyed || otherTnt.detonated || otherTnt.triggered) {
        return;
      }

      const distance = distanceBetween(origin, entityPosition(otherTnt));
      if (distance > TNT_EXPLOSION.radiusPx) {
        return;
      }

      this.triggerTnt(otherTnt, {
        reason: 'chain',
        delayMs: TNT_EXPLOSION.chainDelayMs,
        timeMs,
        sourceId: tnt.id
      });
      chainedTnt.push({
        id: otherTnt.id ?? null,
        distance,
        triggerDeltaMs: (otherTnt.scheduledDetonationAtMs ?? timeMs) - timeMs
      });
    });

    this.getPool(TNT_EXPLOSION.particleKey).explode(origin.x, origin.y, {
      count: TNT_EXPLOSION.particleCount,
      lifespanMs: TNT_EXPLOSION.particleLifespanMs,
      distance: TNT_EXPLOSION.radiusPx * 0.55
    });

    this.scene.lastTntExplosion = {
      reason,
      impact,
      sourceId,
      tntId: tnt.id ?? null,
      x: origin.x,
      y: origin.y,
      radiusPx: TNT_EXPLOSION.radiusPx,
      affectedBlocks,
      affectedPigs,
      chainedTnt
    };

    return this.scene.lastTntExplosion;
  }

  applyTntImpulse(entity, origin, distance, index = 0) {
    const position = entityPosition(entity);
    let dx = position.x - origin.x;
    let dy = position.y - origin.y;
    let magnitude = Math.hypot(dx, dy);

    if (magnitude === 0) {
      const angle = -Math.PI / 2 + index * 0.45;
      dx = Math.cos(angle);
      dy = Math.sin(angle);
      magnitude = 1;
    }

    const falloff = calculateTntExplosionFalloff(distance);
    const current = getEntityVelocity(entity);
    const impulse = TNT_EXPLOSION.radialImpulse * falloff;

    setEntityVelocity(entity, {
      x: current.x + (dx / magnitude) * impulse,
      y: current.y + (dy / magnitude) * impulse
    });
  }

  onBombExploded(bird, explosion = {}) {
    const origin = {
      x: explosion.x ?? bird?.x ?? 0,
      y: explosion.y ?? bird?.y ?? 0
    };
    const affectedBlocks = [];
    const affectedPigs = [];

    [...this.blocks].forEach((block, index) => {
      if (block.destroyed) {
        return;
      }

      const position = entityPosition(block);
      const distance = distanceBetween(origin, position);
      const falloff = calculateBombExplosionFalloff(distance);

      if (falloff <= 0) {
        return;
      }

      const previousHp = block.hp;
      const damage = BOMB_EXPLOSION.baseBlockDamage
        * (BOMB_EXPLOSION.materialMultiplier[block.material] ?? 1)
        * falloff;

      this.applyBombImpulse(block, origin, distance, index);
      block.takeDamage(damage, {
        reason: 'bomb-explosion',
        birdType: 'bomb',
        impact: 0
      });

      affectedBlocks.push({
        id: block.id ?? null,
        material: block.material,
        distance,
        damage,
        hpLoss: Math.max(0, previousHp - block.hp),
        destroyed: block.destroyed
      });
    });

    [...this.pigs].forEach((pig, index) => {
      if (pig.defeated) {
        return;
      }

      const position = entityPosition(pig);
      const distance = distanceBetween(origin, position);
      const falloff = calculateBombExplosionFalloff(distance);

      if (falloff <= 0) {
        return;
      }

      const previousHp = pig.hp;
      const damage = BOMB_EXPLOSION.pigDamage * falloff;

      this.applyBombImpulse(pig, origin, distance, index + affectedBlocks.length);
      pig.takeDamage(damage, {
        reason: 'bomb-explosion',
        birdType: 'bomb',
        impact: 0
      });

      affectedPigs.push({
        id: pig.id ?? null,
        tier: pig.tier ?? null,
        distance,
        damage,
        hpLoss: Math.max(0, previousHp - pig.hp),
        defeated: pig.defeated
      });
    });

    if (!['tap', 'tap-during-auto-timer'].includes(explosion.reason)) {
      this.scene.recordAudioEvent?.(BOMB_EXPLOSION.audioEvent);
    }

    this.getPool(BOMB_EXPLOSION.particleKey).explode(origin.x, origin.y, {
      count: BOMB_EXPLOSION.particleCount,
      lifespanMs: BOMB_EXPLOSION.particleLifespanMs,
      distance: BOMB_EXPLOSION.radiusPx * 0.55
    });

    this.scene.lastBombExplosion = {
      ...explosion,
      x: origin.x,
      y: origin.y,
      radiusPx: BOMB_EXPLOSION.radiusPx,
      affectedBlocks,
      affectedPigs
    };

    return this.scene.lastBombExplosion;
  }

  applyBombImpulse(entity, origin, distance, index = 0) {
    const position = entityPosition(entity);
    let dx = position.x - origin.x;
    let dy = position.y - origin.y;
    let magnitude = Math.hypot(dx, dy);

    if (magnitude === 0) {
      const angle = -Math.PI / 2 + index * 0.45;
      dx = Math.cos(angle);
      dy = Math.sin(angle);
      magnitude = 1;
    }

    const falloff = calculateBombExplosionFalloff(distance);
    const current = getEntityVelocity(entity);
    const impulse = BOMB_EXPLOSION.radialImpulse * falloff;

    setEntityVelocity(entity, {
      x: current.x + (dx / magnitude) * impulse,
      y: current.y + (dy / magnitude) * impulse
    });
  }

  onMatildaEggExploded(egg, {
    contactBody = null,
    contactEntity = null,
    reason = 'contact'
  } = {}) {
    this.eggs = this.eggs.filter((entry) => entry !== egg);
    this.offWorldSince.delete(egg.id);

    if (contactEntity?.kind === 'block' && !contactEntity.destroyed) {
      contactEntity.takeDamage(contactEntity.hp, {
        reason: 'matilda-egg',
        birdType: 'matilda',
        impact: 0
      });
    } else if (contactEntity?.kind === 'pig' && !contactEntity.defeated) {
      contactEntity.takeDamage(contactEntity.hp, {
        reason: 'matilda-egg',
        birdType: 'matilda',
        impact: 0
      });
    }

    this.scene.recordAudioEvent?.(MATILDA_EGG_EXPLOSION.audioEvent);
    this.getPool(MATILDA_EGG_EXPLOSION.particleKey).explode(egg.x, egg.y, {
      count: MATILDA_EGG_EXPLOSION.particleCount,
      lifespanMs: MATILDA_EGG_EXPLOSION.particleLifespanMs,
      distance: 74
    });
    this.scene.lastMatildaEggExplosion = {
      reason,
      contactKind: getContactKind(contactBody, contactEntity),
      contactMaterial: contactEntity?.material ?? null,
      x: egg.x,
      y: egg.y
    };
  }

  onBlockDestroyed(block, reason = 'destroyed') {
    this.blocks = this.blocks.filter((entry) => entry !== block);
    this.boulders = this.boulders.filter((entry) => entry !== block);
    if (Array.isArray(this.scene.boulders)) {
      this.scene.boulders = this.scene.boulders.filter((entry) => entry !== block);
    }
    this.offWorldSince.delete(block.id);

    const material = block.kind === 'boulder'
      ? BOULDER
      : BLOCK_MATERIALS[block.material];
    if (!material) {
      return;
    }

    if (reason !== 'off-world') {
      this.scene.addScore?.(material.score);
      this.scene.recordAudioEvent?.(material.breakSfx);
      this.emitMaterialBurst(block.x, block.y, material);
      this.defeatPigsFromStructuralCollapse(block);
    }
  }

  defeatPigsFromStructuralCollapse(block, reason = 'structural-collapse') {
    const origin = entityPosition(block);

    [...this.pigs].forEach((pig) => {
      if (pig.defeated) {
        return;
      }

      const distance = distanceBetween(origin, entityPosition(pig));
      const collapseRadius = calculateStructuralCollapseRadius(block, pig.radius);
      if (distance > collapseRadius) {
        return;
      }

      pig.takeDamage(pig.hp, {
        reason,
        sourceId: block.id ?? null,
        material: block.material ?? block.kind ?? null,
        distance,
        radius: collapseRadius
      });
    });
  }

  onTntDestroyed(tnt) {
    this.tntCrates = this.tntCrates.filter((entry) => entry !== tnt);
    if (Array.isArray(this.scene.tntCrates)) {
      this.scene.tntCrates = this.scene.tntCrates.filter((entry) => entry !== tnt);
    }
    this.offWorldSince.delete(tnt.id);
  }

  onPigDefeated(pig, reason = 'defeated') {
    this.pigs = this.pigs.filter((entry) => entry !== pig);
    this.offWorldSince.delete(pig.id);
    this.scene.addScore?.(pig.score);
    this.scene.recordAudioEvent?.(PHYSICS_SFX.pigPop);
    this.emitPigBurst(pig.x, pig.y);
    this.updateScenePigCount();
    this.scene.lastPigDefeatReason = reason;
    this.scene.handlePigDefeated?.({
      pig,
      reason,
      pigsLeft: this.pigs.length
    });
  }

  cleanupOffWorldEntities(timeMs) {
    [...this.blocks, ...this.pigs].forEach((entity) => {
      if (entity.destroyed || entity.defeated) {
        return;
      }

      if (entity.kind === 'pig' && this.isPigEscaped(entity)) {
        entity.defeat('stuck-pig-escape');
        return;
      }

      if (!this.isOutsideWorld(entity)) {
        this.offWorldSince.delete(entity.id);
        return;
      }

      const firstSeenAt = this.offWorldSince.get(entity.id) ?? timeMs;
      this.offWorldSince.set(entity.id, firstSeenAt);
      if (timeMs - firstSeenAt < PHYSICS_CONFIG.offWorldCleanupMs) {
        return;
      }

      if (entity.kind === 'pig') {
        entity.defeat('off-world');
      } else {
        entity.destroy('off-world');
      }
    });
  }

  isOutsideWorld(entity) {
    const { left, right, bottom } = this.worldBounds;
    return entity.x < left || entity.x > right || entity.y > bottom;
  }

  isPigEscaped(pig) {
    const { left, right, bottom } = this.worldBounds;
    return pig.y > bottom + 50 || pig.x < left - 200 || pig.x > right + 200;
  }

  emitMaterialBurst(x, y, material) {
    this.getPool(material.particleKey).explode(x, y, {
      count: material.particleCount,
      lifespanMs: material.particleLifespanMs,
      distance: material.particleKey.includes('glass') ? 70 : 52
    });
  }

  emitPigBurst(x, y) {
    this.getPool(PIG_PARTICLE.key).explode(x, y, {
      count: PIG_PARTICLE.count,
      lifespanMs: PIG_PARTICLE.lifespanMs,
      distance: 46
    });
  }

  getPool(key) {
    if (!this.particlePools.has(key)) {
      this.particlePools.set(key, new BurstPool(this.scene, key));
    }

    return this.particlePools.get(key);
  }

  updateScenePigCount() {
    this.scene.pigsLeft = this.pigs.filter((pig) => !pig.defeated).length;
  }

  getDebugState() {
    return {
      settled: this.settle.getState(),
      blocks: this.blocks.map((block) => block.getDebugState()),
      boulders: this.boulders.map((boulder) => boulder.getDebugState()),
      pigs: this.pigs.map((pig) => pig.getDebugState()),
      tntCrates: this.tntCrates.map((tnt) => tnt.getDebugState()),
      eggs: this.eggs.map((egg) => egg.getDebugState()),
      worldBounds: { ...this.worldBounds }
    };
  }

  destroy() {
    this.scene.matter.world.off('collisionstart', this.handleCollisionStart);
    this.particlePools.forEach((pool) => pool.destroy());
    this.particlePools.clear();
    this.bodySpeedSnapshots = new WeakMap();
  }
}
