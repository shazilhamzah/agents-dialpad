'use strict';

/* ===================== helpers ===================== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const app = $('#app');
const esc = Markdown.escapeHtml;
const LS = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('show'), 3200);
}

/* One icon family: 24px grid, 1.75 stroke, round caps. Decorative, so hidden from screen readers. */
const ICON = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
  down: '<path d="M12 5v14M19 12l-7 7-7-7"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  warn: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01"/>',
  term: '<path d="m4 17 6-6-6-6M12 19h8"/>',
  chev: '<path d="m6 9 6 6 6-6"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  qr: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3zM21 14v.01M14 21h.01M17 21h4v-4"/>',
  pin: '<path d="M12 17v5M9 10.76V6h6v4.76l2 2.24v2H7v-2z"/><path d="M9 6V3h6v3"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  diff: '<path d="M12 3v14M5 10h14M5 21h14"/>',
  clip: '<path d="m21 12-8.5 8.5a6 6 0 0 1-8.5-8.5l9-9a4 4 0 0 1 5.66 5.66l-9 9a2 2 0 0 1-2.83-2.83L15 7"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
  phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  fingerprint: '<path d="M12 10a2 2 0 0 0-2 2c0 1.02-.1 2.51-.26 3M14 13.12c0 2.38 0 6.38-1 8.88M2 12a10 10 0 0 1 18-6M2 16a14.66 14.66 0 0 1 3-4M22 12A10 10 0 0 0 12 2a10 10 0 0 0-6.88 2.77M17 13.5a6 6 0 0 0-5-5.5M19 17.5a14 14 0 0 0 .5-3.5M6 21a10 10 0 0 1-.5-3.5c0-1.78.33-3.5 1-5"/>',
};
const icon = (n) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICON[n]}</svg>`;

const MODE_TEXT = { readonly: 'read-only', edit: 'can edit', ask: 'ask before commands', full: 'full access' };
const pendingApprovals = new Set();

/* ===================== token + API ===================== */
let token = LS.get('ag_token');
{
  const m = location.hash.match(/token=([^&]+)/);       // arrives in the URL fragment, never in a query string
  if (m) {
    token = decodeURIComponent(m[1]); LS.set('ag_token', token);
    history.replaceState(null, '', location.pathname + location.search);
  }
}
class AuthError extends Error {}
async function api(path, opts = {}) {
  const unlock = sessionStorage.getItem('ag_unlock');
  const headers = {
    Authorization: 'Bearer ' + token,
    ...(unlock ? { 'X-Unlock': unlock } : {}),
    ...(opts.headers || {}),
    ...(opts.body ? { 'Content-Type': 'application/json' } : {}),
  };
  const r = await fetch('/api' + path, { ...opts, headers });
  if (r.status === 401) throw new AuthError();
  if (r.status === 423) {
    await promptUnlock();
    const newUnlock = sessionStorage.getItem('ag_unlock');
    const retryHeaders = {
      ...headers,
      ...(newUnlock ? { 'X-Unlock': newUnlock } : {}),
    };
    const r2 = await fetch('/api' + path, { ...opts, headers: retryHeaders });
    if (r2.status === 401) throw new AuthError();
    if (!r2.ok) {
      let msg = r2.statusText;
      try { msg = (await r2.json()).detail || msg; } catch { /* not json */ }
      throw new Error(msg);
    }
    return r2;
  }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  return r;
}
const getJSON = async (p, o) => (await api(p, o)).json();
async function uploadFile(chatId, file) {
  const unlock = sessionStorage.getItem('ag_unlock');
  const headers = {
    Authorization: 'Bearer ' + token,
    ...(unlock ? { 'X-Unlock': unlock } : {}),
    'Content-Type': file.type || 'application/octet-stream',
  };
  const r = await fetch('/api/chats/' + encodeURIComponent(chatId) + '/uploads?name=' + encodeURIComponent(file.name), {
    method: 'PUT',
    headers,
    body: file,
  });
  if (r.status === 401) throw new AuthError();
  if (r.status === 423) {
    await promptUnlock();
    const newUnlock = sessionStorage.getItem('ag_unlock');
    if (newUnlock) headers['X-Unlock'] = newUnlock;
    const r2 = await fetch('/api/chats/' + encodeURIComponent(chatId) + '/uploads?name=' + encodeURIComponent(file.name), {
      method: 'PUT',
      headers,
      body: file,
    });
    if (r2.status === 401) throw new AuthError();
    if (!r2.ok) {
      let msg = r2.statusText;
      try { msg = (await r2.json()).detail || msg; } catch { /* not json */ }
      throw new Error(msg);
    }
    return r2.json();
  }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  return r.json();
}
const postJSON = async (p, b) => (await api(p, { method: 'POST', body: JSON.stringify(b) })).json();
function forgetToken() { LS.del('ag_token'); token = null; }

/* ===================== state ===================== */
const state = {
  chats: [],
  sig: '',
  info: null,
  drafts: {},
  openTools: new Set(),
  expandedApprovals: new Set(),
  query: '',
  quick: {},
  lockEnabled: false,
  lockIdleMinutes: 5,
  lockChecked: false,
};
let cur = null;           // the open chat view (see createChatView)

/* ===================== sheets, menu, confirm ===================== */
function openSheet(html, label) {
  $$('dialog.sheet:not([open])').forEach((d) => d.remove());   // a closed sheet whose 'close' event is still pending
  const dlg = document.createElement('dialog');
  dlg.className = 'sheet';
  if (label) dlg.setAttribute('aria-label', label);
  dlg.innerHTML = `<div class="grab" aria-hidden="true"></div><div class="sheet-body">${html}</div>`;
  document.body.appendChild(dlg);
  dlg.addEventListener('close', () => dlg.remove());
  dlg.addEventListener('click', (e) => {
    if (e.target === dlg || e.target.closest('[data-close]')) dlg.close();   // tap the scrim, or any Close/Done/Cancel button
  });
  const grab = $('.grab', dlg);                                                     // drag the grabber down to dismiss
  let y0 = null;
  grab.addEventListener('pointerdown', (e) => { y0 = e.clientY; grab.setPointerCapture(e.pointerId); dlg.style.animation = 'none'; dlg.style.transition = 'none'; });
  grab.addEventListener('pointermove', (e) => { if (y0 !== null) dlg.style.transform = `translateY(${Math.max(0, e.clientY - y0)}px)`; });
  const end = (e) => {
    if (y0 === null) return;
    const dy = e.clientY - y0; y0 = null; dlg.style.transition = '';
    if (dy > 90) dlg.close(); else dlg.style.transform = '';
  };
  grab.addEventListener('pointerup', end); grab.addEventListener('pointercancel', end);
  dlg.showModal();
  return dlg;
}

function confirmSheet({ title, body, confirm, danger }) {
  return new Promise((resolve) => {
    const dlg = openSheet(`<h2>${esc(title)}</h2><p class="lede">${esc(body)}</p>
      <div class="actions"><button class="btn secondary" type="button" data-r="0">Cancel</button>
      <button class="btn ${danger ? 'danger' : ''}" type="button" data-r="1">${esc(confirm)}</button></div>`, title);
    let answer = false;
    dlg.addEventListener('click', (e) => { const b = e.target.closest('[data-r]'); if (b) { answer = b.dataset.r === '1'; dlg.close(); } });
    dlg.addEventListener('close', () => resolve(answer));
  });
}

let menuAnchor = null;
function closeMenu() {
  const m = $('#menu'); if (!m) return;
  if (menuAnchor) menuAnchor.setAttribute('aria-expanded', 'false');
  menuAnchor = null;
  m.remove(); document.removeEventListener('pointerdown', onOutside, true);
}
function onOutside(e) { if (!e.target.closest('#menu') && !(menuAnchor && menuAnchor.contains(e.target))) closeMenu(); }
function openMenu(anchor, items) {
  closeMenu();
  menuAnchor = anchor;
  const menu = document.createElement('div');
  menu.id = 'menu'; menu.className = 'menu'; menu.setAttribute('role', 'menu');
  menu.innerHTML = items.map((it, i) =>
    `<button type="button" role="menuitem" data-i="${i}" class="${it.danger ? 'danger' : ''}">${icon(it.icon)}<span>${esc(it.label)}</span></button>`).join('');
  anchor.closest('.bar').appendChild(menu);
  anchor.setAttribute('aria-expanded', 'true');
  const btns = [...menu.querySelectorAll('button')]; btns[0].focus();
  menu.addEventListener('click', (e) => { const b = e.target.closest('[data-i]'); if (b) { closeMenu(); items[+b.dataset.i].run(); } });
  menu.addEventListener('keydown', (e) => {
    const i = btns.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); btns[(i + 1) % btns.length].focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); btns[(i - 1 + btns.length) % btns.length].focus(); }
    else if (e.key === 'Escape') { e.preventDefault(); closeMenu(); anchor.focus(); }
    else if (e.key === 'Tab') closeMenu();
  });
  setTimeout(() => document.addEventListener('pointerdown', onOutside, true), 0);
}

/* ===================== small formatters ===================== */
function timeAgo(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}
function resetsIn(iso) {
  const s = (Date.parse(iso) - Date.now()) / 1000;
  if (!iso || Number.isNaN(s)) return '';
  if (s <= 0) return 'Resets now';
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return 'Resets in ' + (d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`);
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* fall back */ }
  try {
    const t = document.createElement('textarea'); t.value = text; t.style.position = 'fixed'; t.style.opacity = '0';
    document.body.appendChild(t); t.select(); const ok = document.execCommand('copy'); t.remove(); return ok;
  } catch { return false; }
}

/* ===================== login ===================== */
function showLogin(msg) {
  teardownChat();
  app.innerHTML = `<form class="login" id="login">
      <h1><img class="login-logo" src="/logo-lockup.svg" alt="agents-dialpad"></h1>
      <p>Paste the access token printed when the gateway starts, or open the full link it printed.</p>
      <label for="tok">Access token</label>
      <input id="tok" name="token" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" required>
      <div class="err" role="alert">${esc(msg || '')}</div>
      <button class="btn" type="submit">Connect</button>
    </form>`;
  $('#login').onsubmit = (e) => { e.preventDefault(); token = $('#tok').value.trim(); LS.set('ag_token', token); route(); };
  $('#tok').focus();
}

