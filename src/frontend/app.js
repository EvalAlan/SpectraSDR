/**
 * SpectraSDR - Full Frontend (Phase 3.5/4 Restored)
 */

let ws = null;
let connected = false;
let streaming = false;
let currentFreq = 88700000;
let currentMode = 'FM';
let currentSampleRate = 2400000;

let audioCtx = null;
let audioWorklet = null;
let gainNode = null;
let audioInitialized = false;

let specCtx, watCtx;
let specCanvas, watCanvas;

let vizGain = 1.0;
let vizOffset = 0.0;
let autoScale = true;
let manualMinDb = -80;
let manualMaxDb = -20;
let connectionProfiles = [];
let selectedConnectionId = null;
let connectionListEl = null;
let connectionStatusLine = null;
let connectionConnected = false;
let activeConnectionId = null;
let activeConnectionName = "";

let connectionHost = null;
let connectionPort = null;
let connectionDriver = null;
let connectionSampleRate = null;
let adsbAircraft = new Map();
let decoderStates = new Map();


const PALETTES = {
  classic: [[0,0,0], [0,255,255], [255,0,255], [255,255,255]], 
  magma: [[0,0,4], [81,18,124], [183,55,121], [252,137,97], [251,252,191]],
  viridis: [[68,1,84], [59,81,139], [33,145,140], [94,201,98], [253,231,37]],
  inferno: [[0,0,4], [87,15,109], [187,55,84], [249,142,9], [252,255,164]],
  plasma: [[13,8,135], [126,3,168], [204,71,120], [248,149,64], [240,249,33]]
};
let currentPalette = 'classic';

let lastWaterfallDraw = 0;
const WATERFALL_FPS = 25;
const WATERFALL_FPS_STREAMING = 15;
const SPECTRUM_DB_MIN = -120;
const SPECTRUM_DB_MAX = 0;
const SPECTRUM_DB_STEP = 20;

window.addEventListener('DOMContentLoaded', () => {
  specCanvas = document.getElementById('spectrum-canvas');
  watCanvas  = document.getElementById('waterfall-canvas');
  specCtx    = specCanvas.getContext('2d');
  watCtx     = watCanvas.getContext('2d');

  resize();
  window.addEventListener('resize', resize);

  wireControls();
  connect();
  loadBookmarks();
  loadScanHits();
  initMap();
  loadAdsbAircraft();
  setInterval(loadAdsbAircraft, 10000);
  setInterval(removeStaleMarkers, 30000);
});

function resize() {
  const dpr = window.devicePixelRatio || 1;
  const w = specCanvas.clientWidth;
  if (w === 0) return;
  specCanvas.width  = w * dpr;
  specCanvas.height = 300 * dpr;
  specCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  watCanvas.width  = w * dpr;
  watCanvas.height = 400 * dpr;
}

function wireControls() {
  const modeButtons = document.querySelectorAll('.mode-grid .mode-btn[data-mode]');
  modeButtons.forEach(btn => {
    btn.onclick = () => {
      modeButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentMode = btn.dataset.mode;
      sendJSON({ type: 'SET_MODE', mode: currentMode });
    };
  });

  const vol = document.getElementById('volume-slider');
  if (vol) vol.oninput = () => {
    if (gainNode) gainNode.gain.value = Math.pow(vol.value / 100, 2);
    document.getElementById('volume-value').textContent = vol.value + '%';
  };

  const sq = document.getElementById('squelch-slider');
  if (sq) sq.oninput = () => {
    sendJSON({ type: 'SET_SQUELCH', value: parseFloat(sq.value) });
    document.getElementById('squelch-value').textContent = sq.value + ' dB';
  };

  document.getElementById('rf-gain-slider').oninput = (e) => {
    sendJSON({ type: 'SET_GAIN', value: parseInt(e.target.value) });
  };

  document.getElementById('chk-agc').onchange = (e) => {
    sendJSON({ type: 'SET_AGC', value: e.target.checked });
  };

  const scanSpeed = document.getElementById('scan-speed-slider');
  if (scanSpeed) scanSpeed.oninput = (e) => {
    sendJSON({ type: 'SET_SCAN_SPEED', value: parseInt(e.target.value) });
    const label = document.getElementById('scan-speed-value');
    if (label) label.textContent = e.target.value + ' ms';
  };

  const vizGainSlider = document.getElementById('viz-gain-slider');
  if (vizGainSlider) vizGainSlider.oninput = (e) => {
    vizGain = parseFloat(e.target.value);
    const label = document.getElementById('viz-gain-value');
    if (label) label.textContent = vizGain.toFixed(1) + 'x';
  };

  const vizOffsetSlider = document.getElementById('viz-offset-slider');
  if (vizOffsetSlider) vizOffsetSlider.oninput = (e) => {
    vizOffset = parseFloat(e.target.value);
    const label = document.getElementById('viz-offset-value');
    if (label) label.textContent = vizOffset.toFixed(1);
  };

  connectionListEl = document.getElementById('connection-list');
  connectionStatusLine = document.getElementById('conn-status-line');

  document.getElementById('btn-bookmarks-toggle').onclick = () => {
    document.getElementById('bookmarks-panel').classList.toggle('open');
  };

  document.getElementById('btn-add-bookmark').onclick = openAddBookmarkModal;
  document.getElementById('btn-save-bookmark').onclick = saveBookmark;
  document.getElementById('btn-cancel-bookmark').onclick = () => {
    document.getElementById('bookmark-modal').style.display = 'none';
  };

  document.getElementById('btn-power').onclick = toggleHardwareConnection;
  document.getElementById('btn-connect-modal').onclick = openConnectionModal;
  document.getElementById('btn-close-connect').onclick = closeConnectionModal;
  document.getElementById('btn-save-connection').onclick = saveConnectionProfile;
  document.getElementById('btn-delete-connection').onclick = deleteConnectionProfile;
  document.getElementById('btn-do-connect').onclick = () => {
    connectFromForm();
    closeConnectionModal();
  };
  document.getElementById('btn-disconnect').onclick = disconnectHardware;
  loadConnectionProfiles().catch(err => console.error('Failed to load connections', err));
  const hitMode = document.getElementById('scan-hit-mode');
  const refreshHitsBtn = document.getElementById('btn-refresh-hits');
  const refreshAdsbBtn = document.getElementById('btn-refresh-adsb');
  const exportCsvBtn = document.getElementById('btn-export-csv');
  const exportJsonBtn = document.getElementById('btn-export-json');
  const pruneHitsBtn = document.getElementById('btn-prune-hits');
  const refreshAnalyticsBtn = document.getElementById('btn-refresh-analytics');
  if (hitMode) hitMode.onchange = () => { loadScanHits(); loadAnalytics(); };
  const hitScanMode = document.getElementById('scan-hit-scan-mode');
  if (hitScanMode) hitScanMode.onchange = () => { loadScanHits(); loadAnalytics(); };
  const hitProfile = document.getElementById('scan-hit-profile');
  if (hitProfile) hitProfile.onchange = () => { loadScanHits(); loadAnalytics(); };
  if (refreshHitsBtn) refreshHitsBtn.onclick = () => { loadScanHits(); loadAnalytics(); };
  if (refreshAdsbBtn) refreshAdsbBtn.onclick = () => loadAdsbAircraft();
  if (exportCsvBtn) exportCsvBtn.onclick = () => exportScanHitsCsv();
  if (exportJsonBtn) exportJsonBtn.onclick = () => exportScanHitsJson();
  if (pruneHitsBtn) pruneHitsBtn.onclick = () => pruneScanHits();
  if (refreshAnalyticsBtn) refreshAnalyticsBtn.onclick = () => loadAnalytics();
  // Auto-refresh hits+analytics on time range changes
  const hitFrom = document.getElementById('scan-hit-from');
  const hitTo = document.getElementById('scan-hit-to');
  const hitHours = document.getElementById('scan-hit-hours');
  if (hitFrom) hitFrom.onchange = () => { loadScanHits(); loadAnalytics(); };
  if (hitTo) hitTo.onchange = () => { loadScanHits(); loadAnalytics(); };
  if (hitHours) hitHours.onchange = () => { loadScanHits(); loadAnalytics(); };

  document.getElementById('btn-scan').onclick = toggleScan;
  document.getElementById('btn-range-scan').onclick = startRangeScan;
  document.getElementById('btn-skip').onclick = () => sendJSON({ type: 'SKIP_SCAN' });
  
  document.getElementById('btn-start').onclick = toggleStream;
  document.getElementById('btn-set-freq').onclick = setFreq;

  document.getElementById('btn-rec-audio').onclick = toggleRecordAudio;
  document.getElementById('btn-rec-iq').onclick = toggleRecordIQ;
  
  document.getElementById('chk-pocsag').onchange = (e) => {
    sendJSON({ type: 'TOGGLE_DECODER', name: 'pocsag', value: e.target.checked });
    decoderStates.set('pocsag', !!e.target.checked);
    updatePluginStatus();
    document.getElementById('decoder-log').style.display = e.target.checked ? 'block' : 'none';
  };

  const adsbToggle = document.getElementById('chk-adsb');
  if (adsbToggle) {
    adsbToggle.onchange = (e) => {
      sendJSON({ type: 'TOGGLE_DECODER', name: 'adsb', value: e.target.checked });
      decoderStates.set('adsb', !!e.target.checked);
      updatePluginStatus();
      if (e.target.checked) {
        reopenAdsbMap();
        loadAdsbAircraft();
      }
      // Reflect the change immediately instead of waiting on the server echo.
      syncDecoderCheckboxes();
    };
  }

  const themeSel = document.getElementById('waterfall-theme');
  if (themeSel) themeSel.onchange = (e) => {
    currentPalette = e.target.value;
  };

  // Mouse wheel tuning over spectrum
  specCanvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const step = e.shiftKey ? 1000 : 10000;
    const delta = e.deltaY < 0 ? step : -step;
    sendJSON({ type: 'SET_FREQ', value: currentFreq + delta });
  }, { passive: false });
}

