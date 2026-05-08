export function clampDragVector(vector, clampRadius) {
  const rawX = Number.isFinite(vector?.x) ? vector.x : 0;
  const rawY = Number.isFinite(vector?.y) ? vector.y : 0;
  const rawDistance = Math.hypot(rawX, rawY);

  if (!Number.isFinite(clampRadius) || clampRadius <= 0 || rawDistance === 0) {
    return {
      x: 0,
      y: 0,
      distance: 0,
      rawDistance,
      clamped: false,
      scale: 1
    };
  }

  const scale = rawDistance > clampRadius ? clampRadius / rawDistance : 1;
  const x = rawX * scale;
  const y = rawY * scale;

  return {
    x,
    y,
    distance: Math.hypot(x, y),
    rawDistance,
    clamped: scale < 1,
    scale
  };
}

export function computeLaunchVelocity(dragVector, {
  clampRadius,
  power
}) {
  const clamped = clampDragVector(dragVector, clampRadius);

  return {
    x: -clamped.x * power,
    y: -clamped.y * power,
    speed: clamped.distance * power,
    drag: clamped
  };
}

export function predictTrajectory({
  origin,
  velocity,
  gravityPerSecond,
  sampleCount,
  sampleStep,
  velocityScale = 60
}) {
  const startX = Number.isFinite(origin?.x) ? origin.x : 0;
  const startY = Number.isFinite(origin?.y) ? origin.y : 0;
  const vx = Number.isFinite(velocity?.x) ? velocity.x : 0;
  const vy = Number.isFinite(velocity?.y) ? velocity.y : 0;
  const gravity = Number.isFinite(gravityPerSecond) ? gravityPerSecond : 0;
  const count = Math.max(0, Math.floor(sampleCount));
  const dt = Number.isFinite(sampleStep) && sampleStep > 0 ? sampleStep : 1 / 30;

  return Array.from({ length: count }, (_, index) => {
    const time = index * dt;

    return {
      index,
      time,
      x: startX + vx * velocityScale * time,
      y: startY + vy * velocityScale * time + 0.5 * gravity * time * time
    };
  });
}