/* ===================== shell + chat list ===================== */
function mountShell() {
  if ($('.shell')) return;
  app.innerHTML = `<div class="shell" data-view="list" data-running="false">
    <aside class="side" aria-label="Chats">
      <header class="bar">
        <div class="titles"><h1 class="brand"><img src="/logo-mark.svg" alt="" width="24" height="24"><span>agents-dialpad</span></h1></div>
        <button class="icon-btn" id="btn-sched" type="button" aria-label="Schedules" style="display:none">${icon('clock')}</button>
        <button class="icon-btn" id="btn-limits" type="button" aria-label="Usage limits">${icon('gauge')}</button>
        <button class="icon-btn" id="btn-side-more" type="button" aria-label="More" aria-haspopup="menu" aria-expanded="false">${icon('more')}</button>
        <button class="icon-btn" id="btn-new" type="button" aria-label="New chat">${icon('plus')}</button>
      </header>
      <div class="search">${icon('search')}<label class="sr" for="q">Search chats</label><input id="q" type="search" placeholder="Search chats" autocomplete="off" enterkeyhint="search"></div>
      <nav class="chats" id="chat-list" aria-label="Chat list"></nav>
    </aside>
    <main class="pane" id="pane"></main>
  </div>`;
  ensureLockOverlay();
  $('#btn-sched').onclick = openSchedules;
  $('#btn-limits').onclick = openLimits;
  $('#btn-side-more').onclick = (e) => { if ($('#menu')) return closeMenu(); openMenu(e.currentTarget, sideMenuItems()); };
  $('#btn-new').onclick = openNewChat;
  const qInput = $('#q');
  let qTimer = null;
  qInput.oninput = () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(async () => {
      state.query = qInput.value.trim();
      if (!state.query) {
        renderList();
      } else {
        try {
          const d = await getJSON('/chats?q=' + encodeURIComponent(state.query));
          renderSearchResults(d.chats);
        } catch (e) { handleErr(e); }
      }
    }, 250);
  };
  renderList();
  loadInfo().then((info) => {
    if ($('#btn-sched')) $('#btn-sched').style.display = (info && info.has_schedules) ? '' : 'none';
    renderList();
    updateHeader();
  }).catch(() => {});   // agent + model names for the list and header
}

function b64urlToUint8(str) {
  const pad = '='.repeat((4 - str.length % 4) % 4);
  const base64 = (str + pad).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function pushSupported() {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

async function enablePush() {
  if (!pushSupported()) {
    if (/iPhone|iPad/.test(navigator.userAgent) && !matchMedia('(display-mode: standalone)').matches) {
      toast('On iPhone, add agents-dialpad to your Home Screen first, then open it from there.');
    } else {
      toast("This browser can't receive notifications.");
    }
    return;
  }
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') {
    toast('Notifications are blocked in your browser settings.');
    return;
  }
  let keyData;
  try {
    keyData = await getJSON('/push/key');
  } catch (e) {
    return handleErr(e);
  }
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: b64urlToUint8(keyData.publicKey),
    });
    const label = ((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || 'device').slice(0, 40);
    await api('/push/subscribe', {
      method: 'POST',
      body: JSON.stringify({ subscription: sub.toJSON(), label }),
    });
    LS.set('ag_push', '1');
    toast('Notifications on');
  } catch (err) {
    handleErr(err);
  }
}

async function disablePush() {
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await api('/push/unsubscribe', {
        method: 'POST',
        body: JSON.stringify({ endpoint: sub.endpoint }),
      });
      await sub.unsubscribe();
    }
  } catch {
    /* ignore */
  }
  LS.del('ag_push');
  toast('Notifications off');
}

async function sendTestPush() {
  try {
    const r = await getJSON('/push/test', { method: 'POST' });
    toast(r.sent > 0 ? 'Test notification sent' : 'No devices subscribed');
  } catch (e) {
    handleErr(e);
  }
}

function sideMenuItems() {
  const hasPush = LS.get('ag_push') === '1';
  const items = [
    { icon: 'qr', label: 'Pair a device', run: openPair },
    { icon: 'phone', label: 'Devices', run: openDevices },
    { icon: 'lock', label: 'App lock', run: openAppLock },
  ];
  if (hasPush) {
    items.push({ icon: 'bell', label: 'Turn off notifications', run: disablePush });
    items.push({ icon: 'bell', label: 'Send a test notification', run: sendTestPush });
  } else {
    items.push({ icon: 'bell', label: 'Turn on notifications', run: enablePush });
  }
  if (state.info && state.info.has_schedules) {
    items.push({ icon: 'clock', label: 'Schedules', run: openSchedules });
  }
  return items;
}
async function openDevices() {
  let data;
  try {
    data = await getJSON('/devices');
  } catch (e) {
    return handleErr(e);
  }
  const isOwner = (data.me === 'owner');
  const dlg = openSheet(`
    <h2>Devices</h2>
    <p class="lede">Each paired phone or tablet has its own token.</p>
    <div class="devices-list" id="dev-list"></div>
    ${isOwner ? '<button class="btn" type="button" id="btn-add-dev" style="width:100%; margin-top:12px;">Add a device</button>' : '<p class="note">Devices can only be added or revoked from the computer.</p>'}
    <div class="actions"><button class="btn secondary" type="button" data-close>Close</button></div>
  `, 'Devices');
  $('[data-close]', dlg).onclick = () => dlg.close();

  function renderDevList(devs) {
    const listEl = $('#dev-list', dlg);
    if (!devs.length) {
      listEl.innerHTML = '<p class="note">No devices paired yet.</p>';
      return;
    }
    listEl.innerHTML = devs.map(d => {
      const isThis = (d.id === data.me);
      const seen = d.last_seen ? `Last used ${timeAgo(d.last_seen)}` : 'Never used';
      return `
        <div class="device-row">
          <div class="device-info">
            <span class="device-name">${esc(d.name)}${isThis ? ' <span class="this-tag">(This device)</span>' : ''}</span>
            <span class="device-seen">${esc(seen)}</span>
          </div>
          ${isOwner ? `<button class="btn secondary danger btn-sm" type="button" data-revoke="${esc(d.id)}" data-name="${esc(d.name)}">Revoke</button>` : ''}
        </div>
      `;
    }).join('');

    if (isOwner) {
      $$('[data-revoke]', listEl).forEach(btn => {
        btn.onclick = async () => {
          const name = btn.dataset.name;
          const id = btn.dataset.revoke;
          const ok = await confirmSheet({
            title: 'Revoke device?',
            body: `Revoke ${name}? It will be signed out immediately.`,
            confirm: 'Revoke',
            danger: true,
          });
          if (!ok) return;
          try {
            await api(`/devices/${encodeURIComponent(id)}`, { method: 'DELETE' });
            toast('Device revoked');
            data.devices = data.devices.filter(x => x.id !== id);
            renderDevList(data.devices);
          } catch (err) {
            handleErr(err);
          }
        };
      });
    }
  }

  renderDevList(data.devices);

  if (isOwner) {
    $('#btn-add-dev', dlg).onclick = () => {
      dlg.close();
      const nameDlg = openSheet(`<form id="f-dev"><h2>Add a device</h2>
        <label for="d-name">Device name</label>
        <input id="d-name" type="text" maxlength="40" placeholder="My phone" required>
        <div class="actions"><button class="btn secondary" type="button" data-close>Cancel</button><button class="btn" type="submit" id="d-go">Create code</button></div></form>`, 'Add a device');
      $('#f-dev', nameDlg).onsubmit = async (e) => {
        e.preventDefault();
        const name = $('#d-name', nameDlg).value.trim();
        if (!name) return;
        const go = $('#d-go', nameDlg); go.setAttribute('aria-busy', 'true');
        try {
          const res = await getJSON('/devices', { method: 'POST', body: JSON.stringify({ name }) });
          nameDlg.close();
          openSheet(`
            <h2>Pair device</h2>
            <p class="lede">Scan with your phone's camera to connect <b>${esc(res.device.name)}</b>. Anyone who scans this code can use your agents, so don't share it.</p>
            <div class="qr"><img src="${esc(res.qr)}" alt="QR code to pair" width="240" height="240"></div>
            <p class="note"><a href="${esc(res.url)}" target="_blank" rel="noopener">Open link directly</a></p>
            <div class="actions"><button class="btn" type="button" data-close>Done</button></div>
          `, 'Pair device');
        } catch (err) {
          go.removeAttribute('aria-busy');
          handleErr(err);
        }
      };
    };
  }
}

async function openPair() {
  let data;
  try { data = await getJSON('/pair'); } catch (e) { return handleErr(e); }
  const dlg = openSheet(`<h2>Pair a device</h2>
    <p class="lede">Scan with your phone's camera. Anyone who scans this code can use your agents, so don't share it.</p>
    <div class="qr"><img src="${esc(data.qr)}" alt="QR code that opens agents-dialpad on another device" width="240" height="240"></div>
    ${!data.remote ? '<p class="note">Phone access isn\'t published yet, so this code only works on this computer. Run <code>tailscale serve --bg --https=8443 8787</code> on the computer (see docs/remote-access.md).</p>' : ''}
    <div class="actions"><button class="btn secondary" type="button" id="pair-copy">Copy link</button><button class="btn" type="button" data-close>Done</button></div>`, 'Pair a device');
  $('[data-close]', dlg).onclick = () => dlg.close();
  $('#pair-copy', dlg).onclick = async () => { if (await copyText(data.url)) toast('Link copied'); };
}

/* ===================== app lock ===================== */
function bufferToBase64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let str = '';
  for (const char of bytes) str += String.fromCharCode(char);
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

function base64urlToBuffer(base64url) {
  let b64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
  while (b64.length % 4) b64 += '=';
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function ensureLockOverlay() {
  if ($('#lock-overlay')) return;
  const overlay = document.createElement('div');
  overlay.id = 'lock-overlay';
  overlay.className = 'lock-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', 'App locked');
  overlay.setAttribute('hidden', '');
  overlay.innerHTML = `
    <div class="lock-card">
      <div class="lock-badge">
        <img src="/logo-mark.svg" alt="" class="lock-icon" width="52" height="52">
      </div>
      <h2>Locked</h2>
      <p class="lock-msg" id="lock-msg">Unlock to continue.</p>
      <button id="btn-unlock" class="btn primary" type="button">
        ${icon('fingerprint')}<span>Unlock</span>
      </button>
    </div>
  `;
  document.body.appendChild(overlay);
}

