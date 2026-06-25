const canvas = document.getElementById("orb");
const ctx = canvas.getContext("2d");
const stage = document.getElementById("stage");
const statusEl = document.getElementById("status");
const progressEl = document.getElementById("progress");
const saidEl = document.getElementById("said");
const replyEl = document.getElementById("reply");
const hintEl = document.getElementById("hint");

let state = "idle";
let level = 0;
let target = 0;
let fadeTimer = null;

// Eased visual quantities so state changes glide instead of snapping.
let spin = 0.6;          // current rotation speed, eased toward spinTarget
let spinAngle = 0;       // accumulated rotation, so eased speed never jumps angle
let lastNow = performance.now();
let renderC = [210, 22, 40]; // currently-rendered color, eased toward COLORS[state]

// Idle "blink" — a rare, quick dim, so the eye reads as alive and watching.
let nextBlink = 2.4 + Math.random() * 5;
let blinkStart = -1;

// The Deimos canon: black and blood, with a single ember warmth. Red-forward.
const COLORS = {
  idle:      [210, 22, 40],   // banked crimson coal
  listening: [255, 35, 62],   // roused blood-rose
  thinking:  [244, 66, 40],   // oracular ember, redder
  speaking:  [255, 52, 40],   // forge-fire red
};

const DPR = Math.min(window.devicePixelRatio || 1, 2);
const SIZE = 480;
const cx = SIZE / 2, cy = SIZE / 2;
const baseR = 50, ringR = 130;

function setupCanvas() {
  canvas.width = SIZE * DPR;
  canvas.height = SIZE * DPR;
  ctx.scale(DPR, DPR);
}
setupCanvas();

// Sleek reticle arcs — thin broken rings that turn slowly around the eye,
// replacing the scattered ember cloud with deliberate, watching geometry.
const arcs = [
  { rf: 1.00, w: 1.6, spd:  0.16, span: 1.55, off: 0.0,            hot: 0.30 },
  { rf: 1.00, w: 1.6, spd:  0.16, span: 1.55, off: Math.PI,        hot: 0.30 },
  { rf: 1.28, w: 1.1, spd: -0.11, span: 0.95, off: 0.9,            hot: 0.45 },
  { rf: 1.28, w: 1.1, spd: -0.11, span: 0.95, off: 0.9 + Math.PI,  hot: 0.45 },
  { rf: 1.56, w: 0.8, spd:  0.07, span: 0.55, off: 2.1,            hot: 0.55 },
];

// Expanding rings emitted while speaking, like a voice waveform.
let ripples = [];
let lastRipple = 0;

function rgba(c, a) { return `rgba(${c[0]},${c[1]},${c[2]},${a})`; }
// Pull a color toward white by `amt` (0..1) for incandescent highlights.
function hot(c, amt) {
  return [
    Math.round(c[0] + (255 - c[0]) * amt),
    Math.round(c[1] + (255 - c[1]) * amt),
    Math.round(c[2] + (255 - c[2]) * amt),
  ];
}

