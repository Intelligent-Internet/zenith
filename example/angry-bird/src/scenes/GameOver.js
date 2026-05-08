import Phaser from 'phaser';

import { registerDebugScene } from '../systems/debug.js';

export default class GameOver extends Phaser.Scene {
  constructor() {
    super('GameOver');
  }

  create() {
    registerDebugScene(this);

    this.add.text(640, 360, 'Game Over', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '48px',
      color: '#ffffff'
    }).setOrigin(0.5);
  }
}