let activeUnlockPromise = null;
function promptUnlock() {
  if (activeUnlockPromise) return activeUnlockPromise;
  ensureLockOverlay();
  const overlay = $('#lock-overlay');
  document.body.classList.add('is-locked');
  overlay.removeAttribute('hidden');
  const btn = $('#btn-unlock');
  const msg = $('#lock-msg');
  try {
    if (window.matchMedia && !window.matchMedia('(pointer: coarse)').matches) {
      btn.focus({ focusVisible: false });
    }
  } catch {}

  activeUnlockPromise = new Promise((resolve) => {
    async function doUnlock() {
      try {
        btn.disabled = true;
        btn.innerHTML = `<span class="spin"></span><span>Waiting for fingerprint or PIN…</span>`;
        if (msg) msg.textContent = 'Touch your fingerprint sensor or enter device PIN…';

        const optsRes = await fetch('/api/lock/unlock/options', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        });
        if (optsRes.status === 401) throw new AuthError();
        if (optsRes.status === 429) {
          toast('Too many failed attempts. Try again later.');
          return;
        }
        if (!optsRes.ok) {
          let err = optsRes.statusText;
          try { err = (await optsRes.json()).detail || err; } catch {}
          throw new Error(err);
        }
        const data = await optsRes.json();
        const chalId = data.challenge_id;
        const opts = data.options || data;
        opts.challenge = base64urlToBuffer(opts.challenge);
        if (opts.allowCredentials) {
          opts.allowCredentials.forEach(c => c.id = base64urlToBuffer(c.id));
        }

        const assertion = await navigator.credentials.get({ publicKey: opts });
        const assertionJSON = {
          id: assertion.id,
          rawId: bufferToBase64url(assertion.rawId),
          type: assertion.type,
          response: {
            authenticatorData: bufferToBase64url(assertion.response.authenticatorData),
            clientDataJSON: bufferToBase64url(assertion.response.clientDataJSON),
            signature: bufferToBase64url(assertion.response.signature),
            userHandle: assertion.response.userHandle ? bufferToBase64url(assertion.response.userHandle) : null,
          },
        };

        const verRes = await fetch('/api/lock/unlock/verify', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
          body: JSON.stringify({ challenge_id: chalId, credential: assertionJSON }),
        });
        if (!verRes.ok) {
          let err = verRes.statusText;
          try { err = (await verRes.json()).detail || err; } catch {}
          throw new Error(err);
        }
        const verData = await verRes.json();
        if (verData.unlock) {
          sessionStorage.setItem('ag_unlock', verData.unlock);
          document.body.classList.remove('is-locked');
          overlay.setAttribute('hidden', '');
          resolve(verData.unlock);
        }
      } catch (e) {
        if (e.name !== 'NotAllowedError') {
          toast(e.message || 'Unlock failed');
        }
      } finally {
        btn.disabled = false;
        btn.innerHTML = `${icon('fingerprint')}<span>Unlock</span>`;
        if (msg) msg.textContent = 'Unlock to continue.';
      }
    }
    btn.onclick = () => doUnlock();
    doUnlock();
  }).finally(() => {
    activeUnlockPromise = null;
  });
  return activeUnlockPromise;
}

async function openAppLock() {
  let status;
  try {
    status = await getJSON('/lock/status');
    state.lockEnabled = !!status.enabled;
    state.lockIdleMinutes = status.idle_minutes || 5;
    if (state.lockEnabled) {
      try { localStorage.setItem('ag_lock_enabled', '1'); } catch {}
    } else {
      try { localStorage.removeItem('ag_lock_enabled'); } catch {}
    }
  } catch (e) {
    return handleErr(e);
  }

  if (!status.available) {
    const dlg = openSheet(`
      <h2>App lock</h2>
      <p class="lede">App lock needs the lock extra.</p>
      <p>Install it on your computer:</p>
      <pre style="background:var(--surface-2);padding:10px;border-radius:8px;font-size:0.875rem;overflow-x:auto"><code>uv tool install --upgrade 'agents-dialpad[lock]'</code></pre>
      <div class="actions"><button class="btn" type="button" data-close>Done</button></div>
    `, 'App lock');
    $('[data-close]', dlg).onclick = () => dlg.close();
    return;
  }

  if (status.secure_context_hint || !window.isSecureContext) {
    const dlg = openSheet(`
      <h2>App lock</h2>
      <p class="lede">App lock needs the HTTPS address (Tailscale). Open the app from there.</p>
      <div class="actions"><button class="btn" type="button" data-close>Done</button></div>
    `, 'App lock');
    $('[data-close]', dlg).onclick = () => dlg.close();
    return;
  }

  if (!status.enabled) {
    const dlg = openSheet(`
      <h2>App lock</h2>
      <p class="lede">Protect this device with Face ID, Touch ID or fingerprint. When turned on, the app locks after ${status.idle_minutes} minutes idle.</p>
      <div class="actions">
        <button class="btn secondary" type="button" data-close>Cancel</button>
        <button class="btn primary" id="btn-lock-turn-on" type="button">Turn on</button>
      </div>
    `, 'App lock');
    $('[data-close]', dlg).onclick = () => dlg.close();
    $('#btn-lock-turn-on', dlg).onclick = async () => {
      try {
        const turnBtn = $('#btn-lock-turn-on', dlg);
        turnBtn.disabled = true;
        turnBtn.textContent = 'Registering...';
        const optData = await postJSON('/lock/register/options', {
          name: /iPhone|iPad|Macintosh/.test(navigator.userAgent) ? 'Apple Device' : /Android/.test(navigator.userAgent) ? 'Android Device' : 'Passkey',
        });
        const chalId = optData.challenge_id;
        const opts = optData.options || optData;
        opts.challenge = base64urlToBuffer(opts.challenge);
        opts.user.id = base64urlToBuffer(opts.user.id);
        if (opts.excludeCredentials) {
          opts.excludeCredentials.forEach(c => c.id = base64urlToBuffer(c.id));
        }

        const cred = await navigator.credentials.create({ publicKey: opts });
        const credJSON = {
          id: cred.id,
          rawId: bufferToBase64url(cred.rawId),
          type: cred.type,
          response: {
            attestationObject: bufferToBase64url(cred.response.attestationObject),
            clientDataJSON: bufferToBase64url(cred.response.clientDataJSON),
          },
        };

        const verData = await postJSON('/lock/register/verify', {
          challenge_id: chalId,
          credential: credJSON,
        });
        if (verData.unlock) {
          sessionStorage.setItem('ag_unlock', verData.unlock);
        }
        state.lockEnabled = true;
        toast('App lock turned on');
        dlg.close();
        openAppLock();
      } catch (err) {
        if (err.name !== 'NotAllowedError') {
          toast(err.message || 'Registration failed');
        }
        dlg.close();
      }
    };
    return;
  }

  // Lock is enabled
  const credsHtml = (status.credentials || []).map(c => `
    <div class="lock-cred-item">
      <div class="lock-cred-info">
        <span class="lock-cred-name">${esc(c.name || 'Passkey')}</span>
        <span class="lock-cred-meta">Added ${timeAgo(c.created)}</span>
      </div>
      <button class="btn secondary sm" data-remove-cred="${esc(c.id)}" type="button">Remove</button>
    </div>
  `).join('');

  const dlg = openSheet(`
    <h2>App lock</h2>
    <p class="lede">App lock is on. Locks after ${status.idle_minutes} minutes idle.</p>
    <div class="lock-creds-list">${credsHtml}</div>
    <div class="actions" style="margin-top:16px;">
      <button class="btn secondary" id="btn-lock-add" type="button">Add passkey</button>
      <button class="btn" type="button" data-close>Done</button>
    </div>
  `, 'App lock');
  $('[data-close]', dlg).onclick = () => dlg.close();

  $('#btn-lock-add', dlg).onclick = async () => {
    try {
      const addBtn = $('#btn-lock-add', dlg);
      addBtn.disabled = true;
      addBtn.textContent = 'Registering...';
      const optData = await postJSON('/lock/register/options', {
        name: /iPhone|iPad|Macintosh/.test(navigator.userAgent) ? 'Apple Device' : /Android/.test(navigator.userAgent) ? 'Android Device' : 'Passkey',
      });
      const chalId = optData.challenge_id;
      const opts = optData.options || optData;
      opts.challenge = base64urlToBuffer(opts.challenge);
      opts.user.id = base64urlToBuffer(opts.user.id);
      if (opts.excludeCredentials) {
        opts.excludeCredentials.forEach(c => c.id = base64urlToBuffer(c.id));
      }

      const cred = await navigator.credentials.create({ publicKey: opts });
      const credJSON = {
        id: cred.id,
        rawId: bufferToBase64url(cred.rawId),
        type: cred.type,
        response: {
          attestationObject: bufferToBase64url(cred.response.attestationObject),
          clientDataJSON: bufferToBase64url(cred.response.clientDataJSON),
        },
      };

      const verData = await postJSON('/lock/register/verify', {
        challenge_id: chalId,
        credential: credJSON,
      });
      if (verData.unlock) {
        sessionStorage.setItem('ag_unlock', verData.unlock);
      }
      toast('Passkey added');
      dlg.close();
      openAppLock();
    } catch (err) {
      if (err.name !== 'NotAllowedError') {
        toast(err.message || 'Registration failed');
      }
      dlg.close();
    }
  };

  $$('[data-remove-cred]', dlg).forEach(btn => {
    btn.onclick = async () => {
      const cid = btn.dataset.removeCred;
      if (!confirm('Remove this passkey?')) return;
      try {
        await api('/lock/credentials/' + encodeURIComponent(cid), { method: 'DELETE' });
        toast('Passkey removed');
        dlg.close();
        openAppLock();
      } catch (err) {
        toast(err.message || 'Failed to remove passkey');
      }
    };
  });
}

function renderList() {
  const list = $('#chat-list'); if (!list) return;
  if (state.query) return;
  if (!state.chats.length) {
    list.innerHTML = `<div class="empty">
      ${icon('chat')}
      <p><b>No chats yet</b></p>
      <p class="empty-sub">Conversations with local agents will appear here.</p>
      <button class="btn primary phone-only" id="empty-new" type="button">Start a chat</button>
    </div>`;
    const btn = $('#empty-new');
    if (btn) btn.onclick = openNewChat;
    return;
  }
  const activeId = cur && cur.chat.id;
  const chatRow = (c) => `
    <a class="chat-row" href="#/c/${c.id}"${c.id === activeId ? ' aria-current="page"' : ''}>
      <span class="t"><span class="title">${esc(c.title)}</span>
      <span class="meta">${esc(providerLabel(c.provider))} · ${esc(c.project)} · ${esc(timeAgo(c.updated))}</span></span>
      ${c.pinned ? `<span class="pin-badge" aria-hidden="true">${icon('pin')}</span>` : ''}
      ${c.running ? '<span class="dot" role="img" aria-label="Running"></span>' : ''}
    </a>`;

  const items = state.chats.map((c) => ({ pinned: !!c.pinned, html: chatRow(c) }));
  const pinned = items.filter((i) => i.pinned);
  const recent = items.filter((i) => !i.pinned);
  let html = '';
  if (pinned.length) {
    html += '<div class="chat-sec-label">Pinned</div>' + pinned.map((i) => i.html).join('');
    if (recent.length) html += '<div class="chat-sec-label">Recent</div>' + recent.map((i) => i.html).join('');
  } else {
    html = recent.map((i) => i.html).join('');
  }
  list.innerHTML = html;
}

function renderSearchResults(results) {
  const list = $('#chat-list'); if (!list) return;
  if (!results.length) {
    list.innerHTML = `<div class="empty"><p class="note">No chats match “${esc(state.query)}”.</p></div>`;
    return;
  }
  const activeId = cur && cur.chat.id;
  list.innerHTML = results.map((c) => `
    <a class="chat-row" href="#/c/${c.id}"${c.id === activeId ? ' aria-current="page"' : ''}>
      <span class="t"><span class="title">${esc(c.title)}</span>
      ${c.snippet ? `<span class="snip">${esc(c.snippet)}</span>` : ''}
      <span class="meta">${esc(providerLabel(c.provider))} · ${esc(c.project)} · ${esc(timeAgo(c.updated))}</span></span>
      ${c.pinned ? `<span class="pin-badge" aria-hidden="true">${icon('pin')}</span>` : ''}
      ${c.running ? '<span class="dot" role="img" aria-label="Running"></span>' : ''}
    </a>`).join('');
}