function connect() {
  const host = location.hostname || '127.0.0.1';
  ws = new WebSocket(`ws://${host}:8765`);
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => {
    document.getElementById('status-text').textContent = 'CONNECTED';
    document.getElementById('status-dot').style.background = 'var(--accent)';
    connected = true;
    sendJSON({ type: 'GET_SCAN_CATEGORIES' });
    sendJSON({ type: 'LIST_DECODERS' });
  };
  ws.onclose = () => {
    document.getElementById('status-text').textContent = 'DISCONNECTED';
    document.getElementById('status-dot').style.background = 'var(--accent-red)';
    connected = false;
    setStreamingUI(false); // Reset streaming state on disconnect
    setTimeout(connect, 2000);
  };
  ws.onmessage = (e) => {
    if (typeof e.data === 'string') handleJSON(JSON.parse(e.data));
    else handleBinary(e.data);
  };
}

function sendJSON(obj) { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj)); }

function handleJSON(msg) {
  switch (msg.type) {
    case 'STATE':
      if (msg.freq) updateFreq(msg.freq);
      if (msg.mode) setModeUI(msg.mode);
      if (msg.sample_rate) currentSampleRate = msg.sample_rate;
      if (msg.rtl_host && !selectedConnectionId) document.getElementById('conn-host').value = msg.rtl_host;
      if (msg.rtl_port && !selectedConnectionId) document.getElementById('conn-port').value = msg.rtl_port;
      if (msg.streaming !== undefined) setStreamingUI(msg.streaming);
      if (msg.iq_recording !== undefined) { iqRecording = msg.iq_recording; updateRecordUI(); }
      if (msg.audio_recording !== undefined) { audioRecording = msg.audio_recording; updateRecordUI(); }
      if (msg.connection_id) {
        activeConnectionId = msg.connection_id;
        selectedConnectionId = msg.connection_id;
      }
      if (msg.connection_name) activeConnectionName = msg.connection_name;
      if (msg.connection_driver) connectionDriver = msg.connection_driver;
      if (msg.connection_sample_rate) connectionSampleRate = msg.connection_sample_rate;
      if (msg.connection_host) connectionHost = msg.connection_host;
      if (msg.connection_port) connectionPort = msg.connection_port;
      if (msg.connected !== undefined) connectionConnected = msg.connected;
      updateConnectionStatusLine();
      break;
    case 'FREQ_CHANGED': updateFreq(msg.value); break;
    case 'MODE_CHANGED': setModeUI(msg.mode); break;
    case 'CONNECTION_CHANGED':
      if (msg.host) document.getElementById('conn-host').value = msg.host;
      if (msg.port) document.getElementById('conn-port').value = msg.port;
      if (msg.driver) document.getElementById('conn-driver').value = msg.driver;
      if (msg.sample_rate) document.getElementById('conn-sample-rate').value = msg.sample_rate;
      connectionHost = msg.host || connectionHost;
      connectionPort = msg.port || connectionPort;
      connectionDriver = msg.driver || connectionDriver;
      connectionSampleRate = msg.sample_rate || connectionSampleRate;
      connectionConnected = msg.connected !== undefined ? msg.connected : connectionConnected;
      if (msg.profile_id) {
        activeConnectionId = msg.profile_id;
        selectedConnectionId = msg.profile_id;
      }
      if (msg.name) activeConnectionName = msg.name;
      updateConnectionStatusLine();
      break;
    case 'SIGNAL_LEVEL':
      const pct = Math.max(0, Math.min(100, ((msg.db + 90) / 90) * 100));
      document.getElementById('s-meter-bar').style.width = pct + '%';
      document.getElementById('s-meter-reading').textContent = msg.s_units || 'S0';
      break;
    case 'STREAM_STATE':
      setStreamingUI(msg.streaming);
      break;
    case 'SCAN_STATUS':
      updateScanStatus(msg);
      break;
    case 'SCAN_CATEGORIES':
      populateScanCategories(msg.categories);
      break;
    case 'DECODER_LIST':
      decoderStates = new Map((msg.decoders || []).map(d => [d.name, !!d.enabled]));
      updatePluginStatus(msg.decoders || []);
      syncDecoderCheckboxes();
      break;
    case 'DECODER_STATE':
      if (msg.name) decoderStates.set(msg.name, !!msg.enabled);
      updatePluginStatus();
      syncDecoderCheckboxes();
      break;
    case 'DECODER_STATUS':
      if (msg.status) {
        const badge = document.querySelector(`.plugin-row .plugin-name[data-decoder="${msg.status.name}"]`);
        if (badge) updateDecoderHealthBadge(msg.status);
      }
      if (msg.all) {
        msg.all.forEach(updateDecoderHealthBadge);
      }
      break;
    case 'RECORD_STATUS':
      audioRecording = !!msg.audio;
      iqRecording = !!msg.iq;
      updateRecordUI();
      break;
    case 'POCSAG':
      appendDecoderLog(msg.message);
      break;
    case 'ADSB':
      if (msg.message) mergeAdsbAircraft(msg.message);
      break;
    case 'ADSB_SNAPSHOT':
      if (Array.isArray(msg.aircraft)) {
        adsbAircraft = new Map(msg.aircraft.map(a => [a.icao || `${a.source}:${a.raw || ''}`, a]));
        renderAdsbAircraft();
      }
      break;
  }
}

