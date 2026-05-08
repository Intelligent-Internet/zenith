import Phaser from 'phaser';

import {
  BIRD_SPRITE_STATES,
  BIRD_SPRITE_TYPES,
  MATERIAL_PARTICLE_TYPES,
  MATERIAL_SPRITE_TYPES,
  PIG_SPRITE_TYPES
} from '../constants/assets.js';
import { registerDebugScene } from '../systems/debug.js';

const BIRD_LABELS = {
  red: 'Red',
  blues: 'Blues',
  chuck: 'Chuck',
  matilda: 'Matilda',
  bomb: 'Bomb',
  hal: 'Hal'
};

const PIG_LABELS = {
  small: 'Small',
  medium: 'Medium',
  large: 'Large',
  helmeted: 'Helmet'
};

const MATERIAL_LABELS = {
  wood: 'Wood',
  glass: 'Glass',
  stone: 'Stone'
};

const MATERIAL_PARTICLE_KEYS = {
  wood: 'particle-wood-splinter',
  glass: 'particle-glass-shard',
  stone: 'particle-stone-rubble'
};

function addSectionLabel(scene, x, y, label) {
  scene.add.text(x, y, label, {
    fontFamily: 'Arial, sans-serif',
    fontSize: '21px',
    color: '#243040'
  }).setOrigin(0.5);
}

function addSmallLabel(scene, x, y, label) {
  scene.add.text(x, y, label, {
    fontFamily: 'Arial, sans-serif',
    fontSize: '14px',
    color: '#4b5563'
  }).setOrigin(0.5);
}

export default class DebugRoster extends Phaser.Scene {
  constructor() {
    super('DebugRoster');
  }

  create() {
    const { width, height } = this.scale;

    this.add.rectangle(width / 2, height / 2, width, height, 0xeef5f8);
    this.add.text(width / 2, 34, 'Debug Asset Roster', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '30px',
      color: '#243040'
    }).setOrigin(0.5);

    addSectionLabel(this, 398, 72, 'Birds');

    BIRD_SPRITE_STATES.forEach((state, column) => {
      this.add.text(182 + column * 120, 102, state.label, {
        fontFamily: 'Arial, sans-serif',
        fontSize: '13px',
        color: '#4b5563'
      }).setOrigin(0.5);
    });

    BIRD_SPRITE_TYPES.forEach((birdType, row) => {
      const y = 144 + row * 68;

      this.add.text(72, y, BIRD_LABELS[birdType], {
        fontFamily: 'Arial, sans-serif',
        fontSize: '17px',
        color: '#a16207'
      }).setOrigin(0.5);

      BIRD_SPRITE_STATES.forEach((state, column) => {
        this.add.sprite(182 + column * 120, y, `bird-${birdType}`, state.frame)
          .setDisplaySize(54, 54)
          .setOrigin(0.5);
      });
    });

    addSectionLabel(this, 1000, 84, 'Pigs');
    PIG_SPRITE_TYPES.forEach((pigType, index) => {
      const x = 828 + index * 116;
      const displaySize = { small: 50, medium: 62, large: 74, helmeted: 68 }[pigType];
      this.add.image(x, 150, `pig-${pigType}`)
        .setDisplaySize(displaySize, displaySize)
        .setOrigin(0.5);
      addSmallLabel(this, x, 206, PIG_LABELS[pigType]);
    });

    addSectionLabel(this, 1000, 266, 'Blocks');
    MATERIAL_SPRITE_TYPES.forEach((material, index) => {
      const x = 850 + index * 150;
      const displaySize = material === 'wood'
        ? { width: 112, height: 68 }
        : { width: 74, height: 74 };
      this.add.image(x, 336, `block-${material}`)
        .setDisplaySize(displaySize.width, displaySize.height)
        .setOrigin(0.5);
      addSmallLabel(this, x, 396, MATERIAL_LABELS[material]);
    });

    addSectionLabel(this, 1000, 466, 'Break Particles');
    MATERIAL_PARTICLE_TYPES.forEach((material, index) => {
      const x = 850 + index * 150;
      this.add.image(x, 528, MATERIAL_PARTICLE_KEYS[material])
        .setDisplaySize(46, 46)
        .setOrigin(0.5);
      addSmallLabel(this, x, 574, MATERIAL_LABELS[material]);
    });

    this.add.text(width - 72, height - 38, 'Menu', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '18px',
      color: '#ffffff',
      backgroundColor: '#334155',
      padding: { x: 14, y: 8 }
    })
      .setOrigin(0.5)
      .setInteractive({ useHandCursor: true })
      .on('pointerup', () => this.scene.start('Menu'));

    registerDebugScene(this, {
      showRoster: () => true
    });
  }
}