async function refreshList() {
  if (!$('.shell') || state.query) return;
  try {
    const d = await getJSON('/chats');
    const sig = JSON.stringify(d.chats);
    if (sig !== state.sig) {
      state.sig = sig;
      state.chats = d.chats;
      renderList();
      if (!cur) showEmptyPane();
    }
  } catch (e) {
    if (e instanceof AuthError) { forgetToken(); showLogin('That token was rejected. Paste the current one.'); }
  }
}
setInterval(() => { if (!document.hidden) refreshList(); }, 8000);

async function loadInfo() { state.info = await getJSON('/info'); return state.info; }
const providerLabel = (name) => { const p = state.info && state.info.providers.find((x) => x.name === name); return p ? p.label : name; };
const modelLabel = (provider, id) => {
  const p = state.info && state.info.providers.find((x) => x.name === provider);
  const m = p && p.models.find((x) => x.id === id);
  return m ? m.label : (id || 'Default');
};
const modelOptions = (p, selected) => (p ? p.models : []).map((m) =>
  `<option value="${esc(m.id)}"${m.id === selected ? ' selected' : ''}>${esc(m.label)}</option>`).join('');

/* ===================== sheets: new chat, model, limits ===================== */
async function openNewChat() {
  let info; try { info = await loadInfo(); } catch (e) { return handleErr(e); }
  const isUsable = (p) => p.available && (!p.status || p.status.state === 'ready' || p.status.state === 'unknown');
  const usable = info.providers.filter(isUsable);
  const first = usable[0] || info.providers[0];
  const isClaude = (first && first.name === 'claude');
  const firstModes = (first && first.modes) ? first.modes : info.modes;
  const provOptions = info.providers.map((p) => {
    let disabled = false;
    let suffix = '';
    const st = p.status ? p.status.state : (p.available ? 'ready' : 'not_installed');
    if (st === 'not_signed_in') {
      disabled = true;
      suffix = ' (sign in on the computer)';
    } else if (st === 'not_installed' || !p.available) {
      disabled = true;
      suffix = ' (not installed)';
    }
    const isSelected = first && p.name === first.name;
    return `<option value="${esc(p.name)}"${disabled ? ' disabled' : ''}${isSelected ? ' selected' : ''}>${esc(p.label)}${suffix}</option>`;
  }).join('');
  const signedOut = info.providers.find((p) => p.status && p.status.state === 'not_signed_in');
  const provNote = signedOut ? `<p class="note" id="n-prov-note">${esc(signedOut.note || `${signedOut.label} isn't signed in on the computer.`)}</p>` : '';
  const dlg = openSheet(`<form id="f-new"><h2>New chat</h2>
    <label for="n-prov">Agent</label>
    <select id="n-prov">${provOptions}</select>
    ${provNote}
    <label for="n-model" id="lbl-model">Model</label>
    <select id="n-model">${modelOptions(first, '')}</select>
    <label for="n-proj">Project folder</label>
    <select id="n-proj">${info.projects.map((p) => `<option>${esc(p)}</option>`).join('')}</select>
    <label for="n-mode">Permissions</label>
    <select id="n-mode">${firstModes.map((m) => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join('')}</select>
    <div class="actions"><button class="btn secondary" type="button" data-close>Cancel</button><button class="btn" type="submit" id="n-go">Start</button></div>
    <button class="btn secondary" type="button" id="btn-continue-desk" style="width: 100%; margin-top: 12px;" ${isClaude ? '' : 'hidden'}>Continue a desktop session</button>
  </form>`, 'New chat');
  $('[data-close]', dlg).onclick = () => dlg.close();
  $('#n-prov', dlg).onchange = () => {
    const val = $('#n-prov', dlg).value;
    const prov = info.providers.find((p) => p.name === val);
    $('#n-model', dlg).innerHTML = modelOptions(prov, '');
    const pModes = (prov && prov.modes) ? prov.modes : info.modes;
    $('#n-mode', dlg).innerHTML = pModes.map((m) => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join('');
    $('#btn-continue-desk', dlg).hidden = val !== 'claude';
  };
  $('#btn-continue-desk', dlg).onclick = () => {
    const proj = $('#n-proj', dlg).value;
    const mode = $('#n-mode', dlg).value;
    dlg.close();
    openContinueDesk(info, proj, mode);
  };
  $('#f-new', dlg).onsubmit = async (e) => {
    e.preventDefault();
    const go = $('#n-go', dlg); go.setAttribute('aria-busy', 'true');
    const prov = $('#n-prov', dlg).value;
    const project = $('#n-proj', dlg).value;
    const mode = $('#n-mode', dlg).value;
    try {
      const chat = await postJSON('/chats', {
        provider: prov,
        model: $('#n-model', dlg).value,
        project,
        mode,
      });
      dlg.close();
      location.hash = '#/c/' + chat.id;
      refreshList();
    } catch (err) { go.removeAttribute('aria-busy'); handleErr(err); }
  };
}

async function openContinueDesk(info, initialProj, initialMode) {
  const dlg = openSheet(`
    <h2>Continue a desktop session</h2>
    <label for="cd-proj">Project folder</label>
    <select id="cd-proj">${info.projects.map((p) => `<option${p === initialProj ? ' selected' : ''}>${esc(p)}</option>`).join('')}</select>
    <label for="cd-mode">Permissions</label>
    <select id="cd-mode">${info.modes.map((m) => `<option value="${esc(m.id)}"${m.id === initialMode ? ' selected' : ''}>${esc(m.label)}</option>`).join('')}</select>
    <label>Recent sessions</label>
    <div class="desk-list" id="cd-list"><p class="lede">Loading…</p></div>
    <div class="actions"><button class="btn secondary" type="button" data-close>Cancel</button></div>
  `, 'Continue a desktop session');
  $('[data-close]', dlg).onclick = () => dlg.close();

  const projSel = $('#cd-proj', dlg);
  const listEl = $('#cd-list', dlg);

  async function loadSessions() {
    listEl.innerHTML = '<p class="lede">Loading…</p>';
    let sessions;
    try {
      sessions = await getJSON(`/projects/${encodeURIComponent(projSel.value)}/desk-sessions`);
    } catch (e) {
      return handleErr(e);
    }
    if (!sessions.length) {
      listEl.innerHTML = '<p class="lede">No desktop sessions found for this folder.</p>';
      return;
    }
    listEl.innerHTML = sessions.map((s) => `
      <button class="desk-row" type="button" data-id="${esc(s.id)}">
        <span class="desk-preview">${esc(s.preview)}</span>
        <span class="desk-time">${esc(timeAgo(s.updated))}</span>
      </button>
    `).join('');

    $$('.desk-row', listEl).forEach((btn) => {
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          const chat = await getJSON('/chats/import', {
            method: 'POST',
            body: JSON.stringify({
              project: projSel.value,
              mode: $('#cd-mode', dlg).value,
              session_id: btn.dataset.id,
            }),
          });
          dlg.close();
          location.hash = '#/c/' + chat.id;
          refreshList();
        } catch (err) {
          btn.disabled = false;
          handleErr(err);
        }
      };
    });
  }

  projSel.onchange = loadSessions;
  await loadSessions();
}

async function openModelPicker() {
  if (!cur) return;
  if (cur.live) return toast('Wait for the reply to finish first');
  let info; try { info = state.info || await loadInfo(); } catch (e) { return handleErr(e); }
  const chat = cur.chat, p = info.providers.find((x) => x.name === chat.provider);
  const dlg = openSheet(`<form id="f-model"><h2>Model</h2>
    <p class="lede">${esc(p ? p.label : chat.provider)}. Applies from your next message.</p>
    <label for="m-sel">Model</label><select id="m-sel">${modelOptions(p, chat.model || '')}</select>
    <div class="actions"><button class="btn secondary" type="button" data-close>Cancel</button><button class="btn" type="submit" id="m-go">Save</button></div></form>`, 'Choose model');
  $('[data-close]', dlg).onclick = () => dlg.close();
  $('#f-model', dlg).onsubmit = async (e) => {
    e.preventDefault();
    const go = $('#m-go', dlg); go.setAttribute('aria-busy', 'true');
    try {
      const r = await getJSON('/chats/' + chat.id, { method: 'PATCH', body: JSON.stringify({ model: $('#m-sel', dlg).value }) });
      chat.model = r.model; dlg.close(); updateHeader();
    } catch (err) { go.removeAttribute('aria-busy'); handleErr(err); }
  };
}

function limitsHTML(data) {
  if (!data || !data.providers || !data.providers.length) return '<p class="note">No agents available.</p>';
  return data.providers.map((p) => {
    const rows = p.rows.map((r) => {
      const cls = r.remaining < 15 ? 'low' : r.remaining < 40 ? 'mid' : '';
      const name = r.group === p.label ? r.label : `${r.group} · ${r.label}`;   // don't repeat the section heading
      return `<div class="lim"><div class="lim-top"><span>${esc(name)}</span><b>${r.remaining}% left</b></div>
        <div class="track" role="progressbar" aria-label="${esc(name)}" aria-valuenow="${r.remaining}" aria-valuemin="0" aria-valuemax="100"><i class="${cls}" style="width:${r.remaining}%"></i></div>
        <small>${esc(resetsIn(r.resets_at))}</small></div>`;
    }).join('');
    return `<section class="lim-sec"><h3>${esc(p.label)}</h3>${rows || `<p class="note">${esc(p.note || 'No data.')}</p>`}</section>`;
  }).join('');
}
async function openLimits(force) {
  let dlg = $('#ldlg');
  if (!dlg) {
    dlg = openSheet(`<h2>Usage limits</h2><div id="lbody"><p class="note">Loading…</p></div>
      <div class="actions"><button class="btn secondary" type="button" id="lrefresh">Refresh</button><button class="btn" type="button" data-close>Done</button></div>`, 'Usage limits');
    dlg.id = 'ldlg';
    $('[data-close]', dlg).onclick = () => dlg.close();
    $('#lrefresh', dlg).onclick = () => openLimits(true);
  } else $('#lbody', dlg).innerHTML = '<p class="note">Loading…</p>';
  try {
    const limitsData = await getJSON('/limits' + (force === true ? '?refresh=true' : ''));
    $('#lbody', dlg).innerHTML = limitsHTML(limitsData);
  }
  catch (e) { dlg.close(); handleErr(e); }
}

