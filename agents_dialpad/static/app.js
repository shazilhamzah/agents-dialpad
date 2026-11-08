'use strict';

/* ===================== helpers ===================== */
const $ = (s, r = document) => r.querySelector(s);
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
};
const icon = (n) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICON[n]}</svg>`;

const MODE_TEXT = { readonly: 'read-only', edit: 'can edit', full: 'full access' };

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
  const headers = { Authorization: 'Bearer ' + token, ...(opts.body ? { 'Content-Type': 'application/json' } : {}) };
  const r = await fetch('/api' + path, { ...opts, headers });
  if (r.status === 401) throw new AuthError();
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  return r;
}
const getJSON = async (p, o) => (await api(p, o)).json();
function forgetToken() { LS.del('ag_token'); token = null; }

/* ===================== state ===================== */
const state = { chats: [], sig: '', info: null, drafts: {}, openTools: new Set(), query: '' };
let cur = null;           // open conversation: { chat, live: {events}|null, ctrl, gen }
let stick = true;         // keep the view pinned to the newest text unless the reader scrolled up
let renderQueued = false;

/* ===================== sheets, menu, confirm ===================== */
function openSheet(html, label) {
  const dlg = document.createElement('dialog');
  dlg.className = 'sheet';
  if (label) dlg.setAttribute('aria-label', label);
  dlg.innerHTML = `<div class="grab" aria-hidden="true"></div><div class="sheet-body">${html}</div>`;
  document.body.appendChild(dlg);
  dlg.addEventListener('close', () => dlg.remove());
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });   // tap the scrim
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
      <h1>agents-dialpad</h1>
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
        <div class="titles"><h1>agents-dialpad</h1></div>
        <button class="icon-btn" id="btn-limits" type="button" aria-label="Usage limits">${icon('gauge')}</button>
        <button class="icon-btn" id="btn-side-more" type="button" aria-label="More" aria-haspopup="menu" aria-expanded="false">${icon('more')}</button>
        <button class="icon-btn solid" id="btn-new" type="button" aria-label="New chat">${icon('plus')}</button>
      </header>
      <div class="search">${icon('search')}<label class="sr" for="q">Search chats</label><input id="q" type="search" placeholder="Search chats" autocomplete="off" enterkeyhint="search"></div>
      <nav class="chats" id="chat-list" aria-label="Chat list"></nav>
    </aside>
    <main class="pane" id="pane"></main>
  </div>`;
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
  loadInfo().then(() => { renderList(); updateHeader(); }).catch(() => {});   // agent + model names for the list and header
}

function sideMenuItems() { return [{ icon: 'qr', label: 'Pair a device', run: openPair }]; }
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

