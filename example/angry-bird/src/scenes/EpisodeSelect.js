import Phaser from 'phaser';

import { registerDebugScene } from '../systems/debug.js';
import { getPersistence } from '../systems/persistence.js';
import { computeUnlocks } from '../systems/progression.js';
import {
  buildEpisodeSelectCards,
  buildEpisodeSelectSnapshot
} from '../systems/selectScreenModels.js';

export default class EpisodeSelect extends Phaser.Scene {
  constructor() {
    super('EpisodeSelect');
  }

  init(data = {}) {
    this.focusIndex = Number(data.focusIndex) || 0;
  }

  create() {
    this.persistence = getPersistence();
    this.save = this.persistence.loadSave();
    this.unlocks = computeUnlocks(this.save);

    this.drawBackdrop();
    this.add.text(640, 68, 'Episode Select', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '46px',
      fontStyle: 'bold',
      color: '#ffffff',
      stroke: '#173b32',
      strokeThickness: 7
    }).setOrigin(0.5).setDepth(5);

    this.renderEpisodeCards();
    this.renderForwardArrow();
    this.input.off('pointerdown', this.handlePointerDown, this);
    this.input.on('pointerdown', this.handlePointerDown, this);
    this.refreshDebug();
  }

  drawBackdrop() {
    this.add.image(0, 0, 'bg-episode-2')
      .setOrigin(0)
      .setDisplaySize(1280, 720)
      .setDepth(-30);
    this.add.rectangle(640, 360, 1280, 720, 0x1b8a63, 0.18).setDepth(-29);
    this.add.circle(640, 706, 148, 0xf8d24a, 0.88).setDepth(-28);
    this.add.ellipse(232, 652, 620, 180, 0x2f8f4e, 0.95).setDepth(-27);
    this.add.ellipse(1030, 650, 560, 190, 0x2f8f4e, 0.95).setDepth(-27);
    this.add.rectangle(640, 684, 1280, 88, 0x2f7d32, 0.88).setDepth(-26);
  }

  renderEpisodeCards() {
    this.cardLayer?.destroy(true);
    this.cardLayer = this.add.container(0, 0);
    this.lockedCardFeedbacks = [];
    this.episodeCards = buildEpisodeSelectCards(this.save, this.unlocks);
    this.focusIndex = this.normalizeFocusIndex(this.focusIndex);

    this.episodeCards.forEach((card, index) => {
      this.drawEpisodeCard(card, index === this.focusIndex);
    });
    this.drawFocusDots();
  }

  drawEpisodeCard(card, focused) {
    const container = this.add.container(card.x, card.y).setDepth(8);
    const body = this.add.graphics();
    const bodyFill = card.locked ? 0x465763 : 0x14273b;
    const stroke = focused ? 0xf8d24a : 0x071927;
    const strokeWidth = focused ? 6 : 4;
    const top = -card.height / 2;
    const left = -card.width / 2;

    body.fillStyle(bodyFill, 1);
    body.lineStyle(strokeWidth, stroke, 1);
    body.fillRoundedRect(left, top, card.width, card.height, 8);
    body.strokeRoundedRect(left, top, card.width, card.height, 8);

    const heroPanel = this.add.rectangle(0, -112, card.width - 24, 210, 0xd9f0f2, 1)
      .setStrokeStyle(3, 0x0d2433);
    const hero = this.add.image(0, -114, card.heroKey)
      .setDisplaySize(card.heroRegion.width, card.heroRegion.height);
    const badge = this.add.circle(left + 32, top + 32, 24, 0xf6f0d0)
      .setStrokeStyle(3, 0x0d2433);
    const badgeText = this.add.text(left + 32, top + 31, `${card.episode}.`, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '25px',
      fontStyle: 'bold',
      color: '#1f2933'
    }).setOrigin(0.5);
    const title = this.add.text(0, 34, card.title.toUpperCase(), {
      fontFamily: 'Arial, sans-serif',
      fontSize: '28px',
      fontStyle: 'bold',
      color: '#ffffff',
      stroke: '#1f2933',
      strokeThickness: 5,
      align: 'center',
      wordWrap: { width: card.width - 34 }
    }).setOrigin(0.5);

    const scorePanel = this.add.rectangle(0, 116, card.width - 32, 58, 0x071927, 0.92)
      .setStrokeStyle(2, 0x20364a);
    const scoreLabel = this.add.text(0, 101, 'SCORE', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '15px',
      fontStyle: 'bold',
      color: '#ffffff'
    }).setOrigin(0.5);
    const score = this.add.text(0, 126, card.scoreTotalText.replace('Score ', ''), {
      fontFamily: 'Arial, sans-serif',
      fontSize: '21px',
      fontStyle: 'bold',
      color: '#ffffff'
    }).setOrigin(0.5);

    const starPanel = this.add.rectangle(0, 179, card.width - 32, 50, 0x071927, 0.92)
      .setStrokeStyle(2, 0x20364a);
    const star = this.add.star(-34, 179, 5, 8, 17, 0xf8d24a)
      .setStrokeStyle(2, 0x7a4d00);
    const tally = this.add.text(12, 179, card.starTallyText, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '22px',
      fontStyle: 'bold',
      color: '#ffffff'
    }).setOrigin(0.5);

    container.add([
      body,
      heroPanel,
      hero,
      badge,
      badgeText,
      title,
      scorePanel,
      scoreLabel,
      score,
      starPanel,
      star,
      tally
    ]);
    container.setData('restingX', card.x);

    let lockFeedback = null;

    if (card.locked) {
      lockFeedback = this.addLockedOverlay(container, card);
      container.setAlpha(0.74);
    }

    this.cardLayer.add(container);

    if (card.unlocked) {
      const hitArea = this.add.rectangle(card.x, card.y, card.width, card.height, 0xffffff, 0.001)
        .setInteractive({ useHandCursor: true })
        .setDepth(30);
      hitArea.on('pointerdown', () => {
        this.scene.start('LevelSelect', { episode: card.episode });
      });
      this.cardLayer.add(hitArea);
    } else {
      this.addLockedHitArea(card, container, lockFeedback);
    }
  }

  addLockedOverlay(container, card) {
    const overlay = this.add.rectangle(0, 0, card.width - 16, card.height - 16, 0x000000, 0.28);
    const lock = this.add.graphics();

    lock.lineStyle(6, 0xf8d24a, 0.98);
    lock.beginPath();
    lock.arc(0, -2, 24, Math.PI, 0, false);
    lock.strokePath();
    lock.fillStyle(0xf8d24a, 0.98);
    lock.fillRoundedRect(-28, -2, 56, 42, 7);
    lock.fillStyle(0x1f2933, 1);
    lock.fillCircle(0, 16, 5);
    lock.fillRect(-3, 17, 6, 12);
    const feedback = this.add.graphics().setVisible(false);

    feedback.fillStyle(0xf8d24a, 0.28);
    feedback.fillRoundedRect(
      -card.width / 2 + 7,
      -card.height / 2 + 7,
      card.width - 14,
      card.height - 14,
      8
    );
    feedback.lineStyle(7, 0xf8d24a, 1);
    feedback.strokeRoundedRect(
      -card.width / 2 + 7,
      -card.height / 2 + 7,
      card.width - 14,
      card.height - 14,
      8
    );

    container.add([overlay, lock, feedback]);
    return feedback;
  }

  addLockedHitArea(card, container, feedback) {
    this.lockedCardFeedbacks.push({ card, container, feedback });

    const triggerFeedback = () => {
      this.playLockedFeedback(container, feedback);
    };

    container.setSize(card.width, card.height);
    container.setInteractive(
      new Phaser.Geom.Rectangle(-card.width / 2, -card.height / 2, card.width, card.height),
      Phaser.Geom.Rectangle.Contains
    );
    container.on('pointerdown', triggerFeedback);
    container.on('pointerup', triggerFeedback);

    const hitArea = this.add.rectangle(card.x, card.y, card.width, card.height, 0xffffff, 0.001)
      .setInteractive({ useHandCursor: true })
      .setDepth(30);

    hitArea.on('pointerdown', triggerFeedback);
    hitArea.on('pointerup', triggerFeedback);
    this.cardLayer.add(hitArea);
  }

  handlePointerDown(pointer) {
    const hit = this.lockedCardFeedbacks.find(({ card }) => (
      pointer.x >= card.x - card.width / 2
        && pointer.x <= card.x + card.width / 2
        && pointer.y >= card.y - card.height / 2
        && pointer.y <= card.y + card.height / 2
    ));

    if (hit) {
      this.playLockedFeedback(hit.container, hit.feedback);
    }
  }

  playLockedFeedback(container, feedback) {
    const restingX = container.getData('restingX') ?? container.x;
    const previousShake = container.getData('lockShakeTween');

    previousShake?.stop();
    container.setX(restingX);

    if (feedback) {
      this.tweens.killTweensOf(feedback);
      feedback.setVisible(true).setAlpha(1);
      this.tweens.add({
        targets: feedback,
        alpha: 0.18,
        duration: 900,
        ease: 'Quad.easeOut',
        onComplete: () => {
          feedback.setVisible(false).setAlpha(1);
        }
      });
    }

    const shake = this.tweens.addCounter({
      from: 0,
      to: 1,
      duration: 330,
      ease: 'Sine.easeInOut',
      onUpdate: (tween) => {
        container.setX(restingX + Math.sin(tween.getValue() * Math.PI * 8) * 9);
      },
      onComplete: () => {
        container.setX(restingX);
        container.setData('lockShakeTween', null);
      }
    });
    container.setData('lockShakeTween', shake);
  }

  drawFocusDots() {
    this.episodeCards.forEach((card, index) => {
      const dot = this.add.circle(614 + index * 26, 642, 8, index === this.focusIndex ? 0xf8d24a : 0xffffff, 0.9)
        .setStrokeStyle(2, 0x0d2433)
        .setDepth(12);
      this.cardLayer.add(dot);
    });
  }

  renderForwardArrow() {
    const circle = this.add.circle(1196, 358, 34, 0x67c7e9, 1)
      .setStrokeStyle(4, 0xffffff)
      .setInteractive({ useHandCursor: true })
      .setDepth(25);
    const arrow = this.add.text(1199, 356, '>', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '44px',
      fontStyle: 'bold',
      color: '#ffffff'
    }).setOrigin(0.5).setDepth(26);

    circle.on('pointerdown', () => this.advanceFocus());
    arrow.setInteractive({ useHandCursor: true });
    arrow.on('pointerdown', () => this.advanceFocus());
  }

  normalizeFocusIndex(index) {
    const count = this.episodeCards?.length ?? 0;
    if (count === 0) {
      return 0;
    }

    return ((index % count) + count) % count;
  }

  advanceFocus() {
    this.focusIndex = this.normalizeFocusIndex(this.focusIndex + 1);
    this.renderEpisodeCards();
    this.refreshDebug();
  }

  getEpisodeSelectDOM() {
    return buildEpisodeSelectSnapshot(this.episodeCards ?? [], {
      focusIndex: this.focusIndex
    });
  }

  refreshDebug() {
    const state = registerDebugScene(this, {
      save: this.save,
      mute: this.save?.mute ?? false,
      scene: {
        episodeSelect: this.getEpisodeSelectDOM()
      }
    });

    if (state) {
      state.debug.episodeSelectDOM = () => this.getEpisodeSelectDOM();
    }
  }
}