async function openSchedules() {
  let dlg = $('#sdlg');
  if (!dlg) {
    dlg = openSheet(`<h2>Schedules</h2><div id="sbody"><p class="note">Loading…</p></div>
      <p class="note" style="margin-top:16px">Edit schedules in config.json on the computer.</p>
      <div class="actions"><button class="btn" type="button" data-close>Done</button></div>`, 'Schedules');
    dlg.id = 'sdlg';
    $('[data-close]', dlg).onclick = () => dlg.close();
  } else $('#sbody', dlg).innerHTML = '<p class="note">Loading…</p>';

  try {
    const list = await getJSON('/schedules');
    if (!list.length) {
      $('#sbody', dlg).innerHTML = '<p class="note">No schedules configured.</p>';
      return;
    }
    const fmtNext = (iso) => {
      try {
        const d = new Date(iso);
        const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const day = days[d.getDay()];
        const h = String(d.getHours()).padStart(2, '0');
        const m = String(d.getMinutes()).padStart(2, '0');
        return `${day} ${h}:${m}`;
      } catch { return iso; }
    };
    $('#sbody', dlg).innerHTML = list.map((s, idx) => `
      <div class="sched-row">
        <div class="sched-info">
          <div class="sched-name">${esc(s.name)}</div>
          <div class="sched-meta">Next: ${esc(fmtNext(s.next_run))} · Last: ${esc(s.last_run || 'never')} · ${esc(s.project)} (${esc(s.agent)})</div>
        </div>
        <button class="btn secondary" type="button" data-run-idx="${idx}">Run now</button>
      </div>
    `).join('');

    list.forEach((s, idx) => {
      const btn = dlg.querySelector(`[data-run-idx="${idx}"]`);
      if (btn) {
        btn.onclick = async () => {
          btn.setAttribute('aria-busy', 'true');
          btn.disabled = true;
          try {
            const res = await postJSON('/schedules/' + encodeURIComponent(s.name) + '/run');
            dlg.close();
            location.hash = '#/c/' + res.chat_id;
            refreshList();
          } catch (err) {
            btn.removeAttribute('aria-busy');
            btn.disabled = false;
            handleErr(err);
          }
        };
      }
    });
  } catch (e) {
    dlg.close();
    handleErr(e);
  }
}

function handleErr(e) {
  if (e instanceof AuthError) { forgetToken(); showLogin('That token was rejected. Paste the current one.'); }
  else toast(e.message || 'Something went wrong');
}

/* ===================== conversation ===================== */
function showEmptyPane() {
  const pane = $('#pane'); if (!pane) return;
  if (!state.chats.length) {
    pane.innerHTML = `
      <div class="empty empty-hero">
        <div class="empty-badge">
          <img src="/logo-mark.svg" alt="" class="empty-logo" width="44" height="44">
        </div>
        <h2 class="empty-title">agents-dialpad</h2>
        <p class="empty-sub">Pick up the line to an agent running on this computer.</p>
        <button class="btn primary" id="pane-new" type="button">Start a chat</button>
      </div>`;
    $('#pane-new').onclick = openNewChat;
  } else {
    pane.innerHTML = `
      <div class="empty">
        ${icon('chat')}
        <p><b>Pick a conversation</b></p>
        <p class="empty-sub">Choose a chat from the sidebar to continue.</p>
      </div>`;
  }
  const shell = $('.shell'); if (shell) shell.dataset.running = 'false';
}

function teardownChat() {
  closeMenu();
  const input = $('#input');
  if (input && cur && cur.chat) state.drafts[cur.chat.id] = input.value;
  if (cur) cur.destroy();
  cur = null;
}

function createChatView(chat, els) {
  const view = {
    chat,
    live: null,
    ctrl: null,
    gen: 0,
    stick: true,
    els,
    onRunningChange: null,
    _renderQueued: false,

    renderThread() {
      if (!this.els.thread) return;
      this.els.thread.dataset.chatId = this.chat.id;       // lets approval buttons find their chat
      let topNote = '';
      if (this.chat.imported && (!this.chat.messages || this.chat.messages.length === 0)) {
        topNote = '<div class="thread-note">Continued from a session on the computer. Earlier messages stay there, but the agent remembers them.</div>';
      }
      this.els.thread.innerHTML = topNote + this.chat.messages.map(msgHTML).join('') + '<div class="live-slot"></div>';
      this.renderLive();
    },

    renderLive() {
      if (!this.els.thread) return;
      const el = this.els.thread.querySelector('.live-slot');
      if (!el) return;
      if (!this.live) { el.className = 'live-slot'; el.innerHTML = ''; return; }
      el.className = 'live-slot msg assistant';
      el.innerHTML = `<div class="prose">${assistantHTML(this.live.events, true)}</div>`;
    },

    scheduleRender() {
      if (this._renderQueued) return;
      this._renderQueued = true;
      requestAnimationFrame(() => {
        this._renderQueued = false;
        this.renderLive();
        this.scrollToEnd(false);
      });
    },

    scrollToEnd(force) {
      const box = this.els.msgs;
      if (!box) return;
      if (force || this.stick) {
        box.scrollTop = box.scrollHeight;
        if (force) this.stick = true;
      }
      if (this.els.jump) this.els.jump.hidden = this.stick || !this.live;
    },

    setRunning(on) {
      if (this.els.send) {
        this.els.send.classList.toggle('stop', on);
        this.els.send.setAttribute('aria-label', on ? 'Stop' : 'Send');
        this.els.send.innerHTML = icon(on ? 'stop' : 'up');
      }
      const shell = $('.shell');
      if (shell) shell.dataset.running = on ? 'true' : 'false';
      if (this.els.msgs) this.els.msgs.setAttribute('aria-busy', on ? 'true' : 'false');
      if (this.onRunningChange) this.onRunningChange(on);
    },

    async attach() {
      if (this.ctrl) this.ctrl.abort();
      const gen = ++this.gen, ctrl = new AbortController();
      this.ctrl = ctrl;
      this.live = { events: [] };
      this.setRunning(true);
      this.renderLive();
      this.scrollToEnd(true);
      try {
        const r = await api(`/chats/${this.chat.id}/stream?start=0`, { signal: ctrl.signal });
        const reader = r.body.getReader(), dec = new TextDecoder();
        let buf = '';
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let nl;
          while ((nl = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, nl).trim();
            buf = buf.slice(nl + 1);
            if (!line) continue;
            const ev = JSON.parse(line);
            if (ev.type === 'ping') continue;
            this.live.events.push(ev);
            this.scheduleRender();
          }
        }
      } catch (e) {
        if (gen !== this.gen || e.name === 'AbortError') return;
        if (e instanceof AuthError) return handleErr(e);
        setTimeout(() => { if (gen === this.gen) this.recover(); }, 1500);
        return;
      }
      if (gen !== this.gen) return;
      try {
        this.chat = await getJSON('/chats/' + this.chat.id);
      } catch {}
      this.live = null;
      this.setRunning(false);
      if (this === cur) updateHeader();
      this.renderThread();
      this.scrollToEnd(false);
      if (this.els.sr) this.els.sr.textContent = 'Reply finished';
      refreshList();
    },

    async recover() {
      try {
        const fresh = await getJSON('/chats/' + this.chat.id);
        this.chat = fresh;
        if (fresh.running) {
          this.attach();
        } else {
          this.live = null;
          this.setRunning(false);
          if (this === cur) updateHeader();
          this.renderThread();
          this.scrollToEnd(false);
        }
      } catch (e) {
        if (e instanceof AuthError) handleErr(e);
        else setTimeout(() => this.recover(), 3000);
      }
    },

    async stop() {
      try {
        await api(`/chats/${this.chat.id}/stop`, { method: 'POST' });
      } catch (e) {
        toast(e.message);
      }
    },

    destroy() {
      if (this.ctrl) {
        this.ctrl.abort();
        this.ctrl = null;
      }
    }
  };

  if (els.msgs) {
    els.msgs.addEventListener('scroll', () => {
      view.stick = els.msgs.scrollHeight - els.msgs.scrollTop - els.msgs.clientHeight < 80;
      if (els.jump) els.jump.hidden = view.stick || !view.live;
    }, { passive: true });
  }
  if (els.jump) {
    els.jump.onclick = () => view.scrollToEnd(true);
  }

  return view;
}

async function openChat(id, approvalReq) {
  if (cur && cur.chat.id === id && $('#thread')) {
    if (approvalReq) scrollToApproval(approvalReq);
    return;
  }
  teardownChat();
  let chat;
  try { chat = await getJSON('/chats/' + id); } catch (e) { location.hash = '#/'; return handleErr(e); }
  if (location.hash.split('?')[0] !== '#/c/' + id) return;                        // the user moved on while we loaded
  if (state.quick[chat.project] === undefined) {
    try { state.quick[chat.project] = await getJSON('/projects/' + encodeURIComponent(chat.project) + '/commands'); }
    catch { state.quick[chat.project] = []; }
  }
  buildPane(chat);
  cur = createChatView(chat, { msgs: $('#msgs'), thread: $('#thread'), jump: $('#jump'), send: $('#send'), sr: $('#sr') });
  cur.pending = [];       // attachments waiting to be sent
  cur.uploading = 0;
  state.openTools = new Set();
  state.expandedApprovals = new Set();
  cur.renderThread();
  if (approvalReq) {
    scrollToApproval(approvalReq);
  } else {
    cur.scrollToEnd(true);
  }
  renderList();
  if (chat.running) cur.attach();
}

function scrollToApproval(reqId) {
  requestAnimationFrame(() => {
    const card = document.querySelector(`.approval[data-req-id="${CSS.escape(reqId)}"]`);
    if (card) {
      const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
      card.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center' });
      card.classList.add('highlight');
      setTimeout(() => card.classList.remove('highlight'), 2000);
    }
  });
}

