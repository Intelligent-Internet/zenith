#!/usr/bin/env node
/* global AbortController, clearTimeout, fetch, process, setTimeout */
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const LEVEL_ID_PATTERN = /^\d-\d{2}$/;
const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 4100;
const DEFAULT_SESSION = 'mh-m6-f05-s';
const DEFAULT_VIEWPORT = { width: 1280, height: 720 };
const FEATURE_SCREENSHOT_DIR = '/tmp/feature-m6-f05-strategies-for-all-levels';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function usage() {
  return [
    'Usage: node scripts/run_strategy.js <level-id> [--session <name>] [--base-url <url>]',
    '',
    'Replays tests/strategies/<level-id>.json through agent-browser mouse input.',
    'Strategy steps use: { "drag-vector": [x, y], "ability-tap-time": null|milliseconds }.'
  ].join('\n');
}

function parseArgs(argv) {
  const args = [...argv];
  const levelId = args.shift();
  const options = {
    baseUrl: `http://${DEFAULT_HOST}:${DEFAULT_PORT}/`,
    session: process.env.AGENT_BROWSER_SESSION || DEFAULT_SESSION,
    screenshotDir: process.env.STRATEGY_SCREENSHOT_DIR || FEATURE_SCREENSHOT_DIR,
    keepBrowser: false,
    noStartServer: false
  };

  while (args.length > 0) {
    const arg = args.shift();

    if (arg === '--base-url') {
      options.baseUrl = args.shift();
    } else if (arg === '--session') {
      options.session = args.shift();
    } else if (arg === '--screenshot-dir') {
      options.screenshotDir = args.shift();
    } else if (arg === '--keep-browser') {
      options.keepBrowser = true;
    } else if (arg === '--no-start-server') {
      options.noStartServer = true;
    } else if (arg === '--help' || arg === '-h') {
      console.log(usage());
      process.exit(0);
    } else {
      throw new Error(`Unknown option: ${arg}`);
    }
  }

  if (!LEVEL_ID_PATTERN.test(levelId ?? '')) {
    throw new Error(`Expected a level id like 1-01.\n${usage()}`);
  }

  if (!options.session) {
    throw new Error('agent-browser session must not be empty');
  }

  options.baseUrl = options.baseUrl.endsWith('/') ? options.baseUrl : `${options.baseUrl}/`;
  return { levelId, options };
}

function strategyPath(levelId) {
  return join(repoRoot, 'tests', 'strategies', `${levelId}.json`);
}

export function normalizeStrategyStep(step, index, levelId) {
  const dragVector = step?.['drag-vector'] ?? step?.dragVector;
  const abilityTapTime = step?.['ability-tap-time'] ?? step?.abilityTapTime ?? null;

  if (!Array.isArray(dragVector) || dragVector.length !== 2) {
    throw new Error(`${levelId} step ${index} must define "drag-vector": [x, y]`);
  }

  const dragX = Number(dragVector[0]);
  const dragY = Number(dragVector[1]);
  if (!Number.isFinite(dragX) || !Number.isFinite(dragY)) {
    throw new Error(`${levelId} step ${index} has a non-finite drag-vector`);
  }

  if (Math.hypot(dragX, dragY) <= 8) {
    throw new Error(`${levelId} step ${index} drag-vector is inside the tap dead zone`);
  }

  if (dragX > 0) {
    throw new Error(`${levelId} step ${index} pulls forward; strategies must pull back from the slingshot`);
  }

  const tapTime = abilityTapTime === null ? null : Number(abilityTapTime);
  if (tapTime !== null && (!Number.isFinite(tapTime) || tapTime < 0)) {
    throw new Error(`${levelId} step ${index} has an invalid ability-tap-time`);
  }

  return {
    dragVector: [dragX, dragY],
    abilityTapTime: tapTime
  };
}

export function loadStrategy(levelId) {
  const file = strategyPath(levelId);
  if (!existsSync(file)) {
    throw new Error(`Missing strategy file: ${file}`);
  }

  const parsed = JSON.parse(readFileSync(file, 'utf8'));
  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error(`${file} must contain a non-empty array`);
  }

  return parsed.map((step, index) => normalizeStrategyStep(step, index, levelId));
}

export function buildOpenLevelSetupCommands(levelId, baseUrl) {
  const levelUrl = new globalThis.URL(baseUrl);
  levelUrl.searchParams.set('level', levelId);

  return [
    ['open', baseUrl],
    ['storage', 'local', 'clear'],
    ['open', levelUrl.toString()]
  ];
}

