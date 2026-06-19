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

// The Deimos canon: black, blood, ember, divine gold. Each state stays inside it.
const COLORS = {
  idle:      [255, 48, 52],   // banked crimson coal
  listening: [255, 40, 80],   // roused blood-rose
  thinking:  [231, 178, 74],  // oracular gold
  speaking:  [255, 122, 52],  // ember orange
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

const N = 96;
const particles = Array.from({ length: N }, () => ({
  a: Math.random() * Math.PI * 2,
  rf: 0.9 + Math.random() * 0.52,
  spd: (0.15 + Math.random() * 0.5) * (Math.random() < 0.5 ? 1 : -1),
  size: 0.8 + Math.random() * 1.9,
  ph: Math.random() * Math.PI * 2,
}));

// A tighter, counter-rotating inner ring adds depth and motion.
const N2 = 52;
const innerParticles = Array.from({ length: N2 }, () => ({
  a: Math.random() * Math.PI * 2,
  rf: 0.48 + Math.random() * 0.3,
  spd: -(0.25 + Math.random() * 0.6),
  size: 0.6 + Math.random() * 1.3,
  ph: Math.random() * Math.PI * 2,
}));

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
  const c = COLORS[state] || COLORS.idle;

  const breathe = 1 + Math.sin(t * 1.4) * 0.045;
  let react = 0;
  if (state === "listening") react = level * 0.65;
  else if (state === "speaking") react = (0.5 + 0.5 * Math.abs(Math.sin(t * 7))) * 0.34;
  else if (state === "thinking") react = 0.06 + 0.06 * Math.sin(t * 4);
  const coreR = baseR * (breathe + react);

  // 1. Forge aura — a vast soft halo that breathes and flares with the orb.
  const aura = ctx.createRadialGradient(cx, cy, coreR * 0.3, cx, cy, SIZE * 0.52);
  aura.addColorStop(0, rgba(c, 0.18 + react * 0.2));
  aura.addColorStop(0.42, rgba(c, 0.05 + react * 0.06));
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

  // 4. Orbiting embers — outer field and counter-rotating inner field.
  const spinBase = state === "thinking" ? 2.2 : state === "listening" ? 1.0 : 0.5;
  ctx.save();
  ctx.shadowBlur = 9;
  ctx.shadowColor = rgba(c, 0.9);
  for (const p of particles) {
    const ang = p.a + t * p.spd * spinBase;
    const rr = ringR * p.rf * (1 + react * 0.7);
    const x = cx + Math.cos(ang) * rr;
    const y = cy + Math.sin(ang) * rr;
    const tw = 0.4 + 0.6 * Math.abs(Math.sin(t * 1.5 + p.ph));
    ctx.beginPath();
    ctx.arc(x, y, p.size, 0, Math.PI * 2);
    ctx.fillStyle = rgba(c, tw * (0.5 + react));
    ctx.fill();
  }
  for (const p of innerParticles) {
    const ang = p.a + t * p.spd * spinBase;
    const rr = ringR * p.rf * (1 + react * 0.5);
    const x = cx + Math.cos(ang) * rr;
    const y = cy + Math.sin(ang) * rr;
    const tw = 0.4 + 0.6 * Math.abs(Math.sin(t * 2.1 + p.ph));
    ctx.beginPath();
    ctx.arc(x, y, p.size, 0, Math.PI * 2);
    ctx.fillStyle = rgba(hot(c, 0.25), tw * (0.4 + react));
    ctx.fill();
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

  // 7. Incandescent core — white-hot heart fading through the state hue.
  ctx.save();
  ctx.shadowBlur = 64 + react * 80;
  ctx.shadowColor = rgba(c, 0.85);
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
  g.addColorStop(0, "rgba(255,251,246,0.98)");
  g.addColorStop(0.34, rgba(hot(c, 0.5), 0.96));
  g.addColorStop(0.7, rgba(c, 0.9));
  g.addColorStop(1, rgba(c, 0));
  ctx.beginPath();
  ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
  ctx.fillStyle = g;
  ctx.fill();
  ctx.restore();

  // 8. Bright iris rim — the cold, deliberate ring of HAL's stare.
  ctx.save();
  ctx.lineWidth = 1.4;
  ctx.shadowBlur = 16;
  ctx.shadowColor = rgba(hot(c, 0.4), 0.9);
  ctx.beginPath();
  ctx.arc(cx, cy, coreR * 1.16, 0, Math.PI * 2);
  ctx.strokeStyle = rgba(hot(c, 0.35), 0.5 + react * 0.4);
  ctx.stroke();
  ctx.restore();

  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

let ws;
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
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
  statusEl.textContent = s;
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