function setStreamingUI(state) {
  streaming = state;
  const btn = document.getElementById('btn-start');
  if (btn) {
    btn.textContent = streaming ? '■ STOP' : '▶ START';
    btn.classList.toggle('active', streaming);
  }
}

function handleBinary(buf) {
  const view = new Uint8Array(buf);
  const prefix = view[0];
  // Copy to ensure alignment for Float32Array
  const alignedData = new Float32Array(buf.slice(1));
  
  if (prefix === 0x01) {
    drawSpectrum(alignedData);
    drawWaterfall(alignedData);
  } else if (prefix === 0x02) {
    if (audioWorklet && audioInitialized) {
      audioWorklet.port.postMessage(alignedData);
    }
  }
}

function fftIndexForPixel(px, plotW, dataLength) {
  // Use pixel-center sampling to avoid systematic half-bin left bias.
  const normalized = (px + 0.5) / Math.max(1, plotW);
  const idx = Math.floor(normalized * dataLength);
  return Math.max(0, Math.min(dataLength - 1, idx));
}

function drawSpectrum(data) {
  const dpr = window.devicePixelRatio || 1;
  const w = specCanvas.width / dpr;
  const h = 300;
  const leftPad = 46;
  const plotW = Math.max(1, w - leftPad);

  specCtx.fillStyle = '#0a0a12';
  specCtx.fillRect(0, 0, w, h);

  // dB axis (left)
  specCtx.strokeStyle = 'rgba(255,255,255,0.18)';
  specCtx.fillStyle = 'rgba(255,255,255,0.62)';
  specCtx.font = '10px monospace';
  specCtx.textAlign = 'right';
  specCtx.textBaseline = 'middle';
  for (let db = SPECTRUM_DB_MAX; db >= SPECTRUM_DB_MIN; db -= SPECTRUM_DB_STEP) {
    const y = ((SPECTRUM_DB_MAX - db) / (SPECTRUM_DB_MAX - SPECTRUM_DB_MIN)) * h;
    specCtx.beginPath();
    specCtx.moveTo(leftPad - 4, y);
    specCtx.lineTo(w, y);
    specCtx.stroke();
    specCtx.fillText(`${db}`, leftPad - 8, y);
  }
  specCtx.fillStyle = 'rgba(255,255,255,0.5)';
  specCtx.fillText('dB', leftPad - 8, 10);
  specCtx.beginPath();
  specCtx.moveTo(leftPad, 0);
  specCtx.lineTo(leftPad, h);
  specCtx.stroke();

  // Draw Grid/Markers
  const startFreq = currentFreq - currentSampleRate / 2;
  const endFreq = currentFreq + currentSampleRate / 2;
  const bw = currentSampleRate;

  // Decide on step size based on bandwidth
  let step = 100000;
  if (bw > 5e6) step = 1000000;
  else if (bw > 2e6) step = 200000;
  else if (bw < 500000) step = 50000;

  const firstTick = Math.ceil(startFreq / step) * step;

  specCtx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
  specCtx.fillStyle = 'rgba(255, 255, 255, 0.4)';
  specCtx.font = '10px monospace';
  specCtx.textAlign = 'center';
  specCtx.textBaseline = 'alphabetic';
  specCtx.lineWidth = 1;

  for (let f = firstTick; f <= endFreq; f += step) {
    const x = leftPad + ((f - startFreq) / bw) * plotW;
    // Vertical grid line
    specCtx.beginPath();
    specCtx.moveTo(x, 0);
    specCtx.lineTo(x, h);
    specCtx.stroke();

    // Freq Label at top
    const mhz = (f / 1e6).toFixed(1);
    specCtx.fillText(mhz, x, 12);
    // Ticks at bottom
    specCtx.fillRect(x - 0.5, h - 10, 1, 10);
  }

  // Center frequency red line
  specCtx.strokeStyle = 'rgba(255, 0, 0, 0.4)';
  specCtx.beginPath();
  specCtx.moveTo(leftPad + plotW / 2, 0);
  specCtx.lineTo(leftPad + plotW / 2, h);
  specCtx.stroke();

  // Draw the signal trace
  specCtx.beginPath();
  specCtx.strokeStyle = '#00ff88';
  specCtx.lineWidth = 1.5;
  for (let px = 0; px < plotW; px++) {
    const i = fftIndexForPixel(px, plotW, data.length);
    const val = data[i] * vizGain + vizOffset;
    const x = leftPad + px;
    const y = h - val * h;
    if (px === 0) specCtx.moveTo(x, y); else specCtx.lineTo(x, y);
  }
  specCtx.stroke();
}

function drawWaterfall(data) {
  const now = performance.now();
  const fps = streaming ? WATERFALL_FPS_STREAMING : WATERFALL_FPS;
  if (now - lastWaterfallDraw < (1000 / fps)) return;
  lastWaterfallDraw = now;

  const dpr = window.devicePixelRatio || 1;
  const leftPadPx = Math.round(46 * dpr);
  const w = watCanvas.width;
  const plotW = Math.max(1, w - leftPadPx);

  watCtx.drawImage(watCanvas, 0, 1);

  const img = watCtx.createImageData(plotW, 1);
  const palette = PALETTES[currentPalette] || PALETTES.classic;

  for (let px = 0; px < plotW; px++) {
    const i = fftIndexForPixel(px, plotW, data.length);
    const val = Math.max(0, Math.min(0.999, data[i] * vizGain + vizOffset));
    const idx = px * 4;

    // Multi-stop interpolation
    const scaledVal = val * (palette.length - 1);
    const pi = Math.floor(scaledVal);
    const f = scaledVal - pi;
    const c1 = palette[pi];
    const c2 = palette[pi + 1];

    img.data[idx]   = c1[0] + (c2[0] - c1[0]) * f;
    img.data[idx+1] = c1[1] + (c2[1] - c1[1]) * f;
    img.data[idx+2] = c1[2] + (c2[2] - c1[2]) * f;
    img.data[idx+3] = 255;
  }

  // Keep waterfall aligned with spectrum's dB axis reserve.
  watCtx.fillStyle = '#000';
  watCtx.fillRect(0, 0, leftPadPx, 1);
  watCtx.fillStyle = 'rgba(255,255,255,0.18)';
  watCtx.fillRect(leftPadPx - 1, 0, 1, 1);

  watCtx.putImageData(img, leftPadPx, 0);
}

async function initAudio() {
  if (audioInitialized) return;
  try {
    audioCtx = new AudioContext({ sampleRate: 48000 });
    await audioCtx.audioWorklet.addModule('./audio-processor.js?v=' + Date.now());
    audioWorklet = new AudioWorkletNode(audioCtx, 'sdr-audio-processor', { outputChannelCount: [1] });
    gainNode = audioCtx.createGain();
    
    // Set initial volume from slider
    const volSlider = document.getElementById('volume-slider');
    if (volSlider) {
      gainNode.gain.value = Math.pow(volSlider.value / 100, 2);
    } else {
      gainNode.gain.value = 0.25; // 50% default
    }

    audioWorklet.connect(gainNode);
    gainNode.connect(audioCtx.destination);
    audioInitialized = true;
  } catch (e) { console.error(e); }
}