const t0 = performance.now();
function frame(now) {
  const t = (now - t0) / 1000;
  level += (target - level) * 0.15;
  ctx.clearRect(0, 0, SIZE, SIZE);

  // Ease the rendered color toward the target state's hue so transitions glide.
  const tc = COLORS[state] || COLORS.idle;
  for (let i = 0; i < 3; i++) renderC[i] += (tc[i] - renderC[i]) * 0.08;
  const c = renderC;

  const breathe = 1 + Math.sin(t * 1.4) * 0.045;
  let react = 0;
  if (state === "listening") react = level * 0.65;
  else if (state === "speaking") react = (0.5 + 0.5 * Math.abs(Math.sin(t * 7))) * 0.34;
  else if (state === "thinking") react = 0.06 + 0.06 * Math.sin(t * 4);

  // Idle blink: schedule rare quick dims; blinkEnv is 0 (open) .. 1 (shut).
  let blinkEnv = 0;
  if (state === "idle") {
    if (blinkStart < 0 && t >= nextBlink) blinkStart = t;
    if (blinkStart >= 0) {
      const bp = (t - blinkStart) / 0.34; // ~340ms blink
      if (bp >= 1) { blinkStart = -1; nextBlink = t + 4 + Math.random() * 7; }
      else blinkEnv = Math.sin(bp * Math.PI); // smooth dim-and-recover
    }
  } else { blinkStart = -1; nextBlink = t + 4 + Math.random() * 7; }

  const coreR = baseR * (breathe + react) * (1 - blinkEnv * 0.5);
  const lum = 1 - blinkEnv * 0.78; // overall brightness during a blink

  // 1. Forge aura — a vast soft halo that breathes and flares with the orb.
  const aura = ctx.createRadialGradient(cx, cy, coreR * 0.3, cx, cy, SIZE * 0.52);
  aura.addColorStop(0, rgba(c, (0.18 + react * 0.2) * lum));
  aura.addColorStop(0.42, rgba(c, (0.05 + react * 0.06) * lum));
  aura.addColorStop(1, rgba(c, 0));
  ctx.fillStyle = aura;
  ctx.fillRect(0, 0, SIZE, SIZE);

  // 2. Concentric iris rings — the recessed socket of the eye.
  ctx.save();
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i++) {
    const rr = coreR * (2.0 + i * 0.95) * (1 + react * 0.22);
    ctx.beginPath();
    ctx.arc(cx, cy, rr, 0, Math.PI * 2);
    ctx.strokeStyle = rgba(c, 0.05 + i * 0.02);
    ctx.stroke();
  }
  ctx.restore();

  // 3. Thinking sweep — an oracular scanner tracing the rim.
  if (state === "thinking") {
    const sweep = t * 2.4;
    ctx.save();
    ctx.lineWidth = 2;
    ctx.shadowBlur = 14;
    ctx.shadowColor = rgba(c, 0.85);
    ctx.beginPath();
    ctx.arc(cx, cy, ringR * 1.12, sweep, sweep + 1.1);
    ctx.strokeStyle = rgba(c, 0.55);
    ctx.stroke();
    ctx.restore();
  }

  // 4. Reticle arcs — deliberate broken rings rotating around the eye.
  // Ease the spin speed toward its target so the rings spool up/down smoothly.
  const spinTarget = state === "thinking" ? 2.0 : state === "speaking" ? 1.35
             : state === "listening" ? 1.0 : 0.6;
  spin += (spinTarget - spin) * 0.04;
  spinAngle += (now - lastNow) / 1000 * spin; // accumulate so eased speed never jumps angle
  ctx.save();
  ctx.lineCap = "round";
  ctx.shadowBlur = 10;
  ctx.shadowColor = rgba(c, 0.8);
  for (const arc of arcs) {
    const rr = ringR * arc.rf * (1 + react * 0.18);
    const start = arc.off + spinAngle * arc.spd;
    ctx.beginPath();
    ctx.arc(cx, cy, rr, start, start + arc.span);
    ctx.lineWidth = arc.w;
    ctx.strokeStyle = rgba(hot(c, arc.hot * 0.4), (0.2 + react * 0.45) * lum);
    ctx.stroke();
  }
  ctx.restore();

  // 5. Speaking emits expanding echo rings; they fade as they travel.
  if (state === "speaking" && now - lastRipple > 360) {
    ripples.push({ born: t });
    lastRipple = now;
  }
  ctx.save();
  ctx.lineWidth = 1.5;
  ripples = ripples.filter((rp) => t - rp.born < 1.8);
  for (const rp of ripples) {
    const age = t - rp.born;
    const rr = coreR * 1.4 + age * 138;
    ctx.beginPath();
    ctx.arc(cx, cy, rr, 0, Math.PI * 2);
    ctx.strokeStyle = rgba(c, Math.max(0, 0.34 * (1 - age / 1.8)));
    ctx.stroke();
  }
  ctx.restore();

  // 6. Dark iris well so the molten core reads as a recessed, watching eye.
  ctx.save();
  const well = ctx.createRadialGradient(cx, cy, coreR * 0.95, cx, cy, coreR * 2.7);
  well.addColorStop(0, "rgba(6,1,3,0)");
  well.addColorStop(0.45, "rgba(6,1,3,0.5)");
  well.addColorStop(1, "rgba(6,1,3,0)");
  ctx.beginPath();
  ctx.arc(cx, cy, coreR * 2.7, 0, Math.PI * 2);
  ctx.fillStyle = well;
  ctx.fill();
  ctx.restore();

  // 7. Incandescent core — molten heart fading through the state hue.
  ctx.save();
  ctx.shadowBlur = (64 + react * 84) * lum;
  ctx.shadowColor = rgba(c, 0.9 * lum);
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
  g.addColorStop(0, rgba([255, 247, 242], 0.98 * lum));
  g.addColorStop(0.28, rgba(hot(c, 0.55), 0.97 * lum));
  g.addColorStop(0.62, rgba(c, 0.92 * lum));
  g.addColorStop(1, rgba(c, 0));
  ctx.beginPath();
  ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
  ctx.fillStyle = g;
  ctx.fill();
  ctx.restore();

  // 7a. Iris striations — faint radial fibers give the core real iris texture.
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, coreR * 0.98, 0, Math.PI * 2);
  ctx.clip();
  ctx.lineWidth = 0.8;
  const fibers = 40;
  const drift = spinAngle * 0.05;
  for (let i = 0; i < fibers; i++) {
    const a = (i / fibers) * Math.PI * 2 + drift;
    const wob = 0.85 + 0.15 * Math.sin(i * 1.7 + t * 0.6);
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(a) * coreR * 0.30, cy + Math.sin(a) * coreR * 0.30);
    ctx.lineTo(cx + Math.cos(a) * coreR * wob, cy + Math.sin(a) * coreR * wob);
    ctx.strokeStyle = rgba(hot(c, 0.4), (i % 2 ? 0.05 : 0.09) * lum);
    ctx.stroke();
  }
  ctx.restore();

  // 7b. Dark pupil — a watching void at the heart, with a single hot catch-light.
  const pupilR = coreR * (0.34 - react * 0.12);
  ctx.save();
  const pupil = ctx.createRadialGradient(cx, cy, 0, cx, cy, pupilR);
  pupil.addColorStop(0, "rgba(8,1,3,0.96)");
  pupil.addColorStop(0.72, "rgba(20,2,6,0.82)");
  pupil.addColorStop(1, rgba(c, 0));
  ctx.beginPath();
  ctx.arc(cx, cy, pupilR, 0, Math.PI * 2);
  ctx.fillStyle = pupil;
  ctx.fill();
  ctx.beginPath();
  ctx.arc(cx - pupilR * 0.32, cy - pupilR * 0.34, pupilR * 0.28, 0, Math.PI * 2);
  ctx.fillStyle = rgba(hot(c, 0.7), (0.5 + react * 0.4) * lum);
  ctx.fill();
  ctx.restore();

  // 8. Bright iris rim — the cold, deliberate ring of HAL's stare.
  ctx.save();
  ctx.lineWidth = 1.4;
  ctx.shadowBlur = 16;
  ctx.shadowColor = rgba(hot(c, 0.4), 0.9);
  ctx.beginPath();
  ctx.arc(cx, cy, coreR * 1.16, 0, Math.PI * 2);
  ctx.strokeStyle = rgba(hot(c, 0.35), (0.5 + react * 0.4) * lum);
  ctx.stroke();
  ctx.restore();

  lastNow = now;
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

