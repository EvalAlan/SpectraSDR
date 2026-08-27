/**
 * SpectraSDR aircraft map — Leaflet-based display with live ADS-B positions.
 */

let map = null;
let aircraftLayer = null;
let aircraftMarkers = new Map(); // icao -> { marker, data }
let mapInitialized = false;

// The window is shown only while the ADS-B decoder is on, and only if the user
// hasn't dismissed it. Closing hides the window but leaves the decoder running.
let adsbMapEnabled = false;
let mapClosedByUser = false;

const EMERGENCY_SQUAWKS = new Set(["7500", "7600", "7700"]);
const MAP_WINDOW_KEY = "spectrasdr.mapWindow";

function initMap() {
  if (mapInitialized) return;
  mapInitialized = true;

  // Wire the window chrome first: Leaflet is loaded from a CDN, so if it is
  // unreachable the user must still be able to move and close the window.
  initMapWindow();

  if (typeof L === "undefined") {
    console.error("Leaflet failed to load; the aircraft map cannot render.");
    return;
  }

  map = L.map("map-container", {
    center: [42.5, -78.5], // default: WNY
    zoom: 7,
    zoomControl: true,
    attributionControl: true,
  });

  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);

  aircraftLayer = L.layerGroup().addTo(map);

  document.getElementById("btn-center-map").onclick = centerOnAircraft;
}

function clamp(v, lo, hi) {
  return Math.min(Math.max(v, lo), hi);
}

function initMapWindow() {
  const panel = document.getElementById("map-panel");
  const header = document.getElementById("map-header");
  const closeBtn = document.getElementById("btn-close-map");
  const showBtn = document.getElementById("btn-show-map");
  if (!panel || !header) return;

  restoreMapWindow(panel);

  header.addEventListener("mousedown", (e) => {
    if (e.target.closest("button")) return; // let header buttons work
    e.preventDefault();
    const rect = panel.getBoundingClientRect();
    const grabX = e.clientX - rect.left;
    const grabY = e.clientY - rect.top;

    const onMove = (ev) => {
      // Keep the window on screen so the header can always be grabbed again.
      const maxLeft = Math.max(0, window.innerWidth - panel.offsetWidth);
      const maxTop = Math.max(0, window.innerHeight - panel.offsetHeight);
      panel.style.left = clamp(ev.clientX - grabX, 0, maxLeft) + "px";
      panel.style.top = clamp(ev.clientY - grabY, 0, maxTop) + "px";
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      saveMapWindow(panel);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });

  if (closeBtn) closeBtn.onclick = () => { mapClosedByUser = true; refreshMapVisibility(); };
  if (showBtn) showBtn.onclick = reopenAdsbMap;

  // Leaflet caches the container size, so it renders blank or clipped after the
  // window is resized or re-shown. Re-measure whenever the box changes.
  if (window.ResizeObserver) {
    new ResizeObserver(() => {
      if (map) map.invalidateSize();
      saveMapWindow(panel);
    }).observe(panel);
  }
}

/** Called whenever the ADS-B decoder state changes, and on reopen/close. */
function setAdsbMapAvailable(adsbEnabled) {
  adsbMapEnabled = !!adsbEnabled;
  refreshMapVisibility();
}

/** Turning ADS-B on is an explicit request for it, so undo an earlier dismiss. */
function reopenAdsbMap() {
  mapClosedByUser = false;
  refreshMapVisibility();
}

function refreshMapVisibility() {
  const panel = document.getElementById("map-panel");
  const showBtn = document.getElementById("btn-show-map");
  if (!panel) return;

  const visible = adsbMapEnabled && !mapClosedByUser;
  panel.style.display = visible ? "flex" : "none";
  if (showBtn) showBtn.style.display = adsbMapEnabled && mapClosedByUser ? "" : "none";

  // The container had no size while hidden; let layout settle, then re-measure.
  if (visible && map) setTimeout(() => map.invalidateSize(), 0);
}

function saveMapWindow(panel) {
  try {
    localStorage.setItem(MAP_WINDOW_KEY, JSON.stringify({
      left: panel.style.left,
      top: panel.style.top,
      width: panel.style.width,
      height: panel.style.height,
    }));
  } catch (_) { /* storage unavailable; position just won't persist */ }
}

function restoreMapWindow(panel) {
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(MAP_WINDOW_KEY) || "null");
  } catch (_) {
    return;
  }
  if (!saved) return;

  if (saved.width) panel.style.width = saved.width;
  if (saved.height) panel.style.height = saved.height;

  // A window saved on a larger display must not restore off-screen.
  const w = parseInt(saved.width, 10) || panel.offsetWidth;
  const h = parseInt(saved.height, 10) || panel.offsetHeight;
  if (saved.left) {
    panel.style.left = clamp(parseInt(saved.left, 10) || 0, 0, Math.max(0, window.innerWidth - w)) + "px";
  }
  if (saved.top) {
    panel.style.top = clamp(parseInt(saved.top, 10) || 0, 0, Math.max(0, window.innerHeight - h)) + "px";
  }
}