function toggleStream() {
  if (!streaming) {
    initAudio().then(() => {
      if (audioCtx.state === 'suspended') audioCtx.resume();
      sendJSON({ type: 'START_STREAM' });
    });
  } else {
    // Optimistic update so UI is responsive and button isn't stuck if backend is slow/dead
    setStreamingUI(false);
    sendJSON({ type: 'STOP_STREAM' });
    if (audioWorklet) audioWorklet.port.postMessage('CLEAR');
  }
}

function setFreq() {
  const val = parseFloat(document.getElementById('freq-input').value);
  if (!isNaN(val)) sendJSON({ type: 'SET_FREQ', value: Math.round(val * 1e6) });
}

function updateFreq(hz) {
  currentFreq = hz;
  document.getElementById('freq-readout').textContent = (hz / 1e6).toFixed(3) + ' MHz';
  document.getElementById('freq-input').value = (hz / 1e6).toFixed(3);
}

function setModeUI(mode) {
  currentMode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
}

let audioRecording = false;
let iqRecording = false;

function toggleRecordAudio() {
  if (audioRecording) {
    sendJSON({ type: 'STOP_AUDIO_RECORD' });
  } else {
    sendJSON({ type: 'START_AUDIO_RECORD' });
  }
}

function toggleRecordIQ() {
  if (iqRecording) {
    sendJSON({ type: 'STOP_IQ_RECORD' });
  } else {
    sendJSON({ type: 'START_IQ_RECORD' });
  }
}

function updateRecordUI() {
  const btnAudio = document.getElementById('btn-rec-audio');
  const btnIQ = document.getElementById('btn-rec-iq');
  const status = document.getElementById('rec-status');

  if (btnAudio) {
    btnAudio.textContent = audioRecording ? '⏹ STOP Audio' : '🔴 REC Audio';
    btnAudio.classList.toggle('recording', audioRecording);
  }
  if (btnIQ) {
    btnIQ.textContent = iqRecording ? '⏹ STOP IQ' : '🔴 REC IQ';
    btnIQ.classList.toggle('recording', iqRecording);
  }
  if (status) {
    if (audioRecording || iqRecording) {
      const parts = [];
      if (audioRecording) parts.push('Audio');
      if (iqRecording) parts.push('IQ');
      status.textContent = 'Recording: ' + parts.join(' + ');
      status.style.display = 'block';
    } else {
      status.style.display = 'none';
    }
  }
}

let cachedBookmarks = { bookmarks: [] };

function normalizeBookmarkMode(mode, frequency = null) {
  const value = String(mode || '').trim().toUpperCase();
  const alias = {
    'WFM': 'FM',
    'WBFM': 'FM',
    'NBFM': 'NFM'
  };
  const normalized = alias[value] || value;
  const valid = ['AM', 'FM', 'NFM', 'USB', 'LSB', 'CW'];
  const freq = Number(frequency || 0);

  // Legacy bookmark files were often tagged FM incorrectly for AM services.
  // Override obvious ranges so existing user data behaves sanely without manual cleanup.
  if (normalized === 'FM') {
    if ((freq >= 530000 && freq <= 1710000) || (freq >= 108000000 && freq <= 137000000)) {
      return 'AM';
    }
  }

  return valid.includes(normalized) ? normalized : '';
}

function normalizeBookmarksPayload(data) {
  const result = [];

  if (Array.isArray(data)) {
    data.forEach(entry => {
      result.push({
        frequency: entry.frequency,
        label: entry.name || entry.label || '',
        mode: normalizeBookmarkMode(entry.mode || entry.modulation || entry.demod, entry.frequency),
        tags: [String(entry.category || 'Other').trim()].filter(Boolean)
      });
    });
    return { bookmarks: result };
  }

  if (Array.isArray(data?.bookmarks)) {
    data.bookmarks.forEach(entry => {
      const tags = Array.isArray(entry.tags) ? entry.tags : (entry.tag ? [entry.tag] : []);
      result.push({
        frequency: entry.frequency,
        label: entry.label || entry.name || '',
        mode: normalizeBookmarkMode(entry.mode || entry.modulation || entry.demod, entry.frequency),
        tags: tags.map(t => String(t).trim()).filter(Boolean)
      });
    });
    return { bookmarks: result };
  }

  const addFromGrouped = (groups, keyName) => {
    (groups || []).forEach(group => {
      const groupName = String(group?.name || '').trim();
      (group?.stations || []).forEach(st => {
        const tags = new Set((st.tags || []).map(t => String(t).trim()).filter(Boolean));
        if (groupName) tags.add(groupName);
        result.push({
          frequency: st.frequency,
          label: st.label || '',
          mode: normalizeBookmarkMode(st.mode || st.modulation || st.demod, st.frequency),
          tags: Array.from(tags)
        });
      });
    });
  };

  if (Array.isArray(data?.tags)) addFromGrouped(data.tags, 'tags');
  if (Array.isArray(data?.categories)) addFromGrouped(data.categories, 'categories');

  return { bookmarks: result };
}

function getTagNames() {
  const tags = new Set();
  (cachedBookmarks.bookmarks || []).forEach(st => (st.tags || []).forEach(t => tags.add(t)));
  return Array.from(tags).sort((a, b) => a.localeCompare(b));
}

function getTagGroups() {
  const groups = {};
  (cachedBookmarks.bookmarks || []).forEach((st, idx) => {
    const tags = (st.tags && st.tags.length) ? st.tags : ['Untagged'];
    tags.forEach(tag => {
      if (!groups[tag]) groups[tag] = [];
      groups[tag].push({ station: st, index: idx });
    });
  });
  return Object.entries(groups)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([name, entries]) => ({ name, entries }));
}

async function loadBookmarks() {
  try {
    const r = await fetch('/api/bookmarks');
    const data = await r.json();
    cachedBookmarks = normalizeBookmarksPayload(data);
    renderBookmarks();
  } catch (e) { console.error(e); }
}

function renderBookmarks() {
  const list = document.getElementById('bookmarks-list');
  list.innerHTML = '';
  getTagGroups().forEach(group => {
    const section = document.createElement('div');
    section.className = 'bm-category';
    section.innerHTML = `<div class="bm-cat-header">${group.name}</div>`;
    group.entries.forEach(({ station, index }) => {
      const item = document.createElement('div');
      item.className = 'bm-item';
      item.innerHTML = `<span class="bm-label">${station.label}</span><span class="bm-freq">${(station.frequency / 1e6).toFixed(3)}</span><button class="bm-delete" title="Delete">✕</button>`;
      item.querySelector('.bm-label').onclick = () => {
        const mode = normalizeBookmarkMode(station.mode || station.modulation || station.demod, station.frequency);
        sendJSON({ type: 'SET_FREQ', value: station.frequency });
        if (mode) sendJSON({ type: 'SET_MODE', mode });
      };
      item.querySelector('.bm-freq').onclick = item.querySelector('.bm-label').onclick;
      item.querySelector('.bm-delete').onclick = (e) => {
        e.stopPropagation();
        deleteBookmark(index);
      };
      section.appendChild(item);
    });
    list.appendChild(section);
  });
}

