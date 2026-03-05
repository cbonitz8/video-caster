"""Single-page app HTML for the web remote control."""

REMOTE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Video Caster">
<meta name="theme-color" content="#111">
<meta name="color-scheme" content="dark">
<link rel="manifest" href="data:application/json,{&quot;name&quot;:&quot;Video Caster Remote&quot;,&quot;short_name&quot;:&quot;VCRemote&quot;,&quot;display&quot;:&quot;standalone&quot;,&quot;background_color&quot;:&quot;%23111&quot;,&quot;theme_color&quot;:&quot;%23111&quot;,&quot;start_url&quot;:&quot;/&quot;}">
<title>Video Caster Remote</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#111;--bg2:#1a1a1a;--bg3:#222;--fg:#eee;--fg2:#999;
  --accent:#7c5cff;--accent2:#5a3fd4;--danger:#e44;--success:#4c6;
  --radius:12px;--touch:48px;
  --safe-top:env(safe-area-inset-top,0px);
  --safe-bottom:env(safe-area-inset-bottom,0px);
  --safe-left:env(safe-area-inset-left,0px);
  --safe-right:env(safe-area-inset-right,0px);
}
html,body{height:100%;overflow:hidden}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--fg);
  display:flex;flex-direction:column;
  -webkit-tap-highlight-color:transparent;
  -webkit-user-select:none;user-select:none;
  padding-top:var(--safe-top);
  padding-left:var(--safe-left);
  padding-right:var(--safe-right);
}

/* ─── Status bar ─── */
.status-bar{
  display:flex;align-items:center;gap:8px;
  padding:8px 16px;background:var(--bg2);
  border-bottom:1px solid #333;flex-shrink:0;
}
.status-dot{
  width:8px;height:8px;border-radius:50%;
  background:var(--danger);flex-shrink:0;
}
.status-dot.connected{background:var(--success)}
.status-text{font-size:12px;color:var(--fg2);flex:1}
.reconnect-btn{
  background:var(--bg3);border:none;color:var(--fg);
  border-radius:6px;padding:6px 12px;font-size:12px;
  cursor:pointer;display:none;
}
.status-bar.disconnected .reconnect-btn{display:block}
.status-bar.disconnected .status-text{color:var(--danger)}

/* ─── Tab content ─── */
.tab-content{flex:1;overflow-y:auto;padding:16px;display:none}
.tab-content.active{display:flex;flex-direction:column}

/* ─── Bottom nav ─── */
nav{
  display:flex;background:var(--bg2);
  border-top:1px solid #333;padding:4px 0;
  padding-bottom:var(--safe-bottom);flex-shrink:0;
}
nav button{
  flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;
  background:none;border:none;color:var(--fg2);font-size:10px;
  padding:8px 4px;cursor:pointer;min-height:var(--touch);
}
nav button.active{color:var(--accent)}
nav button svg{width:24px;height:24px;fill:currentColor}

/* ─── Remote tab ─── */
#tabRemote{overflow:hidden}

.remote-scroll{
  flex:1;overflow-y:auto;min-height:0;
  padding:0 0 8px;
}

.now-playing{
  text-align:center;padding:12px 0 8px;
}
.now-playing .title{font-size:18px;font-weight:600;margin-bottom:4px}
.now-playing .state{font-size:13px;color:var(--fg2);text-transform:capitalize}

.controls-divider{
  height:1px;background:#333;margin:0;flex-shrink:0;
}

.remote-controls{
  flex-shrink:0;padding:8px 16px 4px;
}

.progress-wrap{padding:4px 0}
.progress-bar{
  width:100%;height:6px;background:var(--bg3);border-radius:3px;
  position:relative;cursor:pointer;margin:6px 0;
  touch-action:none;
}
.progress-fill{
  height:100%;background:var(--accent);border-radius:3px;
  pointer-events:none;width:0%;transition:width .3s linear;
}
.progress-bar .thumb{
  position:absolute;top:50%;width:18px;height:18px;
  background:var(--accent);border-radius:50%;
  transform:translate(-50%,-50%);pointer-events:none;
  left:0%;transition:left .3s linear;
}
.progress-bar.dragging .progress-fill,
.progress-bar.dragging .thumb{transition:none}
.time-row{display:flex;justify-content:space-between;font-size:12px;color:var(--fg2)}

