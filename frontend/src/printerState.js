export function stateClass(state) {
  const value = (state || '').toLowerCase();
  if (/cancel|error|offline|closed|unavailable/.test(value)) return 'state-danger';
  if (/paus/.test(value)) return 'state-paused';
  if (/print|resum|operational/.test(value)) return 'state-ready';
  return 'state-neutral';
}
