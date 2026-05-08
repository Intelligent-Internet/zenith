import { BLOCK_MATERIALS } from '../constants/materials.js';
import { applyDamageToHp } from '../systems/physics.js';

let nextBlockId = 1;

export default class Block {
  constructor(scene, material, x, y, {
    width = 88,
    height = 88,
    angle = 0,
    isStatic = false
  } = {}) {
    const config = BLOCK_MATERIALS[material];
    if (!config) {
      throw new Error(`Unknown block material: ${material}`);
    }

    this.id = `block-${nextBlockId}`;
    nextBlockId += 1;
    this.kind = 'block';
    this.scene = scene;
    this.material = material;
    this.maxHp = config.hp;
    this.hp = config.hp;
    this.destroyed = false;
    this.width = width;
    this.height = height;
    this.lastPosition = { x, y };

    this.gameObject = scene.matter.add.image(x, y, config.texture)
      .setDisplaySize(width, height)
      .setRectangle(width, height)
      .setDepth(3)
      .setFriction(0.8)
      .setFrictionAir(0.002)
      .setBounce(config.restitution)
      .setDensity(config.density)
      .setStatic(isStatic);

    this.gameObject.setAngle(angle);
    this.gameObject.setData('physicsEntity', this);
    this.gameObject.setData('entityKind', this.kind);
    this.gameObject.setData('material', material);
    scene.physicsSystem?.registerBlock(this);
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
    if (this.destroyed) {
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
      this.destroy('damage');
    }

    return this.getDebugState();
  }

  destroy(reason = 'destroyed') {
    if (this.destroyed) {
      return;
    }

    this.destroyed = true;
    this.scene.physicsSystem?.onBlockDestroyed(this, reason);
    this.gameObject.destroy();
  }

  getDebugState() {
    return {
      id: this.id,
      kind: this.kind,
      material: this.material,
      hp: this.hp,
      maxHp: this.maxHp,
      x: this.x,
      y: this.y,
      width: this.width,
      height: this.height,
      destroyed: this.destroyed,
      lastDamage: this.lastDamage ?? null
    };
  }
}

export class WoodBlock extends Block {
  constructor(scene, x, y, options = {}) {
    super(scene, 'wood', x, y, options);
  }
}

export class GlassBlock extends Block {
  constructor(scene, x, y, options = {}) {
    super(scene, 'glass', x, y, options);
  }
}

export class StoneBlock extends Block {
  constructor(scene, x, y, options = {}) {
    super(scene, 'stone', x, y, options);
  }
}
