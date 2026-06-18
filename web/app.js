const canvas = document.getElementById("orb");
const ctx = canvas.getContext("2d");
const stage = document.getElementById("stage");
const statusEl = document.getElementById("status");
const saidEl = document.getElementById("said");
const replyEl = document.getElementById("reply");
const hintEl = document.getElementById("hint");

let state = "idle";
let level = 0;
let target = 0;
let fadeTimer = null;

const COLORS = {
  idle:      [95, 208, 230],
  listening: [31, 227, 255],
  thinking:  [138, 108, 255],
  speaking:  [255, 180, 58],
};

const DPR = Math.min(window.devicePixelRatio || 1, 2);
const SIZE = 460;
const cx = SIZE / 2, cy = SIZE / 2;
const baseR = 46, ringR = 120;

function setupCanvas() {
  canvas.width = SIZE * DPR;
  canvas.height = SIZE * DPR;
  ctx.scale(DPR, DPR);
}
setupCanvas();

const N = 84;
const particles = Array.from({ length: N }, () => ({
  a: Math.random() * Math.PI * 2,
  rf: 0.92 + Math.random() * 0.5,
  spd: (0.15 + Math.random() * 0.5) * (Math.random() < 0.5 ? 1 : -1),
  size: 0.8 + Math.random() * 1.8,
  ph: Math.random() * Math.PI * 2,
}));

// A tighter, counter-rotating inner ring adds depth and motion.
const N2 = 46;
const innerParticles = Array.from({ length: N2 }, () => ({
  a: Math.random() * Math.PI * 2,
  rf: 0.5 + Math.random() * 0.28,
  spd: -(0.25 + Math.random() * 0.6),
  size: 0.6 + Math.random() * 1.2,
  ph: Math.random() * Math.PI * 2,
}));

// Expanding rings emitted while speaking, like a voice waveform.
let ripples = [];
let lastRipple = 0;

function rgba(c, a) { return `rgba(${c[0]},${c[1]},${c[2]},${a})`; }

const t0 = performance.now();
function frame(now) {
  const t = (now - t0) / 1000;
  level += (target - level) * 0.15;
  ctx.clearRect(0, 0, SIZE, SIZE);
  const c = COLORS[state] || COLORS.idle;

  const breathe = 1 + Math.sin(t * 1.6) * 0.04;
  let react = 0;
  if (state === "listening") react = level * 0.6;
  else if (state === "speaking") react = (0.5 + 0.5 * Math.abs(Math.sin(t * 7))) * 0.32;
  else if (state === "thinking") react = 0.05 + 0.05 * Math.sin(t * 4);
  const coreR = baseR * (breathe + react);

  ctx.save();
  ctx.lineWidth = 1;
  for (let i = 0; i < 3; i++) {
    const rr = coreR * (2.2 + i * 0.9) * (1 + react * 0.25);
    ctx.beginPath();
    ctx.arc(cx, cy, rr, 0, Math.PI * 2);
    ctx.strokeStyle = rgba(c, 0.06 + i * 0.02);
    ctx.stroke();
  }
  if (state === "thinking") {
    const sweep = t * 2.4;
    ctx.beginPath();
    ctx.arc(cx, cy, ringR * 1.15, sweep, sweep + 1.1);
    ctx.strokeStyle = rgba(c, 0.5);
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  ctx.restore();

  const spinBase = state === "thinking" ? 2.2 : state === "listening" ? 1.0 : 0.5;
  ctx.save();
  ctx.shadowBlur = 8;
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
  // Inner counter-rotating ring.
  for (const p of innerParticles) {
    const ang = p.a + t * p.spd * spinBase;
    const rr = ringR * p.rf * (1 + react * 0.5);
    const x = cx + Math.cos(ang) * rr;
    const y = cy + Math.sin(ang) * rr;
    const tw = 0.4 + 0.6 * Math.abs(Math.sin(t * 2.1 + p.ph));
    ctx.beginPath();
    ctx.arc(x, y, p.size, 0, Math.PI * 2);
    ctx.fillStyle = rgba(c, tw * (0.4 + react));
    ctx.fill();
  }
  ctx.restore();

  // Speaking emits expanding echo rings; idle/listening let them fade out.
  if (state === "speaking" && now - lastRipple > 360) {
    ripples.push({ born: t });
    lastRipple = now;
  }
  ctx.save();
  ctx.lineWidth = 1.5;
  ripples = ripples.filter((rp) => t - rp.born < 1.8);
  for (const rp of ripples) {
    const age = t - rp.born;
    const rr = coreR * 1.4 + age * 130;
    ctx.beginPath();
    ctx.arc(cx, cy, rr, 0, Math.PI * 2);
    ctx.strokeStyle = rgba(c, Math.max(0, 0.32 * (1 - age / 1.8)));
    ctx.stroke();
  }
  ctx.restore();

  ctx.save();
  ctx.shadowBlur = 60 + react * 60;
  ctx.shadowColor = rgba(c, 0.8);
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
  g.addColorStop(0, "rgba(240,252,255,0.98)");
  g.addColorStop(0.42, rgba(c, 0.92));
  g.addColorStop(1, rgba(c, 0));
  ctx.beginPath();
  ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
  ctx.fillStyle = g;
  ctx.fill();
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
  if (s === "idle") scheduleFade();
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
