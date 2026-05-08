import Phaser from 'phaser';

import { BOOT_ASSETS, loadAsset } from '../constants/assets.js';
import { registerDebugScene } from '../systems/debug.js';

export default class Boot extends Phaser.Scene {
  constructor() {
    super('Boot');
  }

  preload() {
    BOOT_ASSETS.forEach((asset) => loadAsset(this, asset));
  }

  create() {
    registerDebugScene(this);
    this.scene.start('Preloader');
  }
}