function buildPane(chat) {
  const disabledAgents = (state.info && state.info.disabled_agents) || [];
  const isDisabled = disabledAgents.includes(chat.provider);
  const composerHtml = isDisabled
    ? `<div class="composer-in"><p class="disabled-msg">${esc(providerLabel(chat.provider))} is turned off in config.json</p></div>`
    : `<div class="composer-in">
      <div id="attachments" class="attachments-row" hidden></div>
      <div class="meta-row"><button class="chip" id="btn-model" type="button" aria-label="Change model"><span id="model-label"></span>${icon('chev')}</button></div>
      <div class="row">
        <input type="file" id="file-input" multiple accept="image/*,.pdf,.txt,.md,.csv,.json,.log,.yaml,.yml,.xml,.html,.css,.js,.ts,.py" hidden>
        <button class="icon-btn clip-btn" id="btn-clip" type="button" aria-label="Attach files">${icon('clip')}</button>
        <div class="field"><label class="sr" for="input">Message</label>
          <textarea id="input" rows="1" placeholder="Message" enterkeyhint="send"></textarea></div>
        <button class="send" id="send" type="submit" aria-label="Send">${icon('up')}</button>
      </div>
    </div>`;

  $('#pane').innerHTML = `
    <header class="bar">
      <a class="icon-btn back" href="#/" aria-label="Back to chats">${icon('back')}</a>
      <div class="titles"><h2 id="title"></h2><span class="sub" id="sub"></span></div>
      <button class="icon-btn" id="btn-more" type="button" aria-label="More actions" aria-haspopup="menu" aria-expanded="false">${icon('more')}</button>
    </header>
    <div class="msgs" id="msgs" role="log" aria-label="Conversation">
      <div class="thread" id="thread"></div>
      <button class="icon-btn jump" id="jump" type="button" aria-label="Scroll to latest message" hidden>${icon('down')}</button>
    </div>
    <div class="sr" id="sr" role="status"></div>
    <form class="composer" id="composer" autocomplete="off">${composerHtml}</form>`;
  updateHeader(chat);

  function updateSendBtn() {
    const btn = $('#send');
    if (!btn || !cur) return;
    if (cur.uploading && cur.uploading > 0) btn.disabled = true;
    else btn.disabled = false;
  }

  function renderAttachments() {
    const container = $('#attachments');
    if (!container || !cur) return;
    if (!cur.pending || !cur.pending.length) {
      container.innerHTML = '';
      container.hidden = true;
      return;
    }
    container.hidden = false;
    container.innerHTML = cur.pending.map((item, idx) => {
      const thumb = item.url
        ? `<img class="att-thumb" src="${item.url}" alt="">`
        : `<span class="att-icon">${icon('file')}</span>`;
      const spin = item.loading ? `<span class="att-spin" aria-label="Uploading"></span>` : '';
      return `
        <div class="att-chip ${item.loading ? 'loading' : ''}">
          ${thumb}
          <span class="att-name" title="${esc(item.label)}">${esc(item.label)}</span>
          ${spin}
          <button class="att-rm icon-btn" type="button" data-idx="${idx}" aria-label="Remove ${esc(item.label)}">
            ${icon('x')}
          </button>
        </div>`;
    }).join('');

    $$('.att-rm', container).forEach((b) => {
      b.onclick = () => {
        const idx = parseInt(b.dataset.idx, 10);
        const item = cur.pending[idx];
        if (item && item.url) URL.revokeObjectURL(item.url);
        cur.pending.splice(idx, 1);
        renderAttachments();
        updateSendBtn();
      };
    });
  }

  const fileInput = $('#file-input');
  if ($('#btn-clip') && fileInput) {
    $('#btn-clip').onclick = () => fileInput.click();
  }
  if (fileInput) {
    fileInput.onchange = async () => {
      const files = Array.from(fileInput.files || []);
      fileInput.value = '';
      if (!files.length) return;
      if ((cur.pending.length + files.length) > 10) {
        return toast('Maximum 10 attachments per message');
      }
      for (const file of files) {
        const isImg = file.type.startsWith('image/');
        const item = {
          name: '',
          label: file.name,
          url: isImg ? URL.createObjectURL(file) : null,
          loading: true,
        };
        cur.pending.push(item);
        renderAttachments();
        cur.uploading = (cur.uploading || 0) + 1;
        updateSendBtn();
        try {
          const res = await uploadFile(cur.chat.id, file);
          item.name = res.name;
          item.loading = false;
        } catch (e) {
          if (item.url) URL.revokeObjectURL(item.url);
          cur.pending = cur.pending.filter((x) => x !== item);
          handleErr(e);
        } finally {
          cur.uploading = Math.max(0, (cur.uploading || 1) - 1);
          updateSendBtn();
          renderAttachments();
        }
      }
    };
  }

  const input = $('#input');
  if ($('#btn-model')) $('#btn-model').onclick = openModelPicker;
  $('#btn-more').onclick = (e) => {
    if ($('#menu')) return closeMenu();
    const items = [
      { icon: 'edit', label: 'Rename', run: renameChat },
      { icon: 'pin', label: cur.chat.pinned ? 'Unpin' : 'Pin', run: togglePin },
      { icon: 'download', label: 'Export as Markdown', run: exportChat },
      { icon: 'diff', label: 'Changes', run: openChanges },
    ];
    if (chat.provider === 'claude' && chat.session_id) {
      items.push({ icon: 'term', label: 'Continue on the computer', run: openContinueDeskCmd });
    }
    const qCmds = state.quick[chat.project] || [];
    if (qCmds.length) {
      items.push({ icon: 'term', label: 'Quick commands', run: openQuickCommands });
    }
    items.push(
      { icon: 'gauge', label: 'Usage limits', run: openLimits },
      { icon: 'trash', label: 'Delete chat', danger: true, run: deleteChat },
    );
    openMenu(e.currentTarget, items);
  };

  if (input) {
    input.value = state.drafts[chat.id] || '';
    const field = $('.field');
    if (field) field.addEventListener('click', (e) => { if (e.target === e.currentTarget) input.focus(); });
    input.addEventListener('input', autosize);
    input.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' || e.isComposing) return;
      const send = e.ctrlKey || e.metaKey || (!e.shiftKey && matchMedia('(pointer: fine)').matches);
      if (send) { e.preventDefault(); if (cur && !cur.live) sendMessage(cur); }
    });
    autosize();
  }
  $('#composer').onsubmit = (e) => {
    e.preventDefault();
    if (isDisabled) return;
    if (cur && cur.live) cur.stop();
    else sendMessage(cur);
  };
  autosize();
}

function updateHeader(chat) {
  const c = chat || (cur && cur.chat);
  if (!c || !$('#title')) return;
  $('#title').textContent = c.title;
  $('#sub').textContent = `${providerLabel(c.provider)} · ${c.project} · ${MODE_TEXT[c.mode] || c.mode}`;
  const ml = $('#model-label');
  if (ml) ml.textContent = modelLabel(c.provider, c.model || '');
}

function autosize() { const t = $('#input'); if (!t) return; t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, window.innerHeight * 0.38) + 'px'; }

function openContinueDeskCmd() {
  if (!cur || !cur.chat) return;
  const chat = cur.chat;
  const os = (state.info && state.info.server_os) || 'windows';
  const projPath = chat.project_path || chat.project;
  let cmd = '';
  if (os === 'windows') {
    cmd = `cd /d "${projPath}" && claude --resume ${chat.session_id}`;
  } else {
    const escaped = projPath.replace(/'/g, "'\\''");
    cmd = `cd '${escaped}' && claude --resume ${chat.session_id}`;
  }
  const dlg = openSheet(`
    <h2>Continue on the computer</h2>
    <p class="lede">Run this in a terminal on the computer. Close the chat here first so both don't write at once.</p>
    <div class="code-box">
      <pre><code>${esc(cmd)}</code></pre>
      <button class="btn secondary" id="btn-copy-desk" type="button">Copy</button>
    </div>
    <div class="actions"><button class="btn secondary" type="button" data-close>Close</button></div>
  `, 'Continue on the computer');
  $('[data-close]', dlg).onclick = () => dlg.close();
  $('#btn-copy-desk', dlg).onclick = () => copyText(cmd, $('#btn-copy-desk', dlg));
}

async function renameChat() {
  if (!cur) return;
  const chat = cur.chat;
  const dlg = openSheet(`<form id="f-rename"><h2>Rename chat</h2>
    <label for="r-title">Chat name</label>
    <input id="r-title" type="text" maxlength="80" value="${esc(chat.title)}" required>
    <div class="actions"><button class="btn secondary" type="button" data-close>Cancel</button><button class="btn" type="submit" id="r-go">Save</button></div></form>`, 'Rename chat');
  $('[data-close]', dlg).onclick = () => dlg.close();
  $('#f-rename', dlg).onsubmit = async (e) => {
    e.preventDefault();
    const val = $('#r-title', dlg).value.trim();
    if (!val) return;
    const go = $('#r-go', dlg); go.setAttribute('aria-busy', 'true');
    try {
      const r = await getJSON('/chats/' + chat.id, { method: 'PATCH', body: JSON.stringify({ title: val }) });
      chat.title = r.title;
      dlg.close();
      updateHeader();
      refreshList();
    } catch (err) { go.removeAttribute('aria-busy'); handleErr(err); }
  };
}

async function togglePin() {
  if (!cur) return;
  const chat = cur.chat;
  const next = !chat.pinned;
  try {
    const r = await getJSON('/chats/' + chat.id, { method: 'PATCH', body: JSON.stringify({ pinned: next }) });
    chat.pinned = r.pinned;
    toast(r.pinned ? 'Pinned' : 'Unpinned');
    refreshList();
  } catch (err) { handleErr(err); }
}

async function openQuickCommands() {
  if (!cur) return;
  const project = cur.chat.project;
  const cmds = state.quick[project] || [];
  if (!cmds.length) return;

  const btnHtml = cmds.map((c) =>
    `<button class="btn secondary quick-btn" type="button" data-idx="${c.index}">${esc(c.label)}</button>`
  ).join('');

  const dlg = openSheet(`<h2>Quick commands</h2>
    <p class="lede">Runs in ${esc(project)}. Output appears below.</p>
    <div class="quick-btns" id="qbtns">${btnHtml}</div>
    <div id="qres" hidden>
      <div class="quick-meta" id="qmeta"></div>
      <pre class="quick-out" id="qout"></pre>
      <div class="actions"><button class="btn secondary" type="button" id="qcopy">Copy output</button><button class="btn" type="button" data-close>Done</button></div>
    </div>
    <div class="actions" id="qactions"><button class="btn secondary" type="button" data-close>Close</button></div>`, 'Quick commands');

  const btns = dlg.querySelectorAll('.quick-btn');
  const resBox = $('#qres', dlg);
  const metaBox = $('#qmeta', dlg);
  const outBox = $('#qout', dlg);
  const copyBtn = $('#qcopy', dlg);
  const baseActions = $('#qactions', dlg);

  copyBtn.onclick = async () => {
    if (await copyText(outBox.textContent)) toast('Output copied');
  };

  $('#qbtns', dlg).onclick = async (e) => {
    const b = e.target.closest('.quick-btn');
    if (!b) return;
    const idx = b.dataset.idx;
    btns.forEach((btn) => btn.disabled = true);
    b.setAttribute('aria-busy', 'true');
    try {
      const res = await getJSON('/projects/' + encodeURIComponent(project) + '/commands/' + idx, { method: 'POST' });
      resBox.hidden = false;
      baseActions.hidden = true;
      if (res.timed_out) {
        metaBox.className = 'quick-meta err';
        metaBox.textContent = 'Timed out after ' + (res.duration_ms / 1000).toFixed(1) + 's';
      } else {
        metaBox.className = 'quick-meta';
        metaBox.textContent = 'Exit code ' + res.exit_code + ' · ' + (res.duration_ms / 1000).toFixed(1) + 's';
      }
      outBox.textContent = res.output || 'No output.';
    } catch (err) {
      handleErr(err);
    } finally {
      b.removeAttribute('aria-busy');
      btns.forEach((btn) => btn.disabled = false);
    }
  };
}

function formatPath(p) {
  if (!p || p.length <= 48) return p;
  const parts = p.split('/');
  if (parts.length >= 2) return '…/' + parts.slice(-2).join('/');
  return p.slice(0, 20) + '…' + p.slice(-25);
}

function renderDiffLines(raw) {
  if (!raw) return '';
  const lines = raw.split('\n');
  return lines.map(line => {
    let cls = 'ctx';
    if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ') || line.startsWith('index ')) {
      cls = 'meta';
    } else if (line.startsWith('+')) {
      cls = 'add';
    } else if (line.startsWith('-')) {
      cls = 'del';
    } else if (line.startsWith('@@')) {
      cls = 'hunk';
    }
    return `<div class="dl ${cls}">${esc(line)}</div>`;
  }).join('');
}

