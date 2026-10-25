// Vite proxies /api to FastAPI. Remote browsers use the app host, not their own localhost.
// Production hosting should also proxy /api, or set VITE_API_URL at build time.
export const API = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');