.transport-row{
  display:flex;justify-content:center;align-items:center;gap:10px;
  padding:8px 0;
}
.transport-row button{
  background:var(--bg3);border:none;color:var(--fg);border-radius:50%;
  width:var(--touch);height:var(--touch);font-size:13px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;
}
.transport-row .play-btn{
  width:64px;height:64px;background:var(--accent);font-size:22px;
  border-radius:50%;
}
.transport-row .play-btn:active{background:var(--accent2)}

.controls-bottom-row{
  display:flex;justify-content:center;align-items:center;gap:16px;
  padding:4px 0 2px;
}
.stop-btn{
  background:var(--danger);border:none;color:#fff;
  border-radius:var(--radius);padding:12px 32px;font-size:14px;
  cursor:pointer;min-height:var(--touch);
}
.vol-btn{
  background:var(--bg3);border:none;color:var(--fg);
  border-radius:50%;width:var(--touch);height:var(--touch);
  font-size:18px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  position:relative;
}
.vol-btn:active{background:#333}

/* ─── Volume popup ─── */
.vol-popup{
  position:fixed;z-index:50;
  background:var(--bg2);border:1px solid #333;
  border-radius:var(--radius);padding:16px 14px;
  display:none;flex-direction:column;align-items:center;gap:8px;
  box-shadow:0 4px 24px rgba(0,0,0,.6);
}
.vol-popup.show{display:flex}
.vol-popup .vol-label{font-size:12px;color:var(--fg2)}
.vol-slider-v{
  writing-mode:vertical-lr;direction:rtl;
  -webkit-appearance:none;appearance:none;
  width:6px;height:140px;
  background:var(--bg3);border-radius:3px;outline:none;
}
.vol-slider-v::-webkit-slider-thumb{
  -webkit-appearance:none;width:22px;height:22px;
  background:var(--accent);border-radius:50%;cursor:pointer;
}
.vol-backdrop{
  position:fixed;top:0;left:0;right:0;bottom:0;
  z-index:49;display:none;
}
.vol-backdrop.show{display:block}

/* ─── Browse content ─── */
.section-title{font-size:13px;color:var(--fg2);font-weight:600;padding:8px 0 4px;text-transform:uppercase;letter-spacing:.5px}
.file-list{list-style:none}
.file-item{
  padding:12px;background:var(--bg2);border-radius:var(--radius);
  margin-bottom:8px;cursor:pointer;display:flex;align-items:center;gap:12px;
  min-height:var(--touch);
}
.file-item:active{background:var(--bg3)}
.file-item .icon{font-size:20px;flex-shrink:0}
.file-item .info{flex:1;overflow:hidden}
.file-item .name{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.file-item .meta{font-size:11px;color:var(--fg2);margin-top:2px}
.file-item .progress-mini{
  height:3px;background:var(--bg3);border-radius:2px;margin-top:4px;
}
.file-item .progress-mini-fill{height:100%;background:var(--accent);border-radius:2px}
.empty-msg{color:var(--fg2);text-align:center;padding:32px 0;font-size:14px}

.breadcrumb{
  display:flex;flex-wrap:wrap;gap:4px;padding:8px 0;font-size:13px;
  align-items:center;
}
.breadcrumb span{color:var(--fg2);cursor:pointer;padding:4px 6px;border-radius:6px}
.breadcrumb span:active{background:var(--bg3)}
.breadcrumb .sep{color:#555;cursor:default;padding:0 2px}
.breadcrumb .sep:active{background:none}

.folder-item{
  padding:12px;background:var(--bg2);border-radius:var(--radius);
  margin-bottom:8px;cursor:pointer;display:flex;align-items:center;gap:12px;
  min-height:var(--touch);
}
.folder-item:active{background:var(--bg3)}
.folder-item .icon{font-size:20px;flex-shrink:0}
.folder-item .name{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}

/* ─── Devices tab ─── */
.device-item{
  padding:14px;background:var(--bg2);border-radius:var(--radius);
  margin-bottom:8px;cursor:pointer;display:flex;align-items:center;gap:12px;
  min-height:var(--touch);
}
.device-item:active{background:var(--bg3)}
.device-item.selected{border:2px solid var(--accent)}
.device-item .icon{font-size:22px}
.device-item .name{font-size:14px}
.device-item .type{font-size:11px;color:var(--fg2)}
.scan-btn{
  display:block;width:100%;background:var(--bg3);border:none;color:var(--fg);
  border-radius:var(--radius);padding:14px;font-size:14px;cursor:pointer;
  margin-top:12px;min-height:var(--touch);
}
.scan-btn:active{background:#333}

/* ─── Toast ─── */
.toast{
  position:fixed;bottom:80px;left:50%;transform:translateX(-50%);
  background:#333;color:var(--fg);padding:10px 20px;border-radius:20px;
  font-size:13px;z-index:99;opacity:0;transition:opacity .3s;
  pointer-events:none;white-space:nowrap;
}
.toast.show{opacity:1}
</style>
</head>
<body>

<!-- Status bar -->
<div class="status-bar" id="statusBar">
  <span class="status-dot" id="statusDot"></span>
  <span class="status-text" id="statusText">Connecting...</span>
  <button class="reconnect-btn" id="btnReconnect">Reconnect</button>
</div>

<!-- Remote tab (browse + controls unified) -->
<div class="tab-content active" id="tabRemote">
  <div class="remote-scroll">
    <div class="now-playing">
      <div class="title" id="npTitle">Nothing playing</div>
      <div class="state" id="npState">idle</div>
    </div>
    <div id="browseContent"></div>
  </div>
  <div class="controls-divider"></div>
  <div class="remote-controls">
    <div class="progress-wrap">
      <div class="progress-bar" id="progressBar">
        <div class="progress-fill" id="progressFill"></div>
        <div class="thumb" id="progressThumb"></div>
      </div>
      <div class="time-row">
        <span id="timeCurrent">0:00</span>
        <span id="timeDuration">0:00</span>
      </div>
    </div>
    <div class="transport-row">
      <button onclick="seek(-60)">-60</button>
      <button onclick="seek(-10)">-10</button>
      <button class="play-btn" id="btnPlayPause">&#9654;</button>
      <button onclick="seek(10)">+10</button>
      <button onclick="seek(60)">+60</button>
    </div>
    <div class="controls-bottom-row">
      <button class="stop-btn" onclick="postCmd('/api/playback/stop')">Stop</button>
      <button class="vol-btn" id="btnVolume">&#128264;</button>
    </div>
  </div>
</div>

<!-- Devices tab -->
<div class="tab-content" id="tabDevices">
  <div id="deviceList"></div>
  <button class="scan-btn" onclick="scanDevices()">Scan for devices</button>
</div>

<!-- Volume popup + backdrop -->
<div class="vol-backdrop" id="volBackdrop"></div>
<div class="vol-popup" id="volPopup">
  <div class="vol-label" id="volLabel">100%</div>
  <input type="range" class="vol-slider-v" id="volumeSlider" min="0" max="100" value="100">
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<!-- Bottom nav -->
<nav>
  <button class="active" data-tab="tabRemote">
    <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
    Remote
  </button>
  <button data-tab="tabDevices">
    <svg viewBox="0 0 24 24"><path d="M21 3H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h5v2h8v-2h5c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 14H3V5h18v12z"/></svg>
    Devices
  </button>
</nav>

<script>
const API = location.origin;
let ws, wsRetry = 1000;
let state = {state:'idle',current_time:0,duration:0,volume:1,title:''};
let devices = [], selectedDeviceId = null;
let dragging = false;
let browsePath = null;

// ─── Toast ───
function showToast(msg, ms) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), ms || 2500);
}

// ─── Status bar ───
function setConnected(connected) {
  const bar = document.getElementById('statusBar');
  const dot = document.getElementById('statusDot');
  const txt = document.getElementById('statusText');
  if (connected) {
    bar.classList.remove('disconnected');
    dot.classList.add('connected');
    txt.textContent = 'Connected';
  } else {
    bar.classList.add('disconnected');
    dot.classList.remove('connected');
    txt.textContent = 'Disconnected';
  }
}

document.getElementById('btnReconnect').onclick = () => {
  document.getElementById('statusText').textContent = 'Reconnecting...';
  if (ws) { try { ws.close(); } catch(e){} }
  connectWS();
  fetch(API+'/api/status').then(r=>r.json()).then(updateStatus).catch(()=>{});
  fetch(API+'/api/devices').then(r=>r.json()).then(d=>{devices=d;renderDevices()}).catch(()=>{});
};

// ─── WebSocket ───
function connectWS() {
  ws = new WebSocket('ws://'+location.host+'/ws');
  ws.onopen = () => {
    setConnected(true);
    wsRetry = 1000;
  };
  ws.onclose = () => {
    setConnected(false);
    setTimeout(connectWS, wsRetry);
    wsRetry = Math.min(wsRetry * 1.5, 10000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'status') updateStatus(msg.data);
    else if (msg.type === 'devices') updateDevices(msg.data);
  };
}
connectWS();

// ─── Status updates ───
function updateStatus(s) {
  state = s;
  document.getElementById('npTitle').textContent = s.title || 'Nothing playing';
  document.getElementById('npState').textContent = s.state;
  if (!dragging) {
    const pct = s.duration > 0 ? (s.current_time / s.duration * 100) : 0;
    document.getElementById('progressFill').style.width = pct + '%';
    document.getElementById('progressThumb').style.left = pct + '%';
  }
  document.getElementById('timeCurrent').textContent = fmtTime(s.current_time);
  document.getElementById('timeDuration').textContent = fmtTime(s.duration);
  const btn = document.getElementById('btnPlayPause');
  btn.innerHTML = s.state === 'playing' ? '&#9646;&#9646;' : '&#9654;';
  const vol = Math.round(s.volume * 100);
  document.getElementById('volumeSlider').value = vol;
  document.getElementById('volLabel').textContent = vol + '%';
}

function fmtTime(secs) {
  if (!secs || secs < 0) return '0:00';
  const h = Math.floor(secs/3600), m = Math.floor((secs%3600)/60), s = Math.floor(secs%60);
  return h > 0 ? h+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')
               : m+':'+String(s).padStart(2,'0');
}

// ─── Commands ───
async function postCmd(url, body) {
  try {
    await fetch(API+url, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch(e) { console.error(e); }
}

document.getElementById('btnPlayPause').onclick = () => postCmd('/api/playback/toggle');

async function seek(offset) {
  const target = Math.max(0, state.current_time + offset);
  await postCmd('/api/playback/seek', {position: target});
}

// ─── Volume popup ───
const volBtn = document.getElementById('btnVolume');
const volPopup = document.getElementById('volPopup');
const volBackdrop = document.getElementById('volBackdrop');
const volSlider = document.getElementById('volumeSlider');
const volLabel = document.getElementById('volLabel');

function showVolume() {
  const rect = volBtn.getBoundingClientRect();
  volPopup.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
  volPopup.style.right = (window.innerWidth - rect.right) + 'px';
  volPopup.classList.add('show');
  volBackdrop.classList.add('show');
}
function hideVolume() {
  volPopup.classList.remove('show');
  volBackdrop.classList.remove('show');
}
volBtn.onclick = () => {
  if (volPopup.classList.contains('show')) hideVolume();
  else showVolume();
};
volBackdrop.onclick = hideVolume;

volSlider.addEventListener('input', (e) => {
  volLabel.textContent = e.target.value + '%';
});
volSlider.addEventListener('change', (e) => {
  postCmd('/api/playback/volume', {level: e.target.value / 100});
});

// ─── Progress bar dragging ───
const bar = document.getElementById('progressBar');
function seekFromEvent(e) {
  const rect = bar.getBoundingClientRect();
  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  document.getElementById('progressFill').style.width = (pct*100)+'%';
  document.getElementById('progressThumb').style.left = (pct*100)+'%';
  return pct;
}

bar.addEventListener('pointerdown', (e) => {
  dragging = true;
  bar.classList.add('dragging');
  bar.setPointerCapture(e.pointerId);
  seekFromEvent(e);
});
bar.addEventListener('pointermove', (e) => { if(dragging) seekFromEvent(e); });
bar.addEventListener('pointerup', (e) => {
  if (!dragging) return;
  dragging = false;
  bar.classList.remove('dragging');
  const pct = seekFromEvent(e);
  if (state.duration > 0) postCmd('/api/playback/seek', {position: pct * state.duration});
});

// ─── Browse content ───
async function loadBrowse() {
  try {
    if (browsePath === null) {
      const res = await fetch(API+'/api/files');
      const data = await res.json();
      renderBrowseHome(data);
    } else {
      const res = await fetch(API+'/api/files/browse?path='+encodeURIComponent(browsePath));
      const entries = await res.json();
      renderBrowseFolder(entries);
    }
  } catch(e) {
    document.getElementById('browseContent').innerHTML = '<div class="empty-msg">Failed to load</div>';
  }
}

function renderBrowseHome(data) {
  let html = '';
  if (data.continue_watching && data.continue_watching.length) {
    html += '<div class="section-title">Continue Watching</div><ul class="file-list">';
    data.continue_watching.forEach(f => {
      const pct = f.duration > 0 ? Math.round(f.position/f.duration*100) : 0;
      html += '<li class="file-item" data-cast-path="'+esc(f.file_path)+'" data-cast-resume="true">'
        + '<div class="icon">&#9654;</div><div class="info">'
        + '<div class="name">'+esc(f.file_name)+'</div>'
        + '<div class="meta">'+pct+'% watched</div>'
        + '<div class="progress-mini"><div class="progress-mini-fill" style="width:'+pct+'%"></div></div>'
        + '</div></li>';
    });
    html += '</ul>';
  }
  if (data.recently_added && data.recently_added.length) {
    html += '<div class="section-title">Recently Added</div><ul class="file-list">';
    data.recently_added.forEach(f => {
      html += '<li class="file-item" data-cast-path="'+esc(f.path)+'" data-cast-resume="false">'
        + '<div class="icon">&#128253;</div><div class="info">'
        + '<div class="name">'+esc(f.name)+'</div>'
        + '<div class="meta">'+esc(f.mtime_ago)+'</div>'
        + '</div></li>';
    });
    html += '</ul>';
  }
  if (data.watch_folders && data.watch_folders.length) {
    html += '<div class="section-title">Watch Folders</div>';
    data.watch_folders.forEach(f => {
      html += '<div class="folder-item" data-browse-path="'+esc(f.path)+'">'
        + '<div class="icon">&#128193;</div>'
        + '<div class="name">'+esc(f.name)+'</div></div>';
    });
  }
  if (!html) html = '<div class="empty-msg">No files found</div>';
  document.getElementById('browseContent').innerHTML = html;
}

function renderBrowseFolder(entries) {
  let html = '';
  html += buildBreadcrumb(browsePath);
  if (!entries.length) {
    html += '<div class="empty-msg">Empty folder</div>';
  } else {
    entries.forEach(e => {
      if (e.is_dir) {
        html += '<div class="folder-item" data-browse-path="'+esc(e.path)+'">'
          + '<div class="icon">&#128193;</div>'
          + '<div class="name">'+esc(e.name)+'</div></div>';
      } else {
        const sizeMB = e.size ? (e.size/1048576).toFixed(0)+' MB' : '';
        html += '<li class="file-item" data-cast-path="'+esc(e.path)+'" data-cast-resume="false">'
          + '<div class="icon">&#127916;</div><div class="info">'
          + '<div class="name">'+esc(e.name)+'</div>'
          + (sizeMB ? '<div class="meta">'+sizeMB+'</div>' : '')
          + '</div></li>';
      }
    });
  }
  document.getElementById('browseContent').innerHTML = html;
}

function buildBreadcrumb(path) {
  const parts = path.split('/').filter(Boolean);
  let html = '<div class="breadcrumb">';
  html += '<span data-browse-path="">Home</span>';
  let accumulated = '';
  for (let i = 0; i < parts.length; i++) {
    accumulated += '/' + parts[i];
    html += '<span class="sep">/</span>';
    html += '<span data-browse-path="'+esc(accumulated)+'">'+esc(parts[i])+'</span>';
  }
  html += '</div>';
  return html;
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

document.getElementById('browseContent').addEventListener('click', (e) => {
  const browseItem = e.target.closest('[data-browse-path]');
  if (browseItem) {
    const p = browseItem.dataset.browsePath;
    browsePath = p || null;
    loadBrowse();
    return;
  }
  const item = e.target.closest('[data-cast-path]');
  if (item) castFile(item.dataset.castPath, item.dataset.castResume === 'true');
});

async function castFile(path, resume) {
  try {
    const res = await fetch(API+'/api/cast', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path, resume}),
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      showToast(data.error || 'Cast failed');
      return;
    }
    if (data.device) {
      showToast('Casting to ' + data.device);
      const dev = devices.find(d => d.name === data.device);
      if (dev) { selectedDeviceId = dev.id; renderDevices(); }
    }
    switchTab('tabRemote');
  } catch(e) { showToast('Cast failed: ' + e.message); }
}

// ─── Devices tab ───
function updateDevices(devs) {
  devices = devs;
  renderDevices();
}

function renderDevices() {
  if (!devices.length) {
    document.getElementById('deviceList').innerHTML = '<div class="empty-msg">No devices found</div>';
    return;
  }
  const icons = {chromecast:'\\u25ce', appletv:'\\u25c6', dlna:'\\u25a8'};
  let html = '';
  devices.forEach(d => {
    const sel = d.id === selectedDeviceId ? ' selected' : '';
    html += '<div class="device-item'+sel+'" data-device-id="'+esc(d.id)+'">'
      + '<div class="icon">'+(icons[d.device_type]||'\\u25cb')+'</div>'
      + '<div><div class="name">'+esc(d.name)+'</div>'
      + '<div class="type">'+esc(d.device_type)+'</div></div></div>';
  });
  document.getElementById('deviceList').innerHTML = html;
}

document.getElementById('deviceList').addEventListener('click', (e) => {
  const item = e.target.closest('[data-device-id]');
  if (item) selectDevice(item.dataset.deviceId);
});

async function selectDevice(id) {
  selectedDeviceId = id;
  renderDevices();
  await postCmd('/api/device/select', {device_id: id});
}

async function scanDevices() {
  document.querySelector('.scan-btn').textContent = 'Scanning...';
  await postCmd('/api/devices/scan');
  setTimeout(() => { document.querySelector('.scan-btn').textContent = 'Scan for devices'; }, 3000);
}

// ─── Tab switching ───
document.querySelectorAll('nav button').forEach(btn => {
  btn.onclick = () => switchTab(btn.dataset.tab);
});

function switchTab(id) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  document.querySelector('nav button[data-tab="'+id+'"]').classList.add('active');
}

// ─── Init ───
fetch(API+'/api/devices').then(r=>r.json()).then(d=>{devices=d;renderDevices()}).catch(()=>{});
fetch(API+'/api/status').then(r=>r.json()).then(updateStatus).catch(()=>{});
loadBrowse();
</script>
</body>
</html>
"""