async function openChanges() {
  if (!cur || !cur.chat) return;
  const project = cur.chat.project;
  const dlg = openSheet('<h2>Changes</h2><p class="lede">Loading…</p>', 'Project changes');
  dlg.classList.add('wide');
  const body = $('.sheet-body', dlg);

  async function loadChanges() {
    let data;
    try {
      data = await getJSON(`/projects/${encodeURIComponent(project)}/changes`);
    } catch (e) {
      dlg.close();
      return handleErr(e);
    }
    if (!data.is_repo) {
      body.innerHTML = `
        <h2>Changes</h2>
        <p class="lede">This folder is not a git repository</p>
        <div class="actions"><button class="btn secondary" type="button" id="btn-close">Close</button></div>`;
      $('#btn-close', body).onclick = () => dlg.close();
      return;
    }
    const files = data.files || [];
    if (!files.length) {
      const title = data.branch ? esc(data.branch) : 'Changes';
      body.innerHTML = `
        <h2>${title}</h2>
        <p class="lede">No changes since the last commit</p>
        <div class="actions"><button class="btn secondary" type="button" id="btn-close">Close</button></div>`;
      $('#btn-close', body).onclick = () => dlg.close();
      return;
    }

    const title = data.branch ? esc(data.branch) : 'Changes';
    const countText = `${files.length} changed file${files.length === 1 ? '' : 's'}`;
    const rowsHtml = files.map(f => `
      <button class="change-row" type="button" data-path="${esc(f.path)}">
        <span class="change-badge ${esc(f.code)}" aria-label="${esc(f.label)}">${esc(f.code)}</span>
        <span class="change-path">${esc(formatPath(f.path))}</span>
        ${f.orig_path ? `<span class="change-orig">(from ${esc(formatPath(f.orig_path))})</span>` : ''}
      </button>
    `).join('');

    body.innerHTML = `
      <h2>${title}</h2>
      <p class="lede">${countText}</p>
      <div class="changes-list">${rowsHtml}</div>
      <div class="actions"><button class="btn secondary" type="button" id="btn-close">Close</button></div>`;

    $('#btn-close', body).onclick = () => dlg.close();

    $$('.change-row', body).forEach(btn => {
      btn.onclick = () => showDiff(btn.dataset.path);
    });
  }

  async function showDiff(filePath) {
    body.innerHTML = `
      <div class="diff-top">
        <div class="diff-top-left">
          <button class="btn secondary" type="button" id="btn-diff-back">All changes</button>
          <span class="diff-file-path">${esc(formatPath(filePath))}</span>
        </div>
      </div>
      <p class="lede">Loading diff…</p>`;

    $('#btn-diff-back', body).onclick = () => loadChanges();

    let res;
    try {
      res = await getJSON(`/projects/${encodeURIComponent(project)}/changes/diff?path=${encodeURIComponent(filePath)}`);
    } catch (e) {
      return handleErr(e);
    }

    let diffContent = '';
    if (res.kind === 'binary') {
      diffContent = '<p class="diff-msg">Binary file, not shown</p>';
    } else if (res.kind === 'too_large') {
      diffContent = '<p class="diff-msg">Too large to show</p>';
    } else {
      const note = res.truncated ? '<p class="diff-note">Showing the first part only</p>' : '';
      diffContent = `${note}<div class="diff-lines">${renderDiffLines(res.diff)}</div>`;
    }

    const canRevert = res.kind !== 'untracked';
    body.innerHTML = `
      <div class="diff-top">
        <div class="diff-top-left">
          <button class="btn secondary" type="button" id="btn-diff-back">All changes</button>
          <span class="diff-file-path">${esc(formatPath(filePath))}</span>
        </div>
        ${canRevert ? '<button class="btn danger" type="button" id="btn-revert">Revert this file</button>' : ''}
      </div>
      <div class="diff-container">${diffContent}</div>
      <div class="actions"><button class="btn secondary" type="button" id="btn-close">Close</button></div>`;

    $('#btn-diff-back', body).onclick = () => loadChanges();
    $('#btn-close', body).onclick = () => dlg.close();

    const revertBtn = $('#btn-revert', body);
    if (revertBtn) {
      revertBtn.onclick = async () => {
        const ok = await confirmSheet({
          title: 'Revert this file?',
          body: `Your uncommitted changes to ${filePath} will be lost. This can't be undone.`,
          confirm: 'Revert',
          danger: true,
        });
        if (!ok) return;
        try {
          await api(`/projects/${encodeURIComponent(project)}/changes/revert`, {
            method: 'POST',
            body: JSON.stringify({ path: filePath }),
          });
          toast('Reverted');
          await loadChanges();
        } catch (err) {
          handleErr(err);
        }
      };
    }
  }

  await loadChanges();
}

async function exportChat() {
  if (!cur) return;
  try {
    const r = await api('/chats/' + cur.chat.id + '/export');
    const blob = await r.blob();
    const cd = r.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="([^"]+)"/);
    const fname = m ? m[1] : 'chat.md';
    const u = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = u; a.download = fname;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(u), 10000);
  } catch (e) { handleErr(e); }
}

async function deleteChat() {
  if (!cur) return;
  const id = cur.chat.id;
  const ok = await confirmSheet({ title: 'Delete this chat?', body: 'The conversation is removed from this computer. This can’t be undone.', confirm: 'Delete', danger: true });
  if (!ok) return;
  try { await api('/chats/' + id, { method: 'DELETE' }); } catch (e) { return handleErr(e); }
  delete state.drafts[id]; location.hash = '#/'; refreshList();
}



/* ---- rendering ---- */
function toolArg(input) {
  input = input || {};
  return input.command || input.CommandLine || input.file_path || input.path || input.pattern || input.url || input.query || input.description
    || (Object.keys(input).length ? JSON.stringify(input) : '');
}

function assistantHTML(events, live) {
  const blocks = [], toolById = {}, approvalById = {};
  let foot = '', denials = [];
  for (const ev of events) {
    if (ev.type === 'text') {
      const last = blocks[blocks.length - 1];
      if (last && last.kind === 'text') last.text += ev.text; else blocks.push({ kind: 'text', text: ev.text });
    } else if (ev.type === 'tool_use') {
      const b = { kind: 'tool', id: String(ev.id), name: ev.name, arg: toolArg(ev.input), result: null };
      toolById[ev.id] = b; blocks.push(b);
    } else if (ev.type === 'tool_result') {
      if (toolById[ev.id]) toolById[ev.id].result = ev;
    } else if (ev.type === 'approval') {
      const cmd = ev.command != null ? String(ev.command) : (toolArg(ev.input) || '');
      const b = {
        kind: 'approval',
        id: String(ev.id),
        tool: ev.tool || 'Command',
        command: cmd,
        description: ev.description || '',
        input: (ev.input && typeof ev.input === 'object') ? ev.input : {},
        truncated: !!ev.truncated,
        result: null,
      };
      approvalById[ev.id] = b; blocks.push(b);
    } else if (ev.type === 'approval_result') {
      if (approvalById[ev.id]) {
        approvalById[ev.id].result = ev;
        pendingApprovals.delete(String(ev.id));
      }
    } else if (ev.type === 'done') {
      const bits = [];
      if (ev.stopped) bits.push('Stopped');
      if (ev.duration_ms) bits.push((ev.duration_ms / 1000).toFixed(1) + 's');
      foot = bits.join(' · ');
      denials = [...new Set(ev.denials || [])];
      if (ev.is_error && ev.result) blocks.push({ kind: 'error', text: ev.result, action: ev.action });
    } else if (ev.type === 'error') {
      blocks.push({ kind: 'error', text: ev.message, action: ev.action });
    }
  }
  let html = blocks.map((b) => {
    if (b.kind === 'text') return Markdown.render(b.text);
    if (b.kind === 'error') {
      const actionHtml = b.action === 'change_model'
        ? `<div class="err-actions"><button class="btn secondary sm" type="button" data-action="change_model">Change model</button></div>`
        : '';
      return `<div class="errbox">${icon('warn')}<div><span>${esc(b.text)}</span>${actionHtml}</div></div>`;
    }
    if (b.kind === 'approval') {
      let statusHtml = '';
      if (!b.result) {
        if (live) {
          const isPending = pendingApprovals.has(b.id);
          statusHtml = `<div class="approval-actions"><button class="btn" type="button" data-approve="${esc(b.id)}" data-allow="1"${isPending ? ' disabled' : ''}>Allow</button><button class="btn secondary" type="button" data-approve="${esc(b.id)}" data-allow="0"${isPending ? ' disabled' : ''}>Deny</button></div>`;
        } else {
          statusHtml = '<div class="approval-status foot">Stopped</div>';
        }
      } else {
        let label = 'Denied';
        if (b.result.allow) {
          label = b.result.by === 'notification' ? 'Allowed from notification' : 'Allowed';
        } else if (b.result.by === 'notification') {
          label = 'Denied from notification';
        } else if (b.result.by === 'timeout') {
          label = 'No answer in time, so it was denied';
        } else if (b.result.by === 'stopped') {
          label = 'Stopped';
        }
        statusHtml = `<div class="approval-status foot">${esc(label)}</div>`;
      }

      const descHtml = b.description ? `<p class="approval-desc">${esc(b.description)}</p>` : '';

      let cmdHtml = '';
      if (b.command) {
        const lines = b.command.split('\n');
        const lineCount = lines.length;
        const needsClamp = lineCount > 6 || b.command.length > 400;
        const isExpanded = state.expandedApprovals && state.expandedApprovals.has(b.id);
        const clampedCls = (needsClamp && !isExpanded) ? ' clamped' : '';
        const showAllBtn = (needsClamp && !isExpanded)
          ? `<button class="approval-expand" type="button" data-approval-expand="${esc(b.id)}">… Show all (${lineCount} lines)</button>`
          : '';
        const headHtml = `<div class="approval-cmd-head"><span class="tool-name"><span class="ic">${icon('term')}</span>$ ${esc(b.tool)}</span><button class="btn secondary sm approval-copy" type="button" aria-label="Copy command" data-approval-copy>Copy</button></div>`;
        cmdHtml = `<div class="approval-cmd-box">${headHtml}<pre class="approval-cmd${clampedCls}"><code>${esc(b.command)}</code></pre>${showAllBtn}</div>`;
      }

      const isFileEdit = /^(edit|multiedit|write)$/i.test(b.tool);
      const filePath = b.input.file_path || b.input.path || '';
      const fileHtml = (isFileEdit && filePath) ? `<div class="approval-file">File: <code>${esc(filePath)}</code></div>` : '';

      let diffLinesHtml = '';
      if (isFileEdit) {
        const tName = (b.tool || '').toLowerCase();
        if (tName === 'edit') {
          const oldLines = b.input.old_string ? String(b.input.old_string).split('\n') : [];
          const newLines = b.input.new_string ? String(b.input.new_string).split('\n') : [];
          const dls = [
            ...oldLines.map((l) => `<div class="dl del">- ${esc(l)}</div>`),
            ...newLines.map((l) => `<div class="dl add">+ ${esc(l)}</div>`),
          ];
          if (dls.length) diffLinesHtml = `<div class="diff-container diff-lines">${dls.join('')}</div>`;
        } else if (tName === 'multiedit') {
          const edits = Array.isArray(b.input.edits) ? b.input.edits : [];
          const dls = [];
          for (const ed of edits) {
            if (ed.old_string) String(ed.old_string).split('\n').forEach((l) => dls.push(`<div class="dl del">- ${esc(l)}</div>`));
            if (ed.new_string) String(ed.new_string).split('\n').forEach((l) => dls.push(`<div class="dl add">+ ${esc(l)}</div>`));
          }
          if (dls.length) diffLinesHtml = `<div class="diff-container diff-lines">${dls.join('')}</div>`;
        } else if (tName === 'write') {
          if (b.input.content) {
            const contentLines = String(b.input.content).split('\n');
            const first20 = contentLines.slice(0, 20);
            const dls = first20.map((l) => `<div class="dl add">+ ${esc(l)}</div>`);
            if (contentLines.length > 20) {
              dls.push(`<div class="dl meta">… (${contentLines.length - 20} more lines)</div>`);
            }
            diffLinesHtml = `<div class="diff-container diff-lines">${dls.join('')}</div>`;
          }
        }
      }

      const truncHtml = b.truncated ? '<p class="approval-note">Very long. The rest is cut off here; Deny if unsure.</p>' : '';

      const excludeKeys = new Set([
        'command', 'CommandLine', 'cmd', 'file_path', 'path', 'description', 'toolSummary',
        'old_string', 'new_string', 'content', 'edits'
      ]);
      const rest = {};
      for (const [k, v] of Object.entries(b.input || {})) {
        if (!excludeKeys.has(k)) rest[k] = v;
      }
      const detailsHtml = Object.keys(rest).length
        ? `<details class="approval-details"><summary>Details</summary><pre class="approval-details-json"><code>${esc(JSON.stringify(rest, null, 2))}</code></pre></details>`
        : '';

      return `<div class="approval" data-req-id="${esc(b.id)}"><div class="approval-title">Allow this?</div>${descHtml}${cmdHtml}${fileHtml}${diffLinesHtml}${truncHtml}${detailsHtml}${statusHtml}</div>`;
    }
    const status = !b.result ? '<span class="st"><span class="spin"></span></span>'
      : b.result.is_error ? `<span class="st err">${icon('x')}</span>` : `<span class="st">${icon('check')}</span>`;
    const head = `<span class="ic">${icon('term')}</span><span class="name">${esc(b.name)}</span><span class="arg">${esc(b.arg)}</span>${status}`;
    if (b.result && b.result.text) {
      return `<details class="tool" data-id="${esc(b.id)}"${state.openTools.has(b.id) ? ' open' : ''}><summary>${head}</summary><pre>${esc(b.result.text)}</pre></details>`;
    }
    return `<div class="tool"><div class="sum">${head}</div></div>`;
  }).join('');
  const last = blocks[blocks.length - 1];
  if (live && (!last || last.kind !== 'text')) html += '<div class="status"><span class="spin"></span><span>Working…</span></div>';
  if (!live && !html) html = '<p class="foot">No output.</p>';
  if (denials.length) {
    const canFull = state.info && state.info.modes.some((m) => m.id === 'full') && cur && cur.chat.mode !== 'full';
    html += `<div class="foot warn">${icon('warn')}<span>Needs approval, so it was blocked: ${esc(denials.join(', '))}.${canFull ? ' Start a new chat with Full access to let it run commands.' : ''}</span></div>`;
  }
  if (foot) html += `<div class="foot tnum">${esc(foot)}</div>`;
  return html;
}