function runProcess(command, args, {
  env = process.env,
  timeoutMs = 30000,
  rejectOnFailure = true
} = {}) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, {
      cwd: repoRoot,
      env,
      stdio: ['ignore', 'pipe', 'pipe']
    });
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => {
      child.kill('SIGTERM');
      rejectPromise(new Error(`${command} ${args.join(' ')} timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.stdout.on('data', (chunk) => {
      stdout += chunk;
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
    });
    child.on('error', (error) => {
      clearTimeout(timer);
      rejectPromise(error);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      const result = { code, stdout, stderr };

      if (code !== 0 && rejectOnFailure) {
        rejectPromise(new Error([
          `${command} ${args.join(' ')} exited ${code}`,
          stdout.trim(),
          stderr.trim()
        ].filter(Boolean).join('\n')));
        return;
      }

      resolvePromise(result);
    });
  });
}

async function browser(args, options = {}) {
  return runProcess('agent-browser', ['--session', options.session, ...args], {
    timeoutMs: options.timeoutMs ?? 30000,
    rejectOnFailure: options.rejectOnFailure ?? true
  });
}

function parseEval(stdout) {
  const trimmed = stdout.trim();
  if (!trimmed) {
    return null;
  }

  const parsed = JSON.parse(trimmed);
  return typeof parsed === 'string' ? JSON.parse(parsed) : parsed;
}

async function evalJson(expression, options) {
  const { stdout } = await browser(['eval', `JSON.stringify(${expression})`], options);
  return parseEval(stdout);
}

async function sleep(ms) {
  await new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

async function isServerHealthy(baseUrl) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1000);

  try {
    const response = await fetch(baseUrl, { signal: controller.signal });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function startDevServerIfNeeded({ baseUrl, noStartServer }) {
  if (await isServerHealthy(baseUrl)) {
    return null;
  }

  if (noStartServer) {
    throw new Error(`${baseUrl} is not healthy and --no-start-server was set`);
  }

  const child = spawn('npm', ['run', 'dev', '--', '--host', DEFAULT_HOST, '--port', String(DEFAULT_PORT)], {
    cwd: repoRoot,
    detached: true,
    env: {
      ...process.env,
      PORT: String(DEFAULT_PORT),
      ANGRY_BIRD_DEV: '1'
    },
    stdio: 'ignore'
  });
  child.unref();

  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (await isServerHealthy(baseUrl)) {
      return child;
    }
    await sleep(250);
  }

  stopDevServer(child);
  throw new Error(`Dev server did not become healthy at ${baseUrl}`);
}

function stopDevServer(child) {
  if (!child?.pid) {
    return;
  }

  try {
    process.kill(-child.pid, 'SIGTERM');
  } catch {
    try {
      child.kill('SIGTERM');
    } catch {
      // Best effort cleanup for a process this script started.
    }
  }
}

async function waitForGameReady(levelId, options) {
  await browser([
    'wait',
    '--fn',
    `window.__GAME__ && window.__GAME__.scene && window.__GAME__.scene.levelId === '${levelId}' && window.__GAME__.scene.bird`
  ], { ...options, timeoutMs: 30000 });
}

async function getPlayState(options) {
  return evalJson(`(() => {
    const game = window.__GAME__;
    const scene = game?.scene ?? {};
    return {
      key: scene.key ?? null,
      levelId: scene.levelId ?? null,
      pigsLeft: Number(scene.pigsLeft ?? game?.pigsLeft ?? 0),
      birdsLeft: Number(scene.birdsLeft ?? game?.birdsLeft ?? 0),
      settled: Boolean(scene.settled ?? game?.settled),
      bird: scene.bird ?? null,
      flyingBird: scene.flyingBird ?? null,
      endCard: scene.endCard ?? null,
      score: Number(game?.score ?? scene.score ?? 0),
      save: game?.save ?? null
    };
  })()`, options);
}

async function getPointerGeometry(dragVector, options) {
  const [dx, dy] = dragVector;

  return evalJson(`(() => {
    const canvas = document.querySelector('canvas');
    const rect = canvas.getBoundingClientRect();
    const game = window.__GAME__;
    const scene = game.scene;
    const camera = scene.cameras?.main ?? {};
    const scaleX = rect.width / 1280;
    const scaleY = rect.height / 720;
    const scrollX = Number(camera.scrollX ?? 0);
    const scrollY = Number(camera.scrollY ?? 0);
    const toScreen = (point) => ({
      x: Math.round(rect.left + (point.x - scrollX) * scaleX),
      y: Math.round(rect.top + (point.y - scrollY) * scaleY)
    });
    const anchor = scene.slingshot.anchor;
    const start = toScreen(anchor);
    const end = toScreen({ x: anchor.x + ${dx}, y: anchor.y + ${dy} });
    return {
      anchor,
      start,
      end,
      tap: {
        x: Math.round(rect.left + rect.width * 0.55),
        y: Math.round(rect.top + rect.height * 0.48)
      }
    };
  })()`, options);
}

async function waitForStepResolution(previousBirdsLeft, options) {
  const deadline = Date.now() + 12500;

  while (Date.now() < deadline) {
    const state = await getPlayState(options);
    if (state.endCard || state.pigsLeft === 0) {
      if (state.endCard) {
        return state;
      }
    }
    if (state.bird?.canDrag && state.birdsLeft < previousBirdsLeft && state.pigsLeft > 0) {
      return state;
    }
    if (!state.flyingBird && state.settled && state.birdsLeft === 0) {
      return state;
    }
    await sleep(350);
  }

  return getPlayState(options);
}

async function waitForFinalOutcome(levelId, options) {
  const deadline = Date.now() + 15000;
  let clearedCandidate = null;

  while (Date.now() < deadline) {
    const state = await getPlayState(options);
    if (state.endCard) {
      return state;
    }
    if (state.pigsLeft === 0 || state.save?.cleared?.includes(levelId)) {
      clearedCandidate = state;
    }
    await sleep(350);
  }

  return clearedCandidate ?? getPlayState(options);
}

async function launchStep(step, index, options) {
  const before = await getPlayState(options);
  if (!before.bird?.canDrag) {
    throw new Error(`Step ${index} cannot launch because no bird is draggable: ${JSON.stringify(before)}`);
  }

  const geometry = await getPointerGeometry(step.dragVector, options);
  const commands = [
    `mouse move ${geometry.start.x} ${geometry.start.y}`,
    'mouse down left',
    `mouse move ${geometry.end.x} ${geometry.end.y}`,
    'mouse up left'
  ];
  if (step.abilityTapTime !== null) {
    commands.push(
      `wait ${step.abilityTapTime}`,
      `mouse move ${geometry.tap.x} ${geometry.tap.y}`,
      'mouse down left',
      'mouse up left'
    );
  }

  await browser(['batch', '--bail', ...commands], {
    ...options,
    timeoutMs: Math.max(30000, (step.abilityTapTime ?? 0) + 5000)
  });

  return waitForStepResolution(before.birdsLeft, options);
}

async function openLevel(levelId, options) {
  await browser(['set', 'viewport', String(DEFAULT_VIEWPORT.width), String(DEFAULT_VIEWPORT.height)], options);
  for (const command of buildOpenLevelSetupCommands(levelId, options.baseUrl)) {
    await browser(command, options);
  }
  await waitForGameReady(levelId, options);
  await sleep(500);
}

function getFinalScore(state, levelId) {
  return Number(
    state.endCard?.finalScore
    ?? state.save?.bestScore?.[levelId]
    ?? state.score
    ?? 0
  );
}

export function isClearedEndState(state) {
  return state?.endCard?.outcome === 'cleared';
}

function assertCleared(state, levelId) {
  if (!isClearedEndState(state)) {
    throw new Error(`Strategy did not clear ${levelId}: ${JSON.stringify(state, null, 2)}`);
  }
}

async function saveEvidenceScreenshot(levelId, options) {
  mkdirSync(options.screenshotDir, { recursive: true });
  const screenshotPath = join(options.screenshotDir, `${levelId}-cleared.png`);
  await browser(['screenshot', screenshotPath], options);
  return screenshotPath;
}

export async function runStrategy(levelId, options) {
  const strategy = loadStrategy(levelId);
  let serverProcess = null;

  try {
    serverProcess = await startDevServerIfNeeded(options);
    await openLevel(levelId, options);

    let state = await getPlayState(options);
    for (const [index, step] of strategy.entries()) {
      if (
        state.endCard?.outcome === 'cleared'
        || state.pigsLeft === 0
        || state.save?.cleared?.includes(levelId)
      ) {
        break;
      }
      state = await launchStep(step, index, options);
    }

    state = await waitForFinalOutcome(levelId, options);
    assertCleared(state, levelId);
    const screenshotPath = await saveEvidenceScreenshot(levelId, options);
    const score = getFinalScore(state, levelId);

    return {
      levelId,
      score,
      pigsLeft: state.pigsLeft,
      screenshotPath
    };
  } finally {
    if (!options.keepBrowser) {
      try {
        await browser(['close'], {
          ...options,
          timeoutMs: 30000,
          rejectOnFailure: false
        });
      } catch (error) {
        console.warn(`Unable to close agent-browser session ${options.session}: ${error.message}`);
      }
    }
    stopDevServer(serverProcess);
  }
}

async function main() {
  const { levelId, options } = parseArgs(process.argv.slice(2));
  const result = await runStrategy(levelId, options);

  console.log([
    `PASS ${result.levelId}`,
    `score=${result.score}`,
    `pigsLeft=${result.pigsLeft}`,
    `screenshot=${result.screenshotPath}`
  ].join(' '));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error.stack || error.message || String(error));
    process.exit(1);
  });
}