function openAddBookmarkModal() {
  const modal = document.getElementById('bookmark-modal');
  document.getElementById('bm-freq').value = (currentFreq / 1e6).toFixed(3);
  document.getElementById('bm-mode').value = currentMode;
  document.getElementById('bm-label').value = '';
  document.getElementById('bm-new-category').value = '';
  const sel = document.getElementById('bm-category');
  sel.innerHTML = '';
  getTagNames().forEach((tag, i) => {
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = tag;
    sel.appendChild(opt);
  });
  modal.style.display = 'flex';
  document.getElementById('bm-label').focus();
}

async function saveBookmark() {
  const label = document.getElementById('bm-label').value.trim() || 'New Station';
  const freq = Math.round(parseFloat(document.getElementById('bm-freq').value) * 1e6);
  const mode = normalizeBookmarkMode(document.getElementById('bm-mode').value) || currentMode;
  const newTagRaw = document.getElementById('bm-new-category').value.trim();
  const selectedTag = getTagNames()[parseInt(document.getElementById('bm-category').value)] || '';

  const parsedNewTags = newTagRaw.split(',').map(t => t.trim()).filter(Boolean);
  const tags = Array.from(new Set(parsedNewTags.length ? parsedNewTags : (selectedTag ? [selectedTag] : ['Untagged'])));

  cachedBookmarks.bookmarks.push({ label, frequency: freq, mode, tags });

  await postBookmarks();
  document.getElementById('bookmark-modal').style.display = 'none';
}

async function deleteBookmark(bookmarkIdx) {
  const st = cachedBookmarks.bookmarks[bookmarkIdx];
  if (!st) return;
  if (!confirm(`Delete "${st.label}"?`)) return;
  cachedBookmarks.bookmarks.splice(bookmarkIdx, 1);
  await postBookmarks();
}

async function postBookmarks() {
  try {
    await fetch('/api/bookmarks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cachedBookmarks)
    });
    renderBookmarks();
  } catch (e) { console.error('Failed to save bookmarks:', e); }
}


function updateConnectionStatusLine(overrideText) {
  if (!connectionStatusLine) return;
  let text = 'Not connected';
  let color = 'var(--text-secondary)';
  if (overrideText) {
    text = overrideText;
    const lc = overrideText.toLowerCase();
    color = lc.includes('failed') || lc.includes('error') ? 'var(--accent-red)' :
            lc.includes('connect') ? 'var(--accent)' : color;
  } else if (connectionConnected) {
    const label = activeConnectionName || (connectionHost ? `${connectionHost}:${connectionPort || ''}` : 'hardware');
    text = `Connected to ${label}`;
    color = 'var(--accent)';
  } else if (activeConnectionName || connectionHost) {
    const label = activeConnectionName || `${connectionHost || ''}:${connectionPort || ''}`;
    text = `Disconnected from ${label}`;
  }
  connectionStatusLine.textContent = text;
  connectionStatusLine.style.color = color;
  renderConnectionList();
}

function renderConnectionList() {
  if (!connectionListEl) return;
  connectionListEl.innerHTML = '';
  if (!connectionProfiles.length) {
    const empty = document.createElement('div');
    empty.className = 'connection-item';
    empty.textContent = 'No saved connections';
    connectionListEl.appendChild(empty);
    return;
  }
  connectionProfiles.forEach(profile => {
    const item = document.createElement('div');
    item.className = 'connection-item';
    if (profile.id === selectedConnectionId) item.classList.add('selected');
    if (connectionConnected && profile.id === activeConnectionId) item.classList.add('connected');
    const name = document.createElement('div');
    name.className = 'conn-name';
    name.textContent = profile.name || `${profile.host}:${profile.port}`;
    const meta = document.createElement('div');
    meta.className = 'conn-meta';
    const hostSpan = document.createElement('span');
    hostSpan.textContent = `${profile.host || ''}:${profile.port || ''}`;
    const driverSpan = document.createElement('span');
    driverSpan.textContent = profile.driver || 'rtl_tcp';
    meta.appendChild(hostSpan);
    meta.appendChild(driverSpan);
    item.appendChild(name);
    item.appendChild(meta);
    item.onclick = () => selectConnectionProfile(profile.id);
    connectionListEl.appendChild(item);
  });
}

function selectConnectionProfile(id) {
  const profile = connectionProfiles.find(p => p.id === id);
  if (!profile) return;
  selectedConnectionId = profile.id;
  fillConnectionForm(profile);
  renderConnectionList();
}

function fillConnectionForm(profile) {
  if (!profile) return;
  document.getElementById('conn-name').value = profile.name || `${profile.host}:${profile.port}`;
  document.getElementById('conn-host').value = profile.host || '';
  document.getElementById('conn-port').value = profile.port || '';
  document.getElementById('conn-driver').value = profile.driver || 'rtl_tcp';
  document.getElementById('conn-sample-rate').value = profile.sample_rate || 2400000;
}

function clearConnectionForm() {
  document.getElementById('conn-name').value = '';
  document.getElementById('conn-host').value = '';
  document.getElementById('conn-port').value = '';
  document.getElementById('conn-driver').value = 'rtl_tcp';
  document.getElementById('conn-sample-rate').value = 2400000;
}

function updateConnectionFormFromSelection() {
  if (!selectedConnectionId) {
    clearConnectionForm();
    return;
  }
  const profile = connectionProfiles.find(p => p.id === selectedConnectionId);
  if (profile) {
    fillConnectionForm(profile);
  } else {
    clearConnectionForm();
  }
}

async function loadConnectionProfiles() {
  try {
    const res = await fetch('/api/connections');
    if (!res.ok) throw new Error('Failed to load connections');
    const data = await res.json();
    connectionProfiles = Array.isArray(data.connections) ? data.connections : [];
    const serverSelected = data.selected_id;
    if (serverSelected && connectionProfiles.some(p => p.id === serverSelected)) {
      selectedConnectionId = serverSelected;
    } else if (!selectedConnectionId || !connectionProfiles.some(p => p.id === selectedConnectionId)) {
      selectedConnectionId = connectionProfiles[0]?.id || null;
    }
    connectionConnected = Boolean(data.connected);
    activeConnectionId = data.selected_id || activeConnectionId;
    activeConnectionName = data.connection_name || activeConnectionName;
    connectionDriver = data.connection_driver || connectionDriver;
    connectionSampleRate = data.connection_sample_rate || connectionSampleRate;
    connectionHost = data.connection_host || connectionHost;
    connectionPort = data.connection_port || connectionPort;
    updateConnectionStatusLine();
    renderConnectionList();
    updateConnectionFormFromSelection();
    populateHitProfileDropdown();
  } catch (err) {
    console.error('Unable to load connections', err);
    if (connectionStatusLine) {
      connectionStatusLine.textContent = 'Failed to load connections';
      connectionStatusLine.style.color = 'var(--accent-red)';
    }
  }
}

async function persistConnectionProfiles() {
  try {
    const res = await fetch('/api/connections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ connections: connectionProfiles, selected_id: selectedConnectionId }),
    });
    if (!res.ok) throw new Error('Failed to save connections');
    await loadConnectionProfiles();
  } catch (err) {
    console.error('Failed to persist connections', err);
    if (connectionStatusLine) {
      connectionStatusLine.textContent = 'Failed to save connections';
      connectionStatusLine.style.color = 'var(--accent-red)';
    }
    throw err;
  }
}