function renderList() {
  const list = $('#chat-list'); if (!list) return;
  if (state.query) return;
  if (!state.chats.length) {
    list.innerHTML = `<div class="empty">${icon('chat')}<p><b>No chats yet</b></p>
      <p>Start one to talk to an agent running on this computer.</p><button class="btn" id="empty-new" type="button">New chat</button></div>`;
    $('#empty-new').onclick = openNewChat;
    return;
  }
  const activeId = cur && cur.chat.id;
  const pinned = state.chats.filter((c) => c.pinned);
  const recent = state.chats.filter((c) => !c.pinned);
  const rowHTML = (c) => `
    <a class="chat-row" href="#/c/${c.id}"${c.id === activeId ? ' aria-current="page"' : ''}>
      <span class="t"><span class="title">${esc(c.title)}</span>
      <span class="meta">${esc(providerLabel(c.provider))} · ${esc(c.project)} · ${esc(timeAgo(c.updated))}</span></span>
      ${c.pinned ? `<span class="pin-badge" aria-hidden="true">${icon('pin')}</span>` : ''}
      ${c.running ? '<span class="dot" role="img" aria-label="Running"></span>' : ''}
    </a>`;

  let html = '';
  if (pinned.length) {
    html += '<div class="chat-sec-label">Pinned</div>' + pinned.map(rowHTML).join('');
    if (recent.length) html += '<div class="chat-sec-label">Recent</div>' + recent.map(rowHTML).join('');
  } else {
    html = recent.map(rowHTML).join('');
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
    if (sig !== state.sig) { state.sig = sig; state.chats = d.chats; renderList(); }
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
  const first = info.providers.find((p) => p.available);
  const dlg = openSheet(`<form id="f-new"><h2>New chat</h2>
    <label for="n-prov">Agent</label>
    <select id="n-prov">${info.providers.map((p) => `<option value="${esc(p.name)}"${p.available ? '' : ' disabled'}>${esc(p.label)}${p.available ? '' : ' (not yet)'}</option>`).join('')}</select>
    <label for="n-model">Model</label>
    <select id="n-model">${modelOptions(first, '')}</select>
    <label for="n-proj">Project folder</label>
    <select id="n-proj">${info.projects.map((p) => `<option>${esc(p)}</option>`).join('')}</select>
    <label for="n-mode">Permissions</label>
    <select id="n-mode">${info.modes.map((m) => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join('')}</select>
    <div class="actions"><button class="btn secondary" type="button" data-close>Cancel</button><button class="btn" type="submit" id="n-go">Start</button></div></form>`, 'New chat');
  $('[data-close]', dlg).onclick = () => dlg.close();
  $('#n-prov', dlg).onchange = () => { $('#n-model', dlg).innerHTML = modelOptions(info.providers.find((p) => p.name === $('#n-prov', dlg).value), ''); };
  $('#f-new', dlg).onsubmit = async (e) => {
    e.preventDefault();
    const go = $('#n-go', dlg); go.setAttribute('aria-busy', 'true');
    try {
      const chat = await getJSON('/chats', { method: 'POST', body: JSON.stringify({
        provider: $('#n-prov', dlg).value, model: $('#n-model', dlg).value, project: $('#n-proj', dlg).value, mode: $('#n-mode', dlg).value }) });
      dlg.close(); location.hash = '#/c/' + chat.id; refreshList();
    } catch (err) { go.removeAttribute('aria-busy'); handleErr(err); }
  };
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
  if (!data.providers.length) return '<p class="note">No agents available.</p>';
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
  try { $('#lbody', dlg).innerHTML = limitsHTML(await getJSON('/limits' + (force === true ? '?refresh=true' : ''))); }
  catch (e) { dlg.close(); handleErr(e); }
}

function handleErr(e) {
  if (e instanceof AuthError) { forgetToken(); showLogin('That token was rejected. Paste the current one.'); }
  else toast(e.message || 'Something went wrong');
}

/* ===================== conversation ===================== */
function showEmptyPane() {
  const pane = $('#pane'); if (!pane) return;
  pane.innerHTML = `<div class="empty">${icon('chat')}<p><b>Pick a chat</b></p><p>Choose one from the list, or start a new one.</p>
    <button class="btn" id="pane-new" type="button">New chat</button></div>`;
  $('#pane-new').onclick = openNewChat;
  setRunning(false);
}

function teardownChat() {
  closeMenu();
  if (!cur) return;
  const input = $('#input'); if (input) state.drafts[cur.chat.id] = input.value;
  if (cur.ctrl) cur.ctrl.abort();
  cur = null;
}

async function openChat(id) {
  if (cur && cur.chat.id === id && $('#thread')) return;           // already showing it
  teardownChat();
  let chat;
  try { chat = await getJSON('/chats/' + id); } catch (e) { location.hash = '#/'; return handleErr(e); }
  if (location.hash !== '#/c/' + id) return;                        // the user moved on while we loaded
  cur = { chat, live: null, ctrl: null, gen: 0 };
  state.openTools = new Set();
  buildPane();
  renderThread(); scrollToEnd(true);
  renderList();                                                     // highlight the open chat
  if (chat.running) attach();
}

function buildPane() {
  const chat = cur.chat;
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
    <form class="composer" id="composer" autocomplete="off"><div class="composer-in">
      <div class="meta-row"><button class="chip" id="btn-model" type="button" aria-label="Change model"><span id="model-label"></span>${icon('chev')}</button></div>
      <div class="row">
        <div class="field"><label class="sr" for="input">Message</label>
          <textarea id="input" rows="1" placeholder="Message" enterkeyhint="send"></textarea></div>
        <button class="send" id="send" type="submit" aria-label="Send">${icon('up')}</button>
      </div>
    </div></form>`;
  updateHeader();

  const msgs = $('#msgs'), input = $('#input');
  msgs.addEventListener('scroll', () => {
    stick = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 80;
    $('#jump').hidden = stick || !cur || !cur.live;
  }, { passive: true });
  $('#jump').onclick = () => scrollToEnd(true);
  msgs.addEventListener('toggle', (e) => {                          // remember which tool calls the reader opened
    const d = e.target; if (!d.matches || !d.matches('details.tool')) return;
    if (d.open) state.openTools.add(d.dataset.id); else state.openTools.delete(d.dataset.id);
  }, true);

  $('#btn-model').onclick = openModelPicker;
  $('#btn-more').onclick = (e) => {
    if ($('#menu')) return closeMenu();
    openMenu(e.currentTarget, [
      { icon: 'edit', label: 'Rename', run: renameChat },
      { icon: 'pin', label: cur.chat.pinned ? 'Unpin' : 'Pin', run: togglePin },
      { icon: 'download', label: 'Export as Markdown', run: exportChat },
      { icon: 'gauge', label: 'Usage limits', run: openLimits },
      { icon: 'trash', label: 'Delete chat', danger: true, run: deleteChat },
    ]);
  };

  input.value = state.drafts[chat.id] || '';
  $('.field').addEventListener('click', (e) => { if (e.target === e.currentTarget) input.focus(); });   // the whole pill is tappable
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.isComposing) return;
    // Phones: Enter is a new line (use the Send button). Computers: Enter sends, Shift+Enter is a new line.
    const send = e.ctrlKey || e.metaKey || (!e.shiftKey && matchMedia('(pointer: fine)').matches);
    if (send) { e.preventDefault(); if (cur && !cur.live) sendMessage(); }
  });
  $('#composer').onsubmit = (e) => { e.preventDefault(); if (cur && cur.live) stopRun(); else sendMessage(); };
  autosize();
}

function updateHeader() {
  if (!cur || !$('#title')) return;
  const c = cur.chat;
  $('#title').textContent = c.title;
  $('#sub').textContent = `${providerLabel(c.provider)} · ${c.project} · ${MODE_TEXT[c.mode] || c.mode}`;
  $('#model-label').textContent = modelLabel(c.provider, c.model || '');
}

function autosize() { const t = $('#input'); if (!t) return; t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, window.innerHeight * 0.38) + 'px'; }

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
  const blocks = [], toolById = {};
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
    } else if (ev.type === 'done') {
      const bits = [];
      if (ev.stopped) bits.push('Stopped');
      if (ev.duration_ms) bits.push((ev.duration_ms / 1000).toFixed(1) + 's');
      foot = bits.join(' · ');
      denials = [...new Set(ev.denials || [])];
      if (ev.is_error && ev.result) blocks.push({ kind: 'error', text: ev.result });
    } else if (ev.type === 'error') {
      blocks.push({ kind: 'error', text: ev.message });
    }
  }
  let html = blocks.map((b) => {
    if (b.kind === 'text') return Markdown.render(b.text);
    if (b.kind === 'error') return `<div class="errbox">${icon('warn')}<span>${esc(b.text)}</span></div>`;
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
  if (m.role === 'user') return `<div class="msg user"><div class="bubble">${esc(m.text)}</div></div>`;
  return `<div class="msg assistant"><div class="prose">${assistantHTML(m.events || [], false)}</div></div>`;
}
function renderThread() {
  const t = $('#thread'); if (!t || !cur) return;
  t.innerHTML = cur.chat.messages.map(msgHTML).join('') + '<div id="live"></div>';
  renderLive();
}
function renderLive() {
  const el = $('#live'); if (!el || !cur) return;
  if (!cur.live) { el.className = ''; el.innerHTML = ''; return; }
  el.className = 'msg assistant';
  el.innerHTML = `<div class="prose">${assistantHTML(cur.live.events, true)}</div>`;
}
function scrollToEnd(force) {
  const box = $('#msgs'); if (!box) return;
  if (force || stick) { box.scrollTop = box.scrollHeight; if (force) stick = true; }
  const j = $('#jump'); if (j) j.hidden = stick || !cur || !cur.live;
}
function scheduleRender() {
  if (renderQueued) return; renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; renderLive(); scrollToEnd(false); });
}

function setRunning(on) {
  const shell = $('.shell'); if (shell) shell.dataset.running = on ? 'true' : 'false';
  const b = $('#send'); if (b) {
    b.classList.toggle('stop', on);
    b.setAttribute('aria-label', on ? 'Stop' : 'Send');
    b.innerHTML = icon(on ? 'stop' : 'up');
  }
  const log = $('#msgs'); if (log) log.setAttribute('aria-busy', on ? 'true' : 'false');
}

/* ---- sending + streaming ---- */
async function sendMessage() {
  if (!cur || cur.live) return;
  const input = $('#input'), text = input.value.trim(); if (!text) return;
  input.value = ''; delete state.drafts[cur.chat.id]; autosize();
  cur.chat.messages.push({ role: 'user', text });
  renderThread(); scrollToEnd(true);
  try {
    await api(`/chats/${cur.chat.id}/messages`, { method: 'POST', body: JSON.stringify({ text }) });
  } catch (e) {
    if (e instanceof AuthError) return handleErr(e);
    toast(e.message); input.value = text; autosize();
    cur.chat = await getJSON('/chats/' + cur.chat.id); renderThread(); return;
  }
  attach();
}
async function stopRun() { try { await api(`/chats/${cur.chat.id}/stop`, { method: 'POST' }); } catch (e) { toast(e.message); } }

/* Replays the running turn from event 0, so reconnecting after a locked screen is trivial. */
async function attach() {
  const c = cur; if (!c) return;
  c.ctrl && c.ctrl.abort();
  const gen = ++c.gen, ctrl = new AbortController(); c.ctrl = ctrl;
  c.live = { events: [] }; setRunning(true); renderLive(); scrollToEnd(true);
  try {
    const r = await api(`/chats/${c.chat.id}/stream?start=0`, { signal: ctrl.signal });
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1); if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.type === 'ping') continue;
        c.live.events.push(ev); scheduleRender();
      }
    }
  } catch (e) {
    if (gen !== c.gen || e.name === 'AbortError') return;
    if (e instanceof AuthError) return handleErr(e);
    setTimeout(() => { if (cur === c && gen === c.gen) recover(); }, 1500);   // network blip: retry
    return;
  }
  if (gen !== c.gen || cur !== c) return;
  c.chat = await getJSON('/chats/' + c.chat.id);
  c.live = null; setRunning(false); updateHeader(); renderThread(); scrollToEnd(false);
  const sr = $('#sr'); if (sr) sr.textContent = 'Reply finished';
  refreshList();
}
async function recover() {
  if (!cur) return;
  try {
    const fresh = await getJSON('/chats/' + cur.chat.id);
    cur.chat = fresh;
    if (fresh.running) attach(); else { cur.live = null; setRunning(false); updateHeader(); renderThread(); scrollToEnd(false); }
  } catch (e) { if (e instanceof AuthError) handleErr(e); else setTimeout(recover, 3000); }
}
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  refreshList();
  if (cur && cur.live) recover();
});

/* ---- copy buttons on code blocks ---- */
document.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-md-copy]'); if (!b) return;
  const ok = await copyText(b.closest('.md-code').querySelector('code').textContent);
  b.textContent = ok ? 'Copied' : 'Copy failed'; b.classList.toggle('done', ok);
  setTimeout(() => { b.textContent = 'Copy'; b.classList.remove('done'); }, 1600);
});

/* ---- keep the composer above the on-screen keyboard (iOS does not resize the layout viewport) ---- */
if (window.visualViewport) {
  const vv = window.visualViewport;
  const sync = () => {
    document.documentElement.style.setProperty('--vh', vv.scale === 1 ? vv.height + 'px' : '100dvh');
    if (vv.scale === 1 && vv.offsetTop) window.scrollTo(0, 0);
  };
  vv.addEventListener('resize', sync); vv.addEventListener('scroll', sync); sync();
}

/* ===================== routing ===================== */
async function route() {
  if (!token) return showLogin();
  mountShell();
  const shell = $('.shell');
  const m = location.hash.match(/^#\/c\/([0-9a-f]{32})$/);
  if (m) { shell.dataset.view = 'chat'; await openChat(m[1]); }
  else { shell.dataset.view = 'list'; teardownChat(); showEmptyPane(); renderList(); }
  refreshList();
}
addEventListener('hashchange', route);
route();

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