function msgHTML(m) {
  if (m.role === 'user') {
    let attHtml = '';
    if (m.attachments && m.attachments.length) {
      attHtml = `<div class="msg-attachments">${m.attachments.map((a) => `<span class="msg-att-chip">${icon('clip')}${esc(a)}</span>`).join('')}</div>`;
    }
    return `<div class="msg user"><div class="bubble">${esc(m.text)}${attHtml}</div></div>`;
  }
  return `<div class="msg assistant"><div class="prose">${assistantHTML(m.events || [], false)}</div></div>`;
}

/* ---- sending + streaming ---- */
async function sendMessage(view) {
  if (!view) view = cur;
  if (!view || view.live) return;
  if (view.uploading > 0) return;            // wait for attachments to finish uploading
  const input = $('#input');
  let text = input.value.trim();
  const pending = view.pending || [];
  const attachments = pending.filter((p) => !p.loading && p.name).map((p) => p.name);
  const labels = pending.filter((p) => !p.loading && p.name).map((p) => p.label || p.name);
  if (!text && !attachments.length) return;
  if (!text) text = 'See the attached files.';
  pending.forEach((p) => { if (p.url) URL.revokeObjectURL(p.url); });
  view.pending = [];
  const attRow = $('#attachments');
  if (attRow) { attRow.innerHTML = ''; attRow.hidden = true; }
  input.value = '';
  delete state.drafts[view.chat.id];
  autosize();

  view.chat.messages.push({ role: 'user', text, attachments: labels });
  view.renderThread();
  view.scrollToEnd(true);

  try {
    const body = attachments.length ? { text, attachments } : { text };
    await api(`/chats/${view.chat.id}/messages`, { method: 'POST', body: JSON.stringify(body) });
    view.attach();
  } catch (e) {
    if (e instanceof AuthError) return handleErr(e);
    toast(e.message);
    input.value = text;
    autosize();
    try { view.chat = await getJSON('/chats/' + view.chat.id); view.renderThread(); } catch {}
  }
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  refreshList();
  if (cur && (cur.live || (cur.chat && cur.chat.running))) cur.recover();
});

/* ---- copy buttons on code blocks ---- */
document.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-md-copy]'); if (!b) return;
  const ok = await copyText(b.closest('.md-code').querySelector('code').textContent);
  b.textContent = ok ? 'Copied' : 'Copy failed'; b.classList.toggle('done', ok);
  setTimeout(() => { b.textContent = 'Copy'; b.classList.remove('done'); }, 1600);
});

/* ---- approval copy button ---- */
document.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-approval-copy]');
  if (!b) return;
  const box = b.closest('.approval-cmd-box');
  const code = box ? box.querySelector('.approval-cmd code') : null;
  const ok = await copyText(code ? code.textContent : '');
  b.textContent = ok ? 'Copied' : 'Copy failed';
  setTimeout(() => { b.textContent = 'Copy'; }, 1600);
});

/* ---- approval expand button (Show all) ---- */
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-approval-expand]');
  if (!b) return;
  const id = b.dataset.approvalExpand;
  state.expandedApprovals.add(id);
  const box = b.closest('.approval-cmd-box');
  if (box) {
    const pre = box.querySelector('.approval-cmd');
    if (pre) pre.classList.remove('clamped');
    b.remove();
  }
});

/* ---- approval buttons (Allow / Deny) ---- */
document.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-approve]');
  if (!b || b.disabled) return;
  const reqId = b.dataset.approve;
  const allow = b.dataset.allow === '1';
  // Find the chat this card belongs to:
  const host = b.closest('[data-chat-id]');
  const chatId = host ? host.dataset.chatId : (cur && cur.chat && cur.chat.id);
  if (!chatId) return;

  pendingApprovals.add(reqId);
  const card = b.closest('.approval');
  const allBtns = card ? card.querySelectorAll('[data-approve]') : [b];
  allBtns.forEach((btn) => { btn.disabled = true; });

  try {
    await api(`/chats/${chatId}/approvals/${encodeURIComponent(reqId)}`, {
      method: 'POST',
      body: JSON.stringify({ allow }),
    });
    if ('serviceWorker' in navigator) {
      try {
        const reg = await navigator.serviceWorker.ready;
        const notifs = await reg.getNotifications({ tag: `approval:${chatId}:${reqId}` });
        notifs.forEach((n) => n.close());
      } catch {}
    }
  } catch (err) {
    pendingApprovals.delete(reqId);
    allBtns.forEach((btn) => { btn.disabled = false; });
    toast(err.message || 'Approval failed');
  }
});

/* ---- action buttons (e.g. Change model) ---- */
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-action="change_model"]');
  if (!b) return;
  openModelPicker();
});

/* ---- tool collapse state ---- */
document.addEventListener('toggle', (e) => {
  const d = e.target;
  if (!d.matches || !d.matches('details.tool')) return;
  if (d.open) state.openTools.add(d.dataset.id);
  else state.openTools.delete(d.dataset.id);
}, true);

/* ---- keep the composer above the on-screen keyboard (iOS does not resize the layout viewport) ---- */
if (window.visualViewport) {
  const vv = window.visualViewport;
  const sync = () => {
    document.documentElement.style.setProperty('--vh', vv.scale === 1 ? vv.height + 'px' : '100dvh');
    if (vv.scale === 1 && vv.offsetTop) window.scrollTo(0, 0);
  };
  vv.addEventListener('resize', sync); vv.addEventListener('scroll', sync); sync();
}

/* ---- lock again when app has been hidden for longer than lockIdleMinutes ---- */
let appHiddenAt = 0;
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') {
    appHiddenAt = Date.now();
  } else if (document.visibilityState === 'visible') {
    if (appHiddenAt > 0 && state.lockIdleMinutes) {
      const elapsedSec = (Date.now() - appHiddenAt) / 1000;
      if (elapsedSec >= state.lockIdleMinutes * 60) {
        sessionStorage.removeItem('ag_unlock');
        if (token) {
          fetch('/api/lock/lock', { method: 'POST', headers: { Authorization: 'Bearer ' + token } }).catch(() => {});
        }
        if (state.lockEnabled) {
          promptUnlock();
        }
      }
    }
    appHiddenAt = 0;
  }
});

/* ===================== routing ===================== */
async function route() {
  if (!token) return showLogin();
  if (!state.lockChecked) {
    state.lockChecked = true;
    if (localStorage.getItem('ag_lock_enabled') === '1' && !sessionStorage.getItem('ag_unlock')) {
      promptUnlock();
    }
    getJSON('/lock/status').then((lk) => {
      state.lockEnabled = !!lk.enabled;
      state.lockIdleMinutes = lk.idle_minutes || 5;
      if (state.lockEnabled) {
        try { localStorage.setItem('ag_lock_enabled', '1'); } catch {}
        if (!sessionStorage.getItem('ag_unlock')) {
          promptUnlock();
        }
      } else {
        try { localStorage.removeItem('ag_lock_enabled'); } catch {}
        document.body.classList.remove('is-locked');
        $('#lock-overlay')?.setAttribute('hidden', '');
      }
    }).catch(() => {});
  }
  mountShell();
  const shell = $('.shell');
  const mc = location.hash.match(/^#\/c\/([0-9a-f]{32})(?:\?(.*))?$/);
  if (mc) {
    shell.dataset.view = 'chat';
    const params = new URLSearchParams(mc[2] || '');
    await openChat(mc[1], params.get('approval'));
  } else {
    shell.dataset.view = 'list';
    teardownChat();
    showEmptyPane();
    renderList();
  }
  refreshList();
}
addEventListener('hashchange', route);
route();

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
