// Vite proxies /api and /auth to FastAPI during development.
export const API_BASE = "";

// HW7: the JWT lives in sessionStorage for this tab and is sent as a bearer token.
const TOKEN_KEY = "s0036_access_token";

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

export function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