let ws;
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  // On every (re)connect, force the UI back to a clickable idle state so a
  // server restart or dropped socket can never leave the orb wedged.
  ws.onopen = () => setState("idle");
  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.type === "state") setState(d.state);
    else if (d.type === "transcript") caption(d.role, d.text);
    else if (d.type === "progress") showProgress(d);
  };
  ws.onclose = () => { statusEl.textContent = "reconnecting"; setTimeout(connect, 1200); };
}

function setState(s) {
  state = s;
  if (statusEl.textContent !== s) {
    statusEl.textContent = s;
    statusEl.classList.remove("flip");
    void statusEl.offsetWidth; // restart the crossfade animation
    statusEl.classList.add("flip");
  }
  document.body.className = s;
  hintEl.classList.toggle("dim", s !== "idle");
  if (s === "listening") startMic();
  else stopMic();
  // Progress only makes sense while thinking/working; clear it otherwise.
  if (s === "idle" || s === "speaking") clearProgress();
  if (s === "idle") scheduleFade();
}

function fmtTime(sec) {
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function showProgress(d) {
  let label = `${(d.phase || "Thinking").toUpperCase()} · ${fmtTime(d.elapsed || 0)}`;
  if (d.estimate) label += ` · est ~${Math.max(1, Math.round(d.estimate / 60))}m`;
  progressEl.textContent = label;
  progressEl.classList.add("show");
}

function clearProgress() {
  progressEl.classList.remove("show");
  progressEl.textContent = "";
}

function caption(role, text) {
  if (!text) return;
  clearTimeout(fadeTimer);
  if (role === "you") {
    saidEl.textContent = text;
    saidEl.classList.add("show");
  } else {
    replyEl.textContent = text;
    replyEl.classList.add("show");
  }
}

function scheduleFade() {
  clearTimeout(fadeTimer);
  fadeTimer = setTimeout(() => {
    saidEl.classList.remove("show");
    replyEl.classList.remove("show");
  }, 9000);
}

function trigger() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (state === "idle") {
    ws.send(JSON.stringify({ action: "listen" }));
  } else if (state === "listening") {
    pause();
  }
}

