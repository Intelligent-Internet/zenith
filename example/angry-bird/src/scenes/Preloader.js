import Phaser from 'phaser';

import { PLACEHOLDER_ASSETS, loadAsset } from '../constants/assets.js';
import {
  installFallbackTexture,
  warnAssetLoadFailure
} from '../systems/assetFallback.js';
import {
  clearTransientLevelParam,
  resolveBootRoute
} from '../systems/bootRoute.js';
import { registerDebugScene } from '../systems/debug.js';

export default class Preloader extends Phaser.Scene {
  constructor() {
    super('Preloader');
  }

  preload() {
    const { width, height } = this.scale;
    const barWidth = 420;
    const barX = width / 2;
    const barY = height / 2 + 54;

    this.add.rectangle(width / 2, height / 2, width, height, 0x7ec8e3);
    this.add.image(barX, barY, 'loading-bar').setDisplaySize(barWidth, 24);
    const fill = this.add.rectangle(barX - barWidth / 2, barY, 0, 14, 0xf04b34).setOrigin(0, 0.5);

    this.add.text(width / 2, height / 2 - 26, 'Loading...', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '28px',
      color: '#ffffff'
    }).setOrigin(0.5);

    this.load.on('progress', (value) => {
      fill.width = Math.max(4, (barWidth - 16) * value);
    });

    const assetsByKey = new Map(PLACEHOLDER_ASSETS.map((asset) => [asset.key, asset]));
    const warnedAssetKeys = new Set();
    const handleLoadError = (file) => {
      const asset = assetsByKey.get(file?.key);

      if (!asset) {
        return;
      }

      installFallbackTexture(this, asset);
      warnAssetLoadFailure(asset, { warnedKeys: warnedAssetKeys });
    };

    this.load.on('loaderror', handleLoadError);
    this.load.once('complete', () => {
      this.load.off('loaderror', handleLoadError);
    });

    PLACEHOLDER_ASSETS.forEach((asset) => loadAsset(this, asset));
  }

  create() {
    registerDebugScene(this);
    if (typeof window !== 'undefined') {
      const route = resolveBootRoute({
        search: window.location.search,
        env: import.meta.env
      });

      if (route.transientLevelParam) {
        clearTransientLevelParam(window);
      }

      this.scene.start(route.scene, route.data);
      return;
    }

    this.scene.start('Menu');
  }
}
