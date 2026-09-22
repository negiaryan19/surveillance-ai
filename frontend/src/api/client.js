/**
 * HTTP client for the Chanakya backend.
 *
 * Two kinds of request exist and they authenticate differently:
 *  - `apiFetch` (JSON calls) sends the token as an `Authorization: Bearer` header.
 *  - `mediaUrl` (URLs handed to <img>, <video>, EventSource and download links) cannot set
 *    headers, so the token travels as a `?token=` query parameter. The backend redacts it
 *    from its access log.
 */

const TOKEN_KEY = 'chanakya_token';
const DEV_BACKEND_URL = 'http://127.0.0.1:5001';

/**
 * Base URL of the backend. A production build is served by Flask itself, so it must be
 * same-origin (empty base, relative URLs). `??` rather than `||` lets a deployment set
 * VITE_API_URL="" explicitly to force same-origin in development too.
 */
export const BACKEND_URL = (
  import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? '' : DEV_BACKEND_URL)
).replace(/\/+$/, '');

/** Human-readable backend location for banners and the About tab. */
export function backendLabel() {
  if (BACKEND_URL) return BACKEND_URL;
  return typeof window === 'undefined' ? 'this origin' : window.location.origin;
}

// Fallback for browsers where localStorage throws (private mode, blocked site data):
// the token then lives for the lifetime of the page instead of breaking login.
let memoryToken = '';

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || memoryToken;
  } catch {
    return memoryToken;
  }
}

export function setToken(token) {
  memoryToken = token || '';
  try {
    if (memoryToken) window.localStorage.setItem(TOKEN_KEY, memoryToken);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage unavailable: the in-memory copy above keeps this session working.
  }
}

export function clearToken() {
  setToken('');
}

export class ApiError extends Error {
  /**
   * @param {number} status HTTP status, or 0 when the backend could not be reached at all.
   * @param {string} message
   */
  constructor(status, message) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** True for the rejection produced by aborting a fetch; callers ignore these. */
export function isAbortError(error) {
  return error?.name === 'AbortError';
}

function joinUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  return `${BACKEND_URL}${path.startsWith('/') ? '' : '/'}${path}`;
}

function appendQuery(url, query) {
  if (!query) return url;
  if (url.endsWith('?') || url.endsWith('&')) return `${url}${query}`;
  return `${url}${url.includes('?') ? '&' : '?'}${query}`;
}

/**
 * URL for media elements, EventSource and download links.
 *
 * `path` may already carry a query string (e.g. `clip_url + "?download=1"`); extra `params`
 * and the token are appended with the correct separator. With an empty base the result is
 * a root-relative URL, which is what the Flask-served production build needs.
 *
 * @param {string} path
 * @param {Record<string, string | number | null | undefined>} [params]
 */
export function mediaUrl(path, params) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null) query.set(key, String(value));
  }
  const token = getToken();
  if (token) query.set('token', token);
  return appendQuery(joinUrl(path), query.toString());
}

function isPlainBody(body) {
  return body !== undefined && body !== null && !(body instanceof FormData) && typeof body !== 'string';
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * JSON request against the backend.
 *
 * @param {string} path e.g. "/api/incidents?limit=10"
 * @param {object} [options]
 * @param {string} [options.method]
 * @param {object | FormData} [options.body] plain objects are sent as JSON; FormData as multipart
 * @param {AbortSignal} [options.signal]
 * @param {string} [options.token] overrides the stored token (LoginGate verifies before saving)
 * @returns {Promise<any>} parsed JSON body (null when the response has none)
 * @throws {ApiError} status 0 = unreachable, otherwise the HTTP status
 */
export async function apiFetch(path, { method = 'GET', body, signal, token } = {}) {
  const headers = { Accept: 'application/json' };
  const bearer = token ?? getToken();
  if (bearer) headers.Authorization = `Bearer ${bearer}`;

  let payload = body;
  if (isPlainBody(body)) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(joinUrl(path), { method, headers, body: payload, signal });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(0, 'Backend unreachable');
  }

  const data = await readJson(response);
  if (!response.ok) {
    throw new ApiError(response.status, data?.error || response.statusText || `HTTP ${response.status}`);
  }
  return data;
}