async function saveConnectionProfile() {
  const hostEl = document.getElementById('conn-host');
  const portEl = document.getElementById('conn-port');
  if (!hostEl || !portEl) return;
  const host = hostEl.value.trim();
  const port = parseInt(portEl.value, 10);
  if (!host || isNaN(port) || port <= 0) {
    if (connectionStatusLine) {
      connectionStatusLine.textContent = 'Enter valid host and port';
      connectionStatusLine.style.color = 'var(--accent-red)';
    }
    return;
  }
  const driver = document.getElementById('conn-driver').value;
  const sampleRate = parseInt(document.getElementById('conn-sample-rate').value, 10) || 2400000;
  const nameInput = document.getElementById('conn-name').value.trim();
  const entry = {
    id: selectedConnectionId || `conn-${Date.now()}`,
    name: nameInput || `${host}:${port}`,
    host,
    port,
    driver,
    sample_rate: sampleRate,
  };
  const idx = connectionProfiles.findIndex(p => p.id === entry.id);
  if (idx >= 0) {
    connectionProfiles[idx] = entry;
  } else {
    connectionProfiles.push(entry);
  }
  selectedConnectionId = entry.id;
  try {
    await persistConnectionProfiles();
  } catch (err) {
    // already reported
  }
}

async function deleteConnectionProfile() {
  if (!selectedConnectionId) {
    if (connectionStatusLine) {
      connectionStatusLine.textContent = 'Select a profile to delete';
      connectionStatusLine.style.color = 'var(--accent-red)';
    }
    return;
  }
  connectionProfiles = connectionProfiles.filter(p => p.id !== selectedConnectionId);
  selectedConnectionId = null;
  try {
    await persistConnectionProfiles();
  } catch (err) {
    // already reported
  }
}


function openConnectionModal() {
  const modal = document.getElementById('connect-modal');
  if (modal) modal.style.display = 'flex';
}

function closeConnectionModal() {
  const modal = document.getElementById('connect-modal');
  if (modal) modal.style.display = 'none';
}

function connectFromForm() {
  const host = document.getElementById('conn-host').value.trim();
  const port = parseInt(document.getElementById('conn-port').value, 10);
  if (!host || isNaN(port) || port <= 0) {
    if (connectionStatusLine) {
      connectionStatusLine.textContent = 'Enter valid host and port';
      connectionStatusLine.style.color = 'var(--accent-red)';
    }
    return;
  }
  const driver = document.getElementById('conn-driver').value;
  const sample_rate = parseInt(document.getElementById('conn-sample-rate').value, 10) || 2400000;
  const name = document.getElementById('conn-name').value.trim() || `${host}:${port}`;
  const profileId = selectedConnectionId || activeConnectionId || `conn-${Date.now()}`;

  const entry = {
    id: profileId,
    name,
    host,
    port,
    driver,
    sample_rate,
  };
  const idx = connectionProfiles.findIndex(p => p.id === profileId);
  if (idx >= 0) connectionProfiles[idx] = entry;
  else connectionProfiles.push(entry);
  selectedConnectionId = profileId;
  persistConnectionProfiles().catch(() => {
    // UI already updated in persistConnectionProfiles on error
  });

  activeConnectionId = profileId;
  activeConnectionName = name;
  connectionHost = host;
  connectionPort = port;
  connectionDriver = driver;
  connectionSampleRate = sample_rate;
  connectionConnected = false;
  updateConnectionStatusLine(`Connecting to ${name}...`);
  sendJSON({ type: 'CONNECT', host, port, driver, sample_rate, name, profile_id: profileId });
}

function toggleHardwareConnection() {
  if (connectionConnected) {
    disconnectHardware();
  } else {
    connectFromForm();
  }
}

function disconnectHardware() {
  sendJSON({ type: 'DISCONNECT' });
  connectionConnected = false;
  updateConnectionStatusLine('Disconnecting...');
}

let isScanning = false;
function toggleScan() {
  if (isScanning) {
    sendJSON({ type: 'STOP_SCAN' });
  } else {
    const cat = document.getElementById('scan-category').value;
    const msg = { type: 'START_SCAN' };
    if (cat) msg.category = cat;
    sendJSON(msg);
  }
}

function startRangeScan() {
  if (isScanning) {
    sendJSON({ type: 'STOP_SCAN' });
    return;
  }
  const startEl = document.getElementById('range-start');
  const endEl = document.getElementById('range-end');
  const stepEl = document.getElementById('range-step');
  const modeEl = document.getElementById('range-mode');
  if (!startEl || !endEl || !stepEl) return;
  const startFreq = Math.round(parseFloat(startEl.value) * 1e6);
  const endFreq = Math.round(parseFloat(endEl.value) * 1e6);
  const step = Math.round(parseFloat(stepEl.value) * 1e3);
  const mode = modeEl ? modeEl.value : currentMode;
  if (isNaN(startFreq) || isNaN(endFreq) || isNaN(step) || step <= 0 || endFreq <= startFreq) {
    alert('Invalid range parameters');
    return;
  }
  sendJSON({ type: 'START_RANGE_SCAN', start: startFreq, end: endFreq, step: step, mode: mode });
}

function updateScanStatus(msg) {
  const btn = document.getElementById('btn-scan');
  const btnRange = document.getElementById('btn-range-scan');
  const info = document.getElementById('scan-info');
  isScanning = msg.state !== 'IDLE';
  if (btn) btn.textContent = isScanning ? 'STOP SCAN' : 'START SCAN';
  if (btnRange) btnRange.textContent = isScanning ? 'STOP' : 'RANGE SCAN';
  if (info) {
    if (isScanning) {
      info.style.display = 'block';
      const modeTag = msg.scan_mode === 'RANGE' ? 'RNG' : 'BKM';
      info.textContent = `[${modeTag}:${msg.state}] ${msg.label || '---'} (${msg.index + 1}/${msg.total}) skip:${msg.skipped}`;
    } else {
      info.style.display = 'none';
      loadScanHits();
    }
  }
}

