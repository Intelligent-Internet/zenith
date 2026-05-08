import { PIG_TIERS } from '../constants/materials.js';
import { applyDamageToHp } from '../systems/physics.js';

let nextPigId = 1;

export default class Pig {
  constructor(scene, tier, x, y, {
    isStatic = false
  } = {}) {
    const config = PIG_TIERS[tier];
    if (!config) {
      throw new Error(`Unknown pig tier: ${tier}`);
    }

    this.id = `pig-${nextPigId}`;
    nextPigId += 1;
    this.kind = 'pig';
    this.scene = scene;
    this.tier = tier;
    this.maxHp = config.hp;
    this.hp = config.hp;
    this.score = config.score;
    this.radius = config.radius;
    this.defeated = false;
    this.lastPosition = { x, y };

    this.gameObject = scene.matter.add.image(x, y, config.texture)
      .setCircle(config.radius)
      .setDisplaySize(config.radius * 2, config.radius * 2)
      .setDepth(4)
      .setFriction(0.7)
      .setFrictionAir(0.001)
      .setBounce(0.25)
      .setDensity(0.001)
      .setStatic(isStatic);

    this.gameObject.setData('physicsEntity', this);
    this.gameObject.setData('entityKind', this.kind);
    this.gameObject.setData('tier', tier);
    this.gameObject.setData('hp', this.hp);
    scene.physicsSystem?.registerPig(this);
  }

  get x() {
    return this.getPosition().x;
  }

  get y() {
    return this.getPosition().y;
  }

  get body() {
    return this.gameObject.body;
  }

  getPosition() {
    const position = this.gameObject?.body?.position;
    if (position) {
      this.lastPosition = { x: position.x, y: position.y };
    }

    return this.lastPosition;
  }

  takeDamage(damage, source = {}) {
    if (this.defeated) {
      return this.getDebugState();
    }

    const result = applyDamageToHp(this.hp, damage);
    this.hp = result.remainingHp;
    this.lastDamage = {
      amount: Math.max(0, damage),
      source,
      remainingHp: this.hp
    };
    this.gameObject.setData('hp', this.hp);

    if (result.destroyed) {
      this.defeat('damage');
    }

    return this.getDebugState();
  }

  defeat(reason = 'defeated') {
    if (this.defeated) {
      return;
    }

    this.defeated = true;
    this.scene.physicsSystem?.onPigDefeated(this, reason);
    this.gameObject.destroy();
  }

  getDebugState() {
    return {
      id: this.id,
      kind: this.kind,
      tier: this.tier,
      hp: this.hp,
      maxHp: this.maxHp,
      score: this.score,
      x: this.x,
      y: this.y,
      radius: this.radius,
      defeated: this.defeated,
      lastDamage: this.lastDamage ?? null
    };
  }
}

export class SmallPig extends Pig {
  constructor(scene, x, y, options = {}) {
    super(scene, 'small', x, y, options);
  }
}

export class MediumPig extends Pig {
  constructor(scene, x, y, options = {}) {
    super(scene, 'medium', x, y, options);
  }
}

export class LargePig extends Pig {
  constructor(scene, x, y, options = {}) {
    super(scene, 'large', x, y, options);
  }
}
