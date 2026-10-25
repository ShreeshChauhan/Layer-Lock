
export const initialReadings = {
  cameraConfidence: 12,
  progress: 42.5
};

export function generateMockReadings(previous) {
  const change = (value, range) =>
    Math.max(
      0,
      Math.min(
        100,
        value + (Math.random() - 0.5) * range
      )
    );

  return {
    ...previous,
    cameraConfidence: change(
      previous.cameraConfidence,
      16
    )
  };
}

export function calculateRisk(readings) {
  return Math.round(
    Math.max(0, Math.min(100, readings.cameraConfidence))
  );
}

export function toBackendPayload(readings) {
  return {
    camera_confidence: readings.cameraConfidence
  };
}