function populateScanCategories(categories) {
  const sel = document.getElementById('scan-category');
  if (!sel) return;
  const cur = sel.value;
  sel.innerHTML = '<option value="">All Tags</option>';
  (categories || []).forEach(name => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
  sel.value = cur;
}


function scanHitTimeRange() {
  const fromEl = document.getElementById('scan-hit-from');
  const toEl = document.getElementById('scan-hit-to');
  const hoursEl = document.getElementById('scan-hit-hours');
  let sinceTs = null;
  let untilTs = null;
  if (fromEl && fromEl.value) {
    sinceTs = Math.floor(new Date(fromEl.value).getTime() / 1000);
  } else if (hoursEl && hoursEl.value) {
    const hours = Math.max(1, parseInt(hoursEl.value, 10) || 24);
    sinceTs = Math.floor(Date.now() / 1000) - hours * 3600;
  }
  if (toEl && toEl.value) {
    untilTs = Math.floor(new Date(toEl.value).getTime() / 1000);
  }
  return { sinceTs, untilTs };
}

async function loadScanHits() {
  const list = document.getElementById('scan-hit-list');
  if (!list) return;
  const mode = document.getElementById('scan-hit-mode')?.value || '';
  const profileId = (document.getElementById('scan-hit-profile')?.value || '').trim();
  const scanMode = document.getElementById('scan-hit-scan-mode')?.value || '';
  const { sinceTs, untilTs } = scanHitTimeRange();
  const params = new URLSearchParams({ limit: '25' });
  if (sinceTs !== null) params.set('since_ts', String(sinceTs));
  if (untilTs !== null) params.set('until_ts', String(untilTs));
  if (mode) params.set('mode', mode);
  if (profileId) params.set('profile_id', profileId);
  if (scanMode) params.set('scan_mode', scanMode);
  const url = `/api/scan_hits?${params.toString()}`;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('failed to load hits');
    const data = await res.json();
    const hits = Array.isArray(data.hits) ? data.hits : [];
    if (!hits.length) {
      list.innerHTML = '<div class="scan-hit-row"><span>No scan hits yet</span></div>';
      return;
    }
    list.innerHTML = '';
    hits.forEach(h => {
      const row = document.createElement('div');
      row.className = 'scan-hit-row';
      const left = document.createElement('span');
      const freqMhz = ((h.freq || 0) / 1e6).toFixed(3);
      const sigDb = h.signal_db != null ? ` ${h.signal_db.toFixed(0)}dB` : '';
      left.textContent = `${freqMhz} ${h.mode || ''}${sigDb}`.trim();
      const right = document.createElement('span');
      const ts = h.ts ? new Date(h.ts * 1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '';
      const prof = h.profile_id ? `[${h.profile_id}]` : '';
      right.textContent = `${ts} ${h.label || h.scan_mode || '-'} ${prof}`.trim();
      row.appendChild(left);
      row.appendChild(right);
      list.appendChild(row);
    });
  } catch (err) {
    list.innerHTML = '<div class="scan-hit-row"><span>Failed to load hits</span></div>';
  }
}

function scanHitQuery() {
  const mode = document.getElementById('scan-hit-mode')?.value || '';
  const profileId = (document.getElementById('scan-hit-profile')?.value || '').trim();
  const scanMode = document.getElementById('scan-hit-scan-mode')?.value || '';
  const { sinceTs, untilTs } = scanHitTimeRange();
  const params = new URLSearchParams({ limit: '1000' });
  if (sinceTs !== null) params.set('since_ts', String(sinceTs));
  if (untilTs !== null) params.set('until_ts', String(untilTs));
  if (mode) params.set('mode', mode);
  if (profileId) params.set('profile_id', profileId);
  if (scanMode) params.set('scan_mode', scanMode);
  return params;
}

async function exportScanHitsCsv() {
  const params = scanHitQuery();
  const url = `/api/scan_hits/export.csv?${params.toString()}`;
  window.open(url, '_blank');
}

async function exportScanHitsJson() {
  const params = scanHitQuery();
  const url = `/api/scan_hits/export.json?${params.toString()}`;
  window.open(url, '_blank');
}

async function pruneScanHits() {
  await fetch('/api/scan_hits/prune', { method: 'POST' });
  loadScanHits();
}

async function loadAnalytics() {
  const container = document.getElementById('scan-analytics');
  if (!container) return;
  const profileId = (document.getElementById('scan-hit-profile')?.value || '').trim();
  const { sinceTs, untilTs } = scanHitTimeRange();
  const params = new URLSearchParams();
  if (sinceTs !== null) params.set('since_ts', String(sinceTs));
  if (untilTs !== null) params.set('until_ts', String(untilTs));
  if (profileId) params.set('profile_id', profileId);
  const url = `/api/scan_hits/analytics?${params.toString()}`;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('failed to load analytics');
    const data = await res.json();
    renderAnalytics(data);
  } catch (err) {
    container.innerHTML = '<div class="scan-hit-row"><span>Failed to load analytics</span></div>';
  }
}

function populateHitProfileDropdown() {
  const sel = document.getElementById('scan-hit-profile');
  if (!sel || sel.tagName !== 'SELECT') return;
  const cur = sel.value;
  sel.innerHTML = '<option value="">All Profiles</option>';
  connectionProfiles.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name || p.id;
    sel.appendChild(opt);
  });
  if (cur) sel.value = cur;
}

function renderAnalytics(data) {
  const container = document.getElementById('scan-analytics');
  if (!container) return;
  if (!data || !data.total_hits) {
    container.innerHTML = '<div class="scan-hit-row"><span>No data for this range</span></div>';
    return;
  }

  let html = '<div class="analytics-section">';

  // Summary
  html += `<div class="analytics-summary"><b>Total Hits:</b> ${data.total_hits}</div>`;

  // Hit rate
  if (data.hit_rate != null) {
    html += `<div class="analytics-summary"><b>Hit Rate:</b> ${data.hit_rate} hits/hr</div>`;
  }

  // Signal stats
  if (data.signal_stats && data.signal_stats.count_with_signal) {
    const s = data.signal_stats;
    html += `<div class="analytics-summary"><b>Signal:</b> avg ${s.avg_db} dB / min ${s.min_db} / max ${s.max_db}</div>`;
  }

  // Hourly distribution sparkline
  if (data.hourly_distribution && data.hourly_distribution.length > 1) {
    const hd = data.hourly_distribution;
    const maxCnt = Math.max(1, ...hd.map(h => h.count));
    const barW = Math.max(2, Math.floor(200 / hd.length));
    html += '<div class="analytics-subtitle">Activity Timeline</div>';
    html += `<div class="analytics-sparkline">`;
    hd.forEach(h => {
      const pct = Math.round((h.count / maxCnt) * 100);
      html += `<div class="sparkline-bar" style="height:${pct}%;width:${barW}px" title="hour ${h.hour_offset}: ${h.count} hits"></div>`;
    });
    html += '</div>';
  }

  // Top frequencies
  if (data.top_frequencies && data.top_frequencies.length) {
    html += '<div class="analytics-subtitle">Top Frequencies</div><table class="analytics-table"><thead><tr><th>MHz</th><th>Count</th></tr></thead><tbody>';
    data.top_frequencies.forEach(f => {
      html += `<tr><td>${f.freq_mhz}</td><td>${f.count}</td></tr>`;
    });
    html += '</tbody></table>';
  }

  // By mode
  if (data.by_mode && data.by_mode.length) {
    html += '<div class="analytics-subtitle">By Mode</div><table class="analytics-table"><thead><tr><th>Mode</th><th>Count</th></tr></thead><tbody>';
    data.by_mode.forEach(m => {
      html += `<tr><td>${m.mode || '-'}</td><td>${m.count}</td></tr>`;
    });
    html += '</tbody></table>';
  }

  // By profile
  if (data.by_profile && data.by_profile.length) {
    html += '<div class="analytics-subtitle">By Profile</div><table class="analytics-table"><thead><tr><th>Profile</th><th>Count</th></tr></thead><tbody>';
    data.by_profile.forEach(p => {
      html += `<tr><td>${p.profile_id || '-'}</td><td>${p.count}</td></tr>`;
    });
    html += '</tbody></table>';
  }

  html += '</div>';
  container.innerHTML = html;
}

function mergeAdsbAircraft(message) {
  // Unwrap DecoderResult.to_dict() envelope: aircraft data lives in .data
  const ac = message.data && message.icao == null ? message.data : message;
  const key = ac.icao || `${ac.source || 'raw'}:${ac.raw || ''}`;
  if (!key) return;
  const prev = adsbAircraft.get(key) || {};
  adsbAircraft.set(key, { ...prev, ...ac });
  renderAdsbAircraft();
  // Feed single aircraft to map
  const merged = adsbAircraft.get(key);
  if (merged.lat != null && merged.lon != null) {
    updateAircraft([merged]);
  }
}