function centerOnAircraft() {
  if (!map || aircraftMarkers.size === 0) return;
  const bounds = [];
  for (const { data } of aircraftMarkers.values()) {
    if (data.lat != null && data.lon != null) {
      bounds.push([data.lat, data.lon]);
    }
  }
  if (bounds.length > 0) {
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 10 });
  }
}

function getAircraftIcon(aircraft) {
  const isEmergency = EMERGENCY_SQUAWKS.has(aircraft.squawk);
  const heading = aircraft.track != null ? aircraft.track : 0;
  const color = isEmergency ? "#ff3366" : "#00ff88";

  // Use a triangle/plane SVG rotated by heading
  const svg = `<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="transform: rotate(${heading}deg);">
    <path d="M12 2 L20 20 L12 16 L4 20 Z" fill="${color}" stroke="#000" stroke-width="0.5" opacity="0.9"/>
  </svg>`;

  return L.divIcon({
    className: "aircraft-marker" + (isEmergency ? " emergency" : ""),
    html: `<div class="aircraft-icon${isEmergency ? " emergency" : ""}">${svg}</div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

function getAircraftLabel(aircraft) {
  const isEmergency = EMERGENCY_SQUAWKS.has(aircraft.squawk);
  const call = aircraft.callsign || aircraft.icao || "?";
  const alt = aircraft.altitude != null ? `${formatAlt(aircraft.altitude)}` : "";
  const spd = aircraft.speed != null ? `${aircraft.speed}kt` : "";
  const text = [call, alt, spd].filter(Boolean).join(" ");

  return `<div class="aircraft-label${isEmergency ? " emergency" : ""}">${text}</div>`;
}

function formatAlt(ft) {
  if (ft >= 10000) return `${(ft / 1000).toFixed(1)}k`;
  return `${ft}`;
}

function buildPopup(aircraft) {
  const isEmergency = EMERGENCY_SQUAWKS.has(aircraft.squawk);
  const call = aircraft.callsign || aircraft.icao || "unknown";
  const icao = aircraft.icao || "—";
  const alt = aircraft.altitude != null ? `${aircraft.altitude} ft` : "—";
  const spd = aircraft.speed != null ? `${aircraft.speed} kt` : "—";
  const track = aircraft.track != null ? `${Math.round(aircraft.track)}°` : "—";
  const squawk = aircraft.squawk || "—";
  const src = aircraft.source || "—";
  const lastSeen = aircraft.last_seen
    ? `${Math.round((Date.now() / 1000) - aircraft.last_seen)}s ago`
    : "—";

  let html = `<div class="aircraft-popup">`;
  html += `<div class="cs${isEmergency ? " emergency" : ""}">${call} ${isEmergency ? "⚠ EMERGENCY" : ""}</div>`;
  html += `<div>ICAO: <b>${icao}</b></div>`;
  html += `<div>Alt: <b>${alt}</b>  Spd: <b>${spd}</b></div>`;
  html += `<div>Track: <b>${track}</b>  Squawk: <b class="${isEmergency ? "emergency" : ""}">${squawk}</b></div>`;
  html += `<div>Source: ${src}  Seen: ${lastSeen}</div>`;
  html += `</div>`;
  return html;
}

function updateAircraft(aircraftList) {
  if (!map || !aircraftLayer) return;

  const seenIcaos = new Set();
  const now = Date.now() / 1000;

  for (const ac of aircraftList) {
    if (!ac.icao) continue;
    if (ac.lat == null || ac.lon == null) continue; // skip without position
    if (now - (ac.last_seen || 0) > 300) continue; // skip stale (>5min)

    seenIcaos.add(ac.icao);
    const existing = aircraftMarkers.get(ac.icao);

    if (existing) {
      existing.data = ac;
      existing.marker.setLatLng([ac.lat, ac.lon]);
      existing.marker.setIcon(getAircraftIcon(ac));
      existing.marker.setPopupContent(buildPopup(ac));
    } else {
      const marker = L.marker([ac.lat, ac.lon], {
        icon: getAircraftIcon(ac),
      });
      marker.bindPopup(buildPopup(ac));
      aircraftLayer.addLayer(marker);
      aircraftMarkers.set(ac.icao, { marker, data: ac });
    }
  }

  // Remove markers for aircraft no longer present
  for (const [icao, { marker }] of aircraftMarkers) {
    if (!seenIcaos.has(icao)) {
      aircraftLayer.removeLayer(marker);
      aircraftMarkers.delete(icao);
    }
  }

  // Update count
  const countEl = document.getElementById("map-aircraft-count");
  if (countEl) countEl.textContent = String(aircraftMarkers.size);
}

function removeStaleMarkers() {
  if (!aircraftLayer) return;
  const now = Date.now() / 1000;
  for (const [icao, { marker, data }] of aircraftMarkers) {
    if (now - (data.last_seen || 0) > 600) {
      aircraftLayer.removeLayer(marker);
      aircraftMarkers.delete(icao);
    }
  }
  const countEl = document.getElementById("map-aircraft-count");
  if (countEl) countEl.textContent = String(aircraftMarkers.size);
}