function pause() {
  if (ws && ws.readyState === WebSocket.OPEN && state === "listening") {
    ws.send(JSON.stringify({ action: "pause" }));
  }
}
stage.addEventListener("click", trigger);
document.addEventListener("keydown", (e) => {
  if (e.code === "Space") { e.preventDefault(); trigger(); }
});

let micStream, audioCtx, analyser, micData;
async function startMic() {
  if (analyser) return;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = audioCtx.createMediaStreamSource(micStream);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    micData = new Uint8Array(analyser.fftSize);
    src.connect(analyser);
    pollMic();
  } catch (err) {
    target = 0;
  }
}
function pollMic() {
  if (!analyser) return;
  analyser.getByteTimeDomainData(micData);
  let sum = 0;
  for (let i = 0; i < micData.length; i++) {
    const v = (micData[i] - 128) / 128;
    sum += v * v;
  }
  target = Math.min(1, Math.sqrt(sum / micData.length) * 4);
  requestAnimationFrame(pollMic);
}
function stopMic() {
  target = 0;
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (audioCtx) audioCtx.close();
  micStream = audioCtx = analyser = null;
}

connect();

// --- HUD side rails: live clock, weather, markets ---------------------------
const clockEl = document.getElementById("clock");
const clockDateEl = document.getElementById("clock-date");
function tickClock() {
  const now = new Date();
  if (clockEl) {
    clockEl.textContent = now.toLocaleTimeString([], {
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
  }
  if (clockDateEl) {
    clockDateEl.textContent = now.toLocaleDateString([], {
      weekday: "short", day: "numeric", month: "short",
    });
  }
}
tickClock();
setInterval(tickClock, 1000);

async function refreshWeather() {
  try {
    const d = await (await fetch("/api/weather")).json();
    const t = document.getElementById("wx-temp");
    const c = document.getElementById("wx-cond");
    const l = document.getElementById("wx-loc");
    if (t) t.textContent = d.temp || "—";
    if (c) c.textContent = d.condition || "—";
    if (l) l.textContent = d.location || "";
  } catch (_) {/* leave placeholders */}
}

function fmtPrice(p) {
  if (p == null) return "—";
  return p >= 1000 ? p.toLocaleString(undefined, { maximumFractionDigits: 0 })
                   : p.toFixed(2);
}
async function refreshStocks() {
  try {
    const d = await (await fetch("/api/stocks")).json();
    const box = document.getElementById("stocks");
    if (!box) return;
    box.innerHTML = "";
    (d.stocks || []).forEach((s) => {
      const row = document.createElement("div");
      row.className = "stock-row";
      const chg = s.change == null ? "" :
        `${s.change >= 0 ? "+" : ""}${s.change.toFixed(1)}%`;
      const cls = s.change == null ? "" : s.change >= 0 ? "stock-up" : "stock-down";
      row.innerHTML =
        `<span class="stock-sym">${s.symbol}</span>` +
        `<span class="stock-val ${cls}">${fmtPrice(s.price)} ${chg}</span>`;
      box.appendChild(row);
    });
  } catch (_) {/* leave placeholder */}
}

refreshWeather(); setInterval(refreshWeather, 10 * 60 * 1000); // every 10 min
refreshStocks(); setInterval(refreshStocks, 60 * 1000);        // every minute

// --- Desktop app: collapse back to the floating mini-orb widget ---
(async function () {
  const T = window.__TAURI__;
  const btn = document.getElementById("collapse");
  if (!T || !T.window) return; // only inside the Tauri app
  const { getCurrentWindow, LogicalSize, LogicalPosition } = T.window;
  const w = getCurrentWindow();

  async function collapse() {
    try {
      await w.setAlwaysOnTop(true);
      await w.setDecorations(false);
      await w.setSize(new LogicalSize(168, 168));
      await w.setPosition(new LogicalPosition(24, 44)); // top-left
    } catch (e) {}
    location.href = "http://localhost:8765/mini";
  }

  if (btn) {
    btn.hidden = false;
    btn.addEventListener("click", collapse);
  }
  // Closing the expanded window returns to the floating orb instead of
  // quitting the app (it's the only window).
  try {
    await w.onCloseRequested((event) => { event.preventDefault(); collapse(); });
  } catch (e) {}
})();