async function loadAdsbAircraft() {
  const list = document.getElementById('adsb-aircraft-list');
  if (!list) return;
  try {
    const res = await fetch('/api/adsb?limit=100');
    if (!res.ok) throw new Error('failed');
    const data = await res.json();
    const aircraft = Array.isArray(data.aircraft) ? data.aircraft : [];
    adsbAircraft = new Map(aircraft.map(a => [a.icao || `${a.source}:${a.raw || ''}`, a]));
    renderAdsbAircraft();
    updateAircraft(aircraft);
  } catch (err) {
    list.innerHTML = '<div class="scan-hit-row"><span>Failed to load aircraft</span></div>';
  }
}

function renderAdsbAircraft() {
  const list = document.getElementById('adsb-aircraft-list');
  if (!list) return;
  const aircraft = Array.from(adsbAircraft.values()).sort((a, b) => (b.last_seen || 0) - (a.last_seen || 0)).slice(0, 25);
  if (!aircraft.length) {
    list.innerHTML = '<div class="scan-hit-row"><span>No aircraft yet</span></div>';
    return;
  }
  list.innerHTML = '';
  aircraft.forEach(a => {
    const row = document.createElement('div');
    row.className = 'scan-hit-row';
    const left = document.createElement('span');
    const call = (a.callsign || a.icao || 'unknown').trim();
    left.textContent = call;
    const right = document.createElement('span');
    const alt = a.altitude != null ? `${a.altitude}ft` : '-';
    const spd = a.speed != null ? `${a.speed}kt` : '-';
    right.textContent = `${alt} ${spd}`;
    row.appendChild(left);
    row.appendChild(right);
    list.appendChild(row);
  });
}

function appendDecoderLog(msg) {
  const log = document.getElementById('decoder-log');
  const line = document.createElement('div');
  line.textContent = `[${new Date().toLocaleTimeString()}] ${msg.address}: ${msg.content}`;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

function syncDecoderCheckboxes() {
  const pocsagToggle = document.getElementById('chk-pocsag');
  const adsbToggle = document.getElementById('chk-adsb');
  const pocsagEnabled = !!decoderStates.get('pocsag');
  const adsbEnabled = !!decoderStates.get('adsb');
  if (pocsagToggle) pocsagToggle.checked = pocsagEnabled;
  if (adsbToggle) adsbToggle.checked = adsbEnabled;

  const log = document.getElementById('decoder-log');
  if (log) log.style.display = pocsagEnabled ? 'block' : 'none';

  // The aircraft map is ADS-B only; it stays hidden for every other decoder.
  setAdsbMapAvailable(adsbEnabled);
}

function updatePluginStatus(decoderInfo = []) {
  const list = document.getElementById('plugin-list');
  const refresh = document.getElementById('plugin-status-refresh');

  // Sync decoderStates from server info
  for (const info of decoderInfo) {
    if (info.enabled !== undefined) {
      decoderStates.set(info.name, !!info.enabled);
    }
  }

  if (list) {
    list.innerHTML = '';
    if (decoderInfo.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'plugin-empty';
      empty.textContent = 'No decoder plugins found';
      list.appendChild(empty);
      return;
    }
    for (const info of decoderInfo) {
      const row = document.createElement('div');
      row.className = 'plugin-row';
      row.dataset.decoder = info.name;

      // Name + version
      const nameCol = document.createElement('div');
      nameCol.className = 'plugin-name-col';
      const nameSpan = document.createElement('span');
      nameSpan.className = 'plugin-name';
      nameSpan.textContent = info.name;
      nameCol.appendChild(nameSpan);
      if (info.version) {
        const ver = document.createElement('span');
        ver.className = 'plugin-version';
        ver.textContent = 'v' + info.version;
        nameCol.appendChild(ver);
      }
      if (info.description) {
        const desc = document.createElement('div');
        desc.className = 'plugin-desc';
        desc.textContent = info.description;
        nameCol.appendChild(desc);
      }
      row.appendChild(nameCol);

      // State badge
      const stateCol = document.createElement('div');
      stateCol.className = 'plugin-state-col';
      const badge = document.createElement('span');
      const state = info.state || 'idle';
      badge.className = 'plugin-badge plugin-badge-' + state;
      badge.textContent = state;
      stateCol.appendChild(badge);
      if (info.note) {
        const note = document.createElement('div');
        note.className = 'plugin-note';
        note.textContent = info.note;
        stateCol.appendChild(note);
      }
      row.appendChild(stateCol);

      // Toggle
      const toggleCol = document.createElement('div');
      toggleCol.className = 'plugin-toggle-col';
      const toggle = document.createElement('label');
      toggle.className = 'plugin-toggle';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !!decoderStates.get(info.name);
      cb.addEventListener('change', (e) => {
        sendJSON({ type: 'TOGGLE_DECODER', name: info.name, value: e.target.checked });
        decoderStates.set(info.name, e.target.checked);
      });
      toggle.appendChild(cb);
      const slider = document.createElement('span');
      slider.className = 'plugin-toggle-slider';
      toggle.appendChild(slider);
      toggleCol.appendChild(toggle);
      row.appendChild(toggleCol);

      list.appendChild(row);
    }
  }

  if (refresh) refresh.textContent = new Date().toLocaleTimeString();
}

function updateDecoderHealthBadge(status) {
  // Find the plugin row by data attribute and update its badge + error note
  const row = document.querySelector(`.plugin-row[data-decoder="${status.name}"]`);
  if (!row) return;
  const badge = row.querySelector('.plugin-badge');
  if (badge) {
    badge.className = 'plugin-badge plugin-badge-' + (status.state || 'idle');
    badge.textContent = status.state || 'idle';
  }
  if (status.error) {
    let note = row.querySelector('.plugin-error');
    if (!note) {
      note = document.createElement('div');
      note.className = 'plugin-error';
      row.querySelector('.plugin-state-col').appendChild(note);
    }
    note.textContent = status.error;
  }
}

/* ── Settings Modal ── */
function wireSettings() {
  const btn = document.getElementById('btn-settings');
  const modal = document.getElementById('settings-modal');
  const closeBtn = document.getElementById('btn-close-settings');
  if (!btn || !modal) return;

  btn.addEventListener('click', () => { modal.style.display = 'flex'; });
  closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
  modal.addEventListener('click', (e) => { if (e.target === modal) modal.style.display = 'none'; });

  // Tab switching
  modal.querySelectorAll('.settings-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      modal.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
      modal.querySelectorAll('.settings-pane').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      modal.querySelector(`.settings-pane[data-pane="${tab.dataset.tab}"]`).classList.add('active');
    });
  });

  // Reset button
  const resetBtn = document.getElementById('btn-reset-settings');
  if (resetBtn) resetBtn.addEventListener('click', () => { if (confirm('Reset all settings to defaults?')) location.reload(); });

  const refreshPluginsBtn = document.getElementById('btn-refresh-plugins');
  if (refreshPluginsBtn) {
    refreshPluginsBtn.addEventListener('click', () => {
      sendJSON({ type: 'LIST_DECODERS' });
    });
  }

  const reloadPluginsBtn = document.getElementById('btn-reload-plugins');
  if (reloadPluginsBtn) {
    reloadPluginsBtn.addEventListener('click', () => {
      sendJSON({ type: 'RELOAD_DECODERS' });
    });
  }
}
wireSettings();
