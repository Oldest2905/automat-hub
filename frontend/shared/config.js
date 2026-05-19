/**
 * config.js — Shared Configuration for ALL frontend pages
 * 
 * HOW THE API_URL WORKS:
 * - In development (localhost): API is at http://localhost:8000
 * - On Railway / production: The frontend and backend are on the SAME server
 *   so we use an empty string "" which means "same domain"
 * - This means you NEVER need to change this file when deploying
 */

/**
 * config.js — Shared Configuration for ALL frontend pages
 */

const CONFIG = {
  // Auto-detects environment. Empty string = same server as frontend.
  API_URL: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8000'
    : '', 

  // WebSocket URL - auto-detects secure vs insecure
  get WS_URL() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
      ? 'localhost:8000'
      : window.location.host;
    return `${protocol}//${host}`;
  },

  GOOGLE_MAPS_KEY: 'YOUR_GOOGLE_MAPS_KEY_HERE',
  FLUTTERWAVE_PUBLIC_KEY: 'FLWPUBK_TEST-xxxxxxxxxxxxxxxx', 

  APP_NAME: 'The Automat Hub',
  APP_VERSION: '1.0.0',

  // Consistent localStorage keys used by all dashboards
  TOKEN_KEY: 'automat_token',
  USER_KEY:  'automat_user',
};

/* ─── API HELPER ──────────────────────────────────────────── */
const API = {
  async get(path) {
    const token = localStorage.getItem(CONFIG.TOKEN_KEY);
    try {
      const res = await fetch(`${CONFIG.API_URL}${path}`, {
        headers: {
          'Authorization': token ? `Bearer ${token}` : '',
          'Content-Type': 'application/json',
        }
      });
      if (res.status === 401) { Auth.logout(); return null; }
      return res.json();
    } catch(e) {
      console.error(`API GET ${path} failed:`, e);
      return null;
    }
  },

  async post(path, body = {}) {
    const token = localStorage.getItem(CONFIG.TOKEN_KEY);
    try {
      const res = await fetch(`${CONFIG.API_URL}${path}`, {
        method: 'POST',
        headers: {
          'Authorization': token ? `Bearer ${token}` : '',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body)
      });
      if (res.status === 401) { Auth.logout(); return null; }
      return res.json();
    } catch(e) {
      console.error(`API POST ${path} failed:`, e);
      return null;
    }
  },

  async put(path, body = {}) {
    const token = localStorage.getItem(CONFIG.TOKEN_KEY);
    try {
      const res = await fetch(`${CONFIG.API_URL}${path}`, {
        method: 'PUT',
        headers: {
          'Authorization': token ? `Bearer ${token}` : '',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body)
      });
      return res.json();
    } catch(e) {
      console.error(`API PUT ${path} failed:`, e);
      return null;
    }
  },

  async del(path) {
    const token = localStorage.getItem(CONFIG.TOKEN_KEY);
    try {
      const res = await fetch(`${CONFIG.API_URL}${path}`, {
        method: 'DELETE',
        headers: { 'Authorization': token ? `Bearer ${token}` : '' }
      });
      return res.json();
    } catch(e) { return null; }
  }
};

/* ─── AUTH HELPER ─────────────────────────────────────────── */
const Auth = {
  isLoggedIn() { return !!localStorage.getItem(CONFIG.TOKEN_KEY); },

  getUser() {
    try { return JSON.parse(localStorage.getItem(CONFIG.USER_KEY) || '{}'); }
    catch { return {}; }
  },

  getRole() { return this.getUser().role || ''; },

  saveLogin(token, user) {
    localStorage.setItem(CONFIG.TOKEN_KEY, token);
    localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(user));
  },

  logout() {
    localStorage.removeItem(CONFIG.TOKEN_KEY);
    localStorage.removeItem(CONFIG.USER_KEY);
    window.location.href = '/frontend/auth/login.html';
  },

  routeByRole() {
    const role = this.getRole();
    const routes = {
      admin:         '/frontend/admin/index.html',
      inspector:     '/frontend/inspector/index.html',
      fleet_owner:   '/frontend/fleet/index.html',
      private_owner: '/frontend/user/index.html',
      reseller:      '/frontend/reseller/index.html',
      mechanic:      '/frontend/workshop/index.html',
    };
    window.location.href = routes[role] || '/frontend/auth/login.html';
  }
};

/* ─── UI HELPERS ──────────────────────────────────────────── */
const UI = {
  toast(message, type = 'info') {
    const colors = { success:'#22d07a', error:'#f0503a', warning:'#f0c03a', info:'#3a8ff0' };
    const t = document.createElement('div');
    t.style.cssText = `position:fixed;bottom:24px;right:24px;z-index:9999;background:#1a1a24;border:1px solid ${colors[type]};color:#eeeaf2;padding:14px 20px;border-radius:10px;font-family:'Familjen Grotesk',sans-serif;font-size:14px;font-weight:500;box-shadow:0 8px 32px rgba(0,0,0,0.4);animation:slideIn 0.3s ease;max-width:320px;line-height:1.4;`;
    t.innerHTML = `<span style="color:${colors[type]};margin-right:8px">●</span>${message}`;
    document.body.appendChild(t);
    setTimeout(() => { t.style.opacity='0'; t.style.transition='opacity 0.3s'; setTimeout(()=>t.remove(),300); }, 3500);
  },

  badge(text, type='default') {
    const classes = {success:'badge-green',danger:'badge-red',warning:'badge-yellow',info:'badge-blue',orange:'badge-orange',default:'badge-muted'};
    return `<span class="badge ${classes[type]||'badge-muted'}">${text}</span>`;
  },

  spinner(size=24) {
    return `<div style="width:${size}px;height:${size}px;border:2px solid rgba(255,255,255,0.2);border-top-color:#f05a1e;border-radius:50%;animation:spin 0.8s linear infinite;display:inline-block;vertical-align:middle;"></div>`;
  },

  loading(containerId, msg='Loading...') {
    const el = document.getElementById(containerId);
    if (el) el.innerHTML = `<div style="padding:40px;text-align:center;color:#6b6b80;">${this.spinner()} <span style="margin-left:12px;font-size:13px;">${msg}</span></div>`;
  },

  empty(containerId, msg='No data found', icon='📭') {
    const el = document.getElementById(containerId);
    if (el) el.innerHTML = `<div style="padding:40px;text-align:center;color:#6b6b80;"><div style="font-size:36px;margin-bottom:12px;">${icon}</div><div style="font-size:13px;">${msg}</div></div>`;
  },

  // Show/hide a loading overlay on a button
  btnLoading(btn, loading, originalText) {
    if (typeof btn === 'string') btn = document.getElementById(btn);
    if (!btn) return;
    if (loading) {
      btn._originalText = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `${this.spinner(16)} &nbsp;Loading...`;
    } else {
      btn.disabled = false;
      btn.innerHTML = originalText || btn._originalText || 'Submit';
    }
  }
};

// Inject global CSS keyframes
const _style = document.createElement('style');
_style.textContent = `
@keyframes spin    { to { transform: rotate(360deg); } }
@keyframes slideIn { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
@keyframes fadeUp  { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
@keyframes fadeIn  { from { opacity:0; } to { opacity:1; } }
@keyframes blink   { 0%,100%{opacity:1} 50%{opacity:0.3} }
`;
document.head.appendChild(_style);
