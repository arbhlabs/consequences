// Consequences Brain: 3D "brain in space" score map.
// Rendering pipeline ported from an earlier ARBH Labs brain view (three.js r170):
// same point-sprite node shader (core + gaussian glow + hologram rings on hubs), additive link shader with energy
// flow, dust field, exp2 fog, UnrealBloom (0.6, 0.5, 0.32) + OutputPass, gimbal rings around the focus.
// Mapping: core = the Consequences ledger, hubs = agents (size = |net score|, warm = positive, red = negative),
// small nodes = scored events orbiting their agent. Added: depth-of-field on sprites, faint nebula sky.
//
// Render scheduling: always alive while the window is visible, focused or not (people watch it from another screen).
// 60 fps while something moves (input, camera spring, new data); otherwise a steady ambient drift at AMBIENT_FPS,
// paced on the display refresh (every 2nd vsync at 60 Hz) so it glides instead of stepping.
// Minimised / hidden / occluded (document.hidden) -> fully stopped; a data change then renders one snapped frame.
import * as THREE from "./vendor/three-0.170.0/three.module.min.js";
import { OrbitControls } from "./vendor/three-0.170.0/OrbitControls.js";
import { EffectComposer } from "./vendor/three-0.170.0/EffectComposer.js";
import { RenderPass } from "./vendor/three-0.170.0/RenderPass.js";
import { UnrealBloomPass } from "./vendor/three-0.170.0/UnrealBloomPass.js";
import { OutputPass } from "./vendor/three-0.170.0/OutputPass.js";

const QS = new URLSearchParams(location.search);
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const AMBIENT_FPS = Number(QS.get("fps")) || 30; // drift + working pulse whenever visible
const LAB = { nosky: QS.has("nosky"), nobloom: QS.has("nobloom") };   // cost experiments only (never set by the app)
const BG = 0x02060c; // the clear colour; through this composer it renders as navy (~22,42,61), measured
// the four-step scale, same hex values as index.html: green, yellow, orange, red (best to worst)
const COL = { green: "#4fe08a", yellow: "#ffe14d", orange: "#ff9f43", red: "#ff5d73", zero: "#8aa0b6", core: "#cff6ff", holo: "#5fe3ff" };
const GOLDEN = Math.PI * (3 - Math.sqrt(5));

const $ = (id) => document.getElementById(id);
const canvas = $("gl");
const labelsEl = $("labels");
const tipEl = $("scene-tip");
const msgEl = $("scene-msg");
const hash = (s) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return ((h >>> 0) % 100000) / 100000; };
const fmt = (v) => { v = Math.round(Number(v) || 0); return (v > 0 ? "+" : "") + v; };
const nowS = () => performance.now() / 1000;

// ---------------------------------------------------------------- renderer (settings)
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, powerPreference: "high-performance" });
} catch (e) {
  failGL("The 3D view needs WebGL, which this graphics driver did not provide. Leaderboard, feed and Ask still update live.");
}
if (renderer) boot();

function failGL(text) {
  if (msgEl) { msgEl.textContent = text; msgEl.hidden = false; }
  window.CBScene = { setData() {}, select() {}, overview() {}, setVisible() {}, stats: () => ({ ok: false, renders: 0 }), project: () => null, ok: false };
  window.dispatchEvent(new Event("cbscene-ready"));
}

function boot() {
renderer.setClearColor(BG, 1);
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(BG, 0.00042);
const camera = new THREE.PerspectiveCamera(55, 1, 1, 12000);
camera.position.set(420, 300, 1500);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.075;
controls.rotateSpeed = 0.7;
controls.zoomSpeed = 1.1;
controls.minDistance = 90;
controls.maxDistance = 4200;
controls.enablePan = true;

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.6, 0.5, 0.32);
composer.addPass(bloom);
composer.addPass(new OutputPass()); // every tier goes through OutputPass so the background tone never changes

// quality tiers: [max DPR, bloom on, bloom res scale]
const TIERS = [[1, false, 0.5], [1, true, 0.6], [1.5, true, 0.75], [2, true, 0.75]];
let tier = 3;
const tierStart = tier;
let downgrades = 0;

// ---------------------------------------------------------------- shaders (with depth of field)
const nodeMat = new THREE.ShaderMaterial({
  uniforms: { uTime: { value: 0 }, uScale: { value: 800 }, uFocus: { value: 1500 } },
  vertexShader: /* glsl */ `
    attribute vec3 color; attribute float aSize; attribute float aHl; attribute float aChanged; attribute float aSpawn; attribute float aKind; attribute float aWork; attribute float aAsk;
    uniform float uTime; uniform float uScale; uniform float uFocus;
    varying vec3 vC; varying float vA; varying float vAge; varying float vKind; varying float vSeed; varying float vBlur; varying float vWork; varying float vAsk;
    void main() {
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      gl_Position = projectionMatrix * mv;
      float sp = clamp((uTime - aSpawn) / 0.9, 0.0, 1.0);
      float pop = sp < 1.0 ? (1.0 + 1.4 * sin(sp * 3.14159)) * sp : 1.0;
      float hlScale = 0.75 + 0.25 * clamp(aHl, 0.0, 2.0);
      vBlur = clamp(abs(-mv.z - uFocus) / uFocus * 1.15, 0.0, 1.0) * (aKind > 1.5 ? 0.0 : 1.0);
      float beat = aWork > 0.5 ? 1.0 + 0.10 * sin(uTime * 3.2) : 1.0;
      gl_PointSize = clamp(aSize * pop * hlScale * beat * (aWork > 0.5 ? 1.35 : 1.0) * (1.0 + vBlur * 0.55) * uScale / max(1.0, -mv.z), 1.5, 340.0);
      vWork = aWork; vAsk = aAsk;
      vC = color; vA = aHl; vAge = uTime - aChanged; vKind = aKind; vSeed = fract(position.x * 0.0137 + position.z * 0.0071);
    }`,
  fragmentShader: /* glsl */ `
    uniform float uTime;
    varying vec3 vC; varying float vA; varying float vAge; varying float vKind; varying float vSeed; varying float vBlur; varying float vWork; varying float vAsk;
    void main() {
      vec2 c = gl_PointCoord * 2.0 - 1.0;
      float r = length(c);
      if (r > 1.0) discard;
      float core = smoothstep(0.30 + vBlur * 0.28, 0.0, r) * (1.0 - vBlur * 0.55);
      float glow = exp(-r * r * mix(6.0, 3.2, vBlur)) * 0.6;
      vec3 col = vC * (glow * 0.85 + core * 0.8) + vec3(1.0) * pow(core, 3.0) * 0.4;
      if (vKind > 0.5) {                     // agents + core: hologram rings
        float ring = smoothstep(0.045, 0.0, abs(r - 0.62)) * 0.9 + smoothstep(0.03, 0.0, abs(r - 0.86)) * 0.45;
        float a = atan(c.y, c.x);
        ring *= 0.55 + 0.45 * step(0.0, sin(a * (vKind > 1.5 ? 12.0 : 6.0) + uTime * (vKind > 1.5 ? 0.8 : -1.2)));
        col += vC * ring * (1.0 - vBlur * 0.6);
      }
      if (vWork > 0.5) {                     // working now: breathing halo + a comet running round the outer ring
        float a2 = atan(c.y, c.x);
        float head = fract((a2 / 6.28318) - uTime * 0.45);
        float comet = smoothstep(0.05, 0.0, abs(r - 0.93)) * pow(head, 6.0) * 2.2;
        float halo = exp(-pow((r - 0.74) * 7.0, 2.0)) * (0.35 + 0.3 * sin(uTime * 3.2));
        col += vec3(0.75, 1.0, 0.9) * comet + mix(vC, vec3(0.6, 1.0, 0.85), 0.45) * halo;
      }
      if (vAsk > 0.5) {                      // finished, waiting for points: slow golden double ring
        float br = 0.5 + 0.5 * sin(uTime * 1.6);
        col += vec3(1.0, 0.78, 0.32) * (smoothstep(0.035, 0.0, abs(r - 0.80)) + 0.6 * smoothstep(0.03, 0.0, abs(r - 0.90))) * (0.45 + 0.9 * br);
      }
      if (vAge < 6.0 && vAge > -5.0) {       // just changed: pulse rings, a flash on arrival
        float fade = 1.0 - clamp(vAge / 6.0, 0.0, 1.0);
        float rp = fract(uTime * 0.55 + vSeed);
        float rr = 0.25 + rp * 0.72;
        col += vec3(0.7, 1.0, 0.85) * smoothstep(0.07, 0.0, abs(r - rr)) * (1.0 - rp) * 1.6 * fade;
        col += vec3(1.0) * core * 2.5 * exp(-max(vAge, 0.0) / 2.5);
      }
      gl_FragColor = vec4(col * clamp(vA, 0.0, 1.6), 1.0);
    }`,
  transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
});

const linkMat = new THREE.ShaderMaterial({
  uniforms: { uTime: { value: 0 }, uFlow: { value: 1 } },
  vertexShader: /* glsl */ `
    attribute vec3 color; attribute float aA; attribute float aT; attribute float aSeed; attribute float aFlow;
    varying vec3 vC; varying float vA; varying float vT; varying float vS; varying float vF;
    void main() { vC = color; vA = aA; vT = aT; vS = aSeed; vF = aFlow; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: /* glsl */ `
    uniform float uTime; uniform float uFlow;
    varying vec3 vC; varying float vA; varying float vT; varying float vS; varying float vF;
    void main() {
      float sp = abs(vF);
      float t = vF < 0.0 ? 1.0 - vT : vT;
      float f = sp > 0.001 ? pow(fract(t - uTime * 0.35 * sp + vS), 16.0) : 0.0;   // still line unless real activity
      gl_FragColor = vec4(vC * vA * (0.55 + f * 3.0 * uFlow) * (sp > 0.001 ? 1.35 : 1.0), 1.0);
    }`,
  transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
});

const partMat = new THREE.ShaderMaterial({
  uniforms: { uScale: { value: 800 } },
  vertexShader: /* glsl */ `
    attribute vec3 color; uniform float uScale; varying vec3 vC;
    void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_Position = projectionMatrix * mv;
      gl_PointSize = clamp(5.0 * uScale / max(1.0, -mv.z), 1.5, 40.0); vC = color; }`,
  fragmentShader: /* glsl */ `
    varying vec3 vC;
    void main() { float r = length(gl_PointCoord * 2.0 - 1.0); if (r > 1.0) discard;
      gl_FragColor = vec4((vC * 0.6 + 0.6) * exp(-r * r * 5.0), 1.0); }`,
  transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
});

const dustMat = new THREE.ShaderMaterial({
  uniforms: { uScale: { value: 800 }, uTime: { value: 0 }, uFocus: { value: 1500 } },
  vertexShader: /* glsl */ `
    attribute float aS; uniform float uScale; uniform float uTime; uniform float uFocus; varying float vA; varying float vB;
    void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_Position = projectionMatrix * mv;
      vB = clamp((uFocus * 0.55 - (-mv.z)) / (uFocus * 0.55), 0.0, 1.0);          // dust in front of the focus: soft bokeh
      gl_PointSize = clamp(aS * (1.0 + vB * 2.5) * uScale / max(1.0, -mv.z), 1.0, 6.0 + vB * 18.0);
      vA = (0.25 + 0.2 * sin(uTime * 0.7 + position.x * 0.01)) * (1.0 - vB * 0.7); }`,
  fragmentShader: /* glsl */ `
    varying float vA; varying float vB;
    void main() { float r = length(gl_PointCoord * 2.0 - 1.0); if (r > 1.0) discard;
      gl_FragColor = vec4(vec3(0.45, 0.8, 1.0) * vA * mix(1.0 - r, exp(-r * r * 2.5) * 0.6, vB), 1.0); }`,
  transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
});

// faint nebula sky: view-direction fbm, kept far below the bloom threshold so it only adds depth
const skyMat = new THREE.ShaderMaterial({
  uniforms: {},
  vertexShader: /* glsl */ `varying vec3 vD; void main() { vD = normalize(position); vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0); gl_Position = p.xyww; }`,
  fragmentShader: /* glsl */ `
    varying vec3 vD;
    float h(vec3 p) { p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
    float n(vec3 x) { vec3 i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f);
      return mix(mix(mix(h(i), h(i + vec3(1,0,0)), f.x), mix(h(i + vec3(0,1,0)), h(i + vec3(1,1,0)), f.x), f.y),
                 mix(mix(h(i + vec3(0,0,1)), h(i + vec3(1,0,1)), f.x), mix(h(i + vec3(0,1,1)), h(i + vec3(1,1,1)), f.x), f.y), f.z); }
    float fbm(vec3 p) { float s = 0.0, a = 0.5; for (int i = 0; i < 5; i++) { s += a * n(p); p = p * 2.03 + 11.7; a *= 0.5; } return s; }
    void main() {
      vec3 d = normalize(vD);
      float c1 = smoothstep(0.45, 0.95, fbm(d * 2.2 + vec3(3.1, 0.0, 1.7)));
      float c2 = smoothstep(0.50, 1.00, fbm(d * 3.1 + vec3(-5.0, 2.0, 0.4)));
      float band = exp(-pow(d.y * 2.2 + 0.25 * sin(d.x * 3.0), 2.0));
      vec3 col = vec3(0.004, 0.020, 0.034) * c1 * (0.6 + band) + vec3(0.016, 0.006, 0.030) * c2 * (0.5 + 0.5 * band);
      gl_FragColor = vec4(col, 1.0);
    }`,
  side: THREE.BackSide, depthWrite: false, depthTest: false, fog: false, transparent: true, blending: THREE.AdditiveBlending,
});
const sky = new THREE.Mesh(new THREE.SphereGeometry(10000, 48, 24), skyMat);
sky.renderOrder = -1;
sky.frustumCulled = false;
if (!LAB.nosky) scene.add(sky);

// dust field (1400 points, r 400..3000)
let dust;
{
  const N = 1400, p = new Float32Array(N * 3), s = new Float32Array(N);
  let seed = 7;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < N; i++) {
    const r = 400 + Math.pow(rnd(), 0.6) * 2600, th = rnd() * Math.PI * 2, ph = Math.acos(2 * rnd() - 1);
    p[i * 3] = r * Math.sin(ph) * Math.cos(th); p[i * 3 + 1] = r * Math.cos(ph) * 0.6; p[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
    s[i] = 2 + rnd() * 5;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(p, 3));
  g.setAttribute("aS", new THREE.BufferAttribute(s, 1));
  dust = new THREE.Points(g, dustMat);
  dust.frustumCulled = false;
  dust.renderOrder = 0;
  scene.add(dust);
}

// focus gimbal rings
const ringGroup = new THREE.Group();
{
  const mk = (r, col, dashed) => {
    const pts = [];
    for (let i = 0; i <= 128; i++) { const a = (i / 128) * Math.PI * 2; pts.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0)); }
    const g = new THREE.BufferGeometry().setFromPoints(pts);
    const m = dashed
      ? new THREE.LineDashedMaterial({ color: col, dashSize: 0.05, gapSize: 0.035, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false })
      : new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: 0.6, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false });
    const l = new THREE.Line(g, m);
    if (dashed) l.computeLineDistances();
    return l;
  };
  const a = mk(1, 0x5fe3ff, true), b = mk(1.0, 0x5fe3ff, false), c = mk(0.72, 0xb78bff, true);
  b.rotation.x = Math.PI / 2; c.rotation.y = Math.PI / 2;
  ringGroup.add(a, b, c);
  ringGroup.visible = false;
  ringGroup.renderOrder = 3;
  scene.add(ringGroup);
}

// faint orbit paths of each agent's events
const orbitMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 1, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false });

// ---------------------------------------------------------------- state
const S = {
  nodes: [], byId: new Map(), links: [], orbits: [], splits: [],
  selected: null, hover: null, model: null, first: true, seen: new Set(),
  focusDist: 1500, center: new THREE.Vector3(), radius: 400,
};
let nodePts = null, linkSeg = null, orbitSeg = null, parts = null;
const tmpV = new THREE.Vector3(), tmpC = new THREE.Color();

function colorFor(v) { return v > 0 ? COL.green : v < 0 ? COL.red : COL.zero; }   // one scored event: by sign
function agentSize(v) { return 26 + Math.sqrt(Math.abs(Number(v) || 0)) * 3.1; }
function eventSize(v) { return 7 + Math.sqrt(Math.abs(Number(v) || 0)) * 1.25; }
function spring(x, k, z) { return { x, v: 0, t: x, k, c: 2 * Math.sqrt(k) * (z || 0.82) }; }
function stepSpring(s, dt) { const a = -s.k * (s.x - s.t) - s.c * s.v; s.v += a * dt; s.x += s.v * dt; if (Math.abs(s.x - s.t) < 0.02 && Math.abs(s.v) < 0.02) { s.x = s.t; s.v = 0; return false; } return true; }

// agent layout: golden-angle ring in x/z; height follows the signed score, so standing reads as altitude
function layoutAgents(agents) {
  const n = agents.length;
  return agents.map((a, i) => {
    const v = Number(a.val) || 0;
    const th = i * GOLDEN * 2.2 + 0.6;
    const rr = 300 + 120 * ((i * 5) % 3) / 2 + 40 * hash(a.id);
    const y = Math.max(-320, Math.min(320, Math.sign(v) * Math.sqrt(Math.abs(v)) * 24)) + (hash(a.id + "y") - 0.5) * 60;
    return [rr * Math.cos(th), y, rr * Math.sin(th)];
  });
}

// ---------------------------------------------------------------- data -> scene
function setData(model) {
  S.model = model;
  const t = nowS();
  const working = new Set(model.working || []);
  const asking = new Set(model.asking || []);
  S.anyWorking = working.size > 0;
  const old = S.byId;
  const agents = model.agents.slice().sort((a, b) => (Number(b.val) || 0) - (Number(a.val) || 0) || String(a.label).localeCompare(b.label));
  const pos = layoutAgents(agents);
  const nodes = [];
  const first = S.first && !REDUCED;
  // core
  const core = old.get("@core") || { id: "@core", kind: 2, label: "CONSEQUENCES", px: spring(0, 60), py: spring(0, 60), pz: spring(0, 60), sz: spring(70, 120), spawn: first ? t : -100, changed: -100 };
  core.color = COL.core; core.val = 0; nodes.push(core);
  agents.forEach((a, i) => {
    let n = old.get(a.id);
    const [x, y, z] = pos[i];
    if (!n) {
      n = { id: a.id, kind: 1, px: spring(first ? 0 : x, 55), py: spring(first ? 0 : y, 55), pz: spring(first ? 0 : z, 55), sz: spring(first ? 0 : agentSize(a.val), 120, 0.6),
            spawn: first ? t + 0.25 + i * 0.07 : (S.first ? -100 : t), changed: S.first ? -100 : t };
    } else if (Number(n.val) !== Number(a.val)) { n.changed = t; n.delta = Number(a.val) - Number(n.val); }
    n.label = a.label; n.val = Number(a.val) || 0; n.standing = a.standing; n.count = a.count; n.color = COL[a.tier] || colorFor(n.val);
    n.work = working.has(a.id); n.wn = (model.workCount || {})[a.id] || 1; n.ask = asking.has(a.id); n.task = (model.tasks || {})[a.id] || "";
    n.px.t = x; n.py.t = y; n.pz.t = z; n.sz.t = agentSize(n.val);
    nodes.push(n);
  });
  // events: shells of 9 around each agent, newest on the inner shell
  const byAgent = new Map();
  model.events.forEach((e) => { const k = "a:" + (e.agent || "UNATTRIBUTED"); if (!byAgent.has(k)) byAgent.set(k, []); byAgent.get(k).push(e); });
  S.orbits = [];
  nodes.filter((n) => n.kind === 1).forEach((ag) => {
    const list = (byAgent.get(ag.id) || []).slice().sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
    const shells = Math.ceil(list.length / 9);
    for (let s = 0; s < shells; s++) {
      const tilt = hash(ag.id + "t" + s) * Math.PI, yaw = hash(ag.id + "w" + s) * Math.PI * 2;
      const U = new THREE.Vector3(Math.cos(yaw), 0, Math.sin(yaw));
      const V = new THREE.Vector3(-Math.sin(yaw) * Math.cos(tilt), Math.sin(tilt), Math.cos(yaw) * Math.cos(tilt)).normalize();
      S.orbits.push({ agent: ag, s, U, V });
    }
    list.forEach((e, k) => {
      const s = Math.floor(k / 9), slot = k % 9, inShell = Math.min(9, list.length - s * 9);
      const orb = S.orbits.find((o) => o.agent === ag && o.s === s);
      let n = old.get(e.id);
      if (!n) {
        const isNew = !S.first && !S.seen.has(e.id);   // only a genuinely new ledger row pops and lights its spoke, once
        n = { id: e.id, kind: 0, sz: spring(first || isNew ? 0 : eventSize(e.val), 140, 0.6),
              spawn: first ? t + 0.9 + k * 0.02 : (isNew ? t : -100), changed: isNew ? t : -100, fresh: isNew };
      }
      S.seen.add(e.id);
      n.agent = ag; n.orb = orb; n.shell = s; n.val = Number(e.val) || 0; n.title = e.title; n.ts = e.ts; n.color = colorFor(n.val);
      n.phase = (slot / inShell) * Math.PI * 2 + hash(e.id) * 0.4;
      n.speed = (s % 2 ? -1 : 1) * 0.11 / (1 + s * 0.45);
      n.sz.t = eventSize(n.val);
      nodes.push(n);
    });
  });
  S.nodes = nodes;
  S.byId = new Map(nodes.map((n) => [n.id, n]));
  S.splits = (model.splits || []).filter(([a, b]) => S.byId.has(a) && S.byId.has(b));
  if (S.selected && !S.byId.has(S.selected)) S.selected = null;
  buildGeometry();
  if (S.first) { S.first = false; S.bootT = t; frameOverview(true); }
  if (model.selected !== undefined) applySelection(model.selected, false);
  kick(first ? 3200 : 2400);
  if (!running()) renderOnce(true); // stopped (unfocused/hidden/idle): show the new data in one snapped frame
}

function shellRadius(n, s) { return n.sz.x * 1.05 + 30 + s * 24; }

function buildGeometry() {
  for (const o of [nodePts, linkSeg, orbitSeg, parts]) if (o) { scene.remove(o); o.geometry.dispose(); }
  const N = S.nodes.length;
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(N * 3), 3).setUsage(THREE.DynamicDrawUsage));
  const col = new Float32Array(N * 3), kind = new Float32Array(N), spawn = new Float32Array(N), changed = new Float32Array(N);
  S.nodes.forEach((n, i) => { tmpC.set(n.color); col.set([tmpC.r, tmpC.g, tmpC.b], i * 3); kind[i] = n.kind; spawn[i] = n.spawn; changed[i] = n.changed; n.i = i; if (n.hl == null) n.hl = 1; });
  g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  g.setAttribute("aSize", new THREE.BufferAttribute(new Float32Array(N), 1).setUsage(THREE.DynamicDrawUsage));
  g.setAttribute("aHl", new THREE.BufferAttribute(new Float32Array(N).fill(1), 1).setUsage(THREE.DynamicDrawUsage));
  g.setAttribute("aKind", new THREE.BufferAttribute(kind, 1));
  g.setAttribute("aSpawn", new THREE.BufferAttribute(spawn, 1));
  g.setAttribute("aChanged", new THREE.BufferAttribute(changed, 1));
  g.setAttribute("aWork", new THREE.BufferAttribute(new Float32Array(S.nodes.map((n) => (n.work ? 1 : 0))), 1));
  g.setAttribute("aAsk", new THREE.BufferAttribute(new Float32Array(S.nodes.map((n) => (n.ask ? 1 : 0))), 1));
  nodePts = new THREE.Points(g, nodeMat);
  nodePts.frustumCulled = false; nodePts.renderOrder = 2;
  scene.add(nodePts);

  // links: core->agent (k0), split agent<->agent (k2), agent->event spokes (k1)
  S.links = [];
  S.nodes.forEach((n) => { if (n.kind === 1) S.links.push([S.byId.get("@core"), n, 0]); });
  S.splits.forEach(([a, b]) => S.links.push([S.byId.get(a), S.byId.get(b), 2]));
  S.nodes.forEach((n) => { if (n.kind === 0) S.links.push([n.agent, n, 1]); });
  const M = S.links.length;
  const lc = new Float32Array(M * 6), lt = new Float32Array(M * 2), ls = new Float32Array(M * 2);
  S.links.forEach(([a, b, k], i) => {
    tmpC.set(a.color); lc.set([tmpC.r, tmpC.g, tmpC.b], i * 6);
    tmpC.set(b.color); lc.set([tmpC.r, tmpC.g, tmpC.b], i * 6 + 3);
    lt[i * 2] = 0; lt[i * 2 + 1] = k === 1 ? 0.35 + 0.65 * hash(String(i)) : 1;
    const sd = hash("s" + a.id + "," + b.id); ls[i * 2] = sd; ls[i * 2 + 1] = sd;
  });
  const lg = new THREE.BufferGeometry();
  lg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(M * 6), 3).setUsage(THREE.DynamicDrawUsage));
  lg.setAttribute("color", new THREE.BufferAttribute(lc, 3));
  lg.setAttribute("aA", new THREE.BufferAttribute(new Float32Array(M * 2), 1).setUsage(THREE.DynamicDrawUsage));
  lg.setAttribute("aT", new THREE.BufferAttribute(lt, 1));
  lg.setAttribute("aSeed", new THREE.BufferAttribute(ls, 1));
  lg.setAttribute("aFlow", new THREE.BufferAttribute(new Float32Array(M * 2), 1).setUsage(THREE.DynamicDrawUsage));
  linkSeg = new THREE.LineSegments(lg, linkMat);
  linkSeg.frustumCulled = false; linkSeg.renderOrder = 1;
  scene.add(linkSeg);

  // orbit paths (64 segments each)
  const SEG = 64, O = S.orbits.length;
  const og = new THREE.BufferGeometry();
  og.setAttribute("position", new THREE.BufferAttribute(new Float32Array(O * SEG * 6), 3).setUsage(THREE.DynamicDrawUsage));
  og.setAttribute("color", new THREE.BufferAttribute(new Float32Array(O * SEG * 6), 3).setUsage(THREE.DynamicDrawUsage));
  orbitSeg = new THREE.LineSegments(og, orbitMat);
  orbitSeg.frustumCulled = false; orbitSeg.renderOrder = 1;
  scene.add(orbitSeg);
  S.orbitDirty = true;

  // energy particles along the focused agent's links (particle material)
  const P = 160;
  const pg = new THREE.BufferGeometry();
  pg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(P * 3), 3).setUsage(THREE.DynamicDrawUsage));
  pg.setAttribute("color", new THREE.BufferAttribute(new Float32Array(P * 3), 3).setUsage(THREE.DynamicDrawUsage));
  pg.setDrawRange(0, 0);
  parts = new THREE.Points(pg, partMat);
  parts.frustumCulled = false; parts.renderOrder = 3;
  scene.add(parts);
  updateHighlight();
}

// ---------------------------------------------------------------- per-frame writes (CPU positions = one truth for render + picking)
function writeScene(t, dt) {
  let moving = false;
  for (const n of S.nodes) {
    if (n.kind > 0) { moving = stepSpring(n.px, dt) | moving; moving = stepSpring(n.py, dt) | moving; moving = stepSpring(n.pz, dt) | moving; }
    moving = stepSpring(n.sz, dt) | moving;
  }
  const orbitsNeedWrite = moving || S.orbitDirty;
  S.orbitDirty = false;
  const P = nodePts.geometry.attributes.position.array, Z = nodePts.geometry.attributes.aSize.array, H = nodePts.geometry.attributes.aHl.array;
  for (const n of S.nodes) {
    if (n.kind > 0) { n.x = n.px.x; n.y = n.py.x; n.z = n.pz.x; }
    else {
      const a = n.agent, R = shellRadius(a, n.shell), th = n.phase + t * n.speed * (REDUCED ? 0 : 1);
      const c = Math.cos(th) * R, s = Math.sin(th) * R;
      n.x = a.px.x + n.orb.U.x * c + n.orb.V.x * s; n.y = a.py.x + n.orb.U.y * c + n.orb.V.y * s; n.z = a.pz.x + n.orb.U.z * c + n.orb.V.z * s;
    }
    P[n.i * 3] = n.x; P[n.i * 3 + 1] = n.y; P[n.i * 3 + 2] = n.z;
    Z[n.i] = Math.max(0, n.sz.x);
    const d = n.hlTo - n.hl;
    if (Math.abs(d) > 0.004) { n.hl += d * Math.min(1, dt * 7); moving = true; } else n.hl = n.hlTo;
    H[n.i] = n.hl;
  }
  nodePts.geometry.attributes.position.needsUpdate = true;
  nodePts.geometry.attributes.aSize.needsUpdate = true;
  nodePts.geometry.attributes.aHl.needsUpdate = true;
  const lp = linkSeg.geometry.attributes.position.array, la = linkSeg.geometry.attributes.aA.array;
  S.links.forEach(([a, b], i) => {
    lp[i * 6] = a.x; lp[i * 6 + 1] = a.y; lp[i * 6 + 2] = a.z; lp[i * 6 + 3] = b.x; lp[i * 6 + 4] = b.y; lp[i * 6 + 5] = b.z;
    const d = S.laTo[i] - S.laCur[i];
    if (Math.abs(d) > 0.002) { S.laCur[i] += d * Math.min(1, dt * 7); moving = true; } else S.laCur[i] = S.laTo[i];
    la[i * 2] = la[i * 2 + 1] = S.laCur[i];
  });
  // light moves only for real events: an agent working (steady inward flow), a score change (fast burst: inward for a
  // gain, outward for a loss) and a just-scored event on its spoke. Everything else is a still, solid line.
  const lf = linkSeg.geometry.attributes.aFlow.array;
  S.links.forEach(([a, b, k], i) => {
    let fl = 0;
    if (k === 0) {
      if (t - b.changed < 6 && t - b.changed >= 0) fl = (b.delta || 0) < 0 ? -2.6 : 2.6;
      else if (b.work) fl = 1;
    } else if (k === 1 && b.fresh && t - b.spawn < 8 && t - b.spawn >= 0) fl = 2;
    lf[i * 2] = lf[i * 2 + 1] = fl;
  });
  linkSeg.geometry.attributes.aFlow.needsUpdate = true;
  linkSeg.geometry.attributes.position.needsUpdate = true;
  linkSeg.geometry.attributes.aA.needsUpdate = true;
  // orbit paths (static unless an agent moved or the highlight changed)
  const SEG = 64, op = orbitSeg.geometry.attributes.position.array, oc = orbitSeg.geometry.attributes.color.array;
  if (orbitsNeedWrite) {
  S.orbits.forEach((o, j) => {
    const a = o.agent, R = shellRadius(a, o.s);
    tmpC.set(a.color);
    const sel = S.selected === a.id, alpha = (sel ? 0.22 : 0.06) * Math.min(1, a.hl);
    for (let q = 0; q < SEG; q++) {
      for (let e = 0; e < 2; e++) {
        const th = ((q + e) / SEG) * Math.PI * 2, c = Math.cos(th) * R, s = Math.sin(th) * R, k = (j * SEG + q) * 6 + e * 3;
        op[k] = a.x + o.U.x * c + o.V.x * s; op[k + 1] = a.y + o.U.y * c + o.V.y * s; op[k + 2] = a.z + o.U.z * c + o.V.z * s;
        oc[k] = tmpC.r * alpha; oc[k + 1] = tmpC.g * alpha; oc[k + 2] = tmpC.b * alpha;
      }
    }
  });
  orbitSeg.geometry.attributes.position.needsUpdate = true;
  orbitSeg.geometry.attributes.color.needsUpdate = true;
  }
  // energy particles on the selected agent's links
  const pp = parts.geometry.attributes.position.array, pc = parts.geometry.attributes.color.array;
  let w = 0;
  // energy streaming core -> agent while it works, and a 3 s burst when its points change
  for (const [a, b, k] of S.links) {
    if (k !== 0 || w >= 150) continue;
    const burst = t - b.changed < 3 && t - b.changed > 0;
    if (!b.work && !burst) continue;
    for (let r = 0; r < (burst ? 6 : 3) && w < 150; r++, w++) {
      let f = (t * (burst ? 0.9 : 0.32) + r / (burst ? 6 : 3) + hash("w" + b.id)) % 1;
      if (burst && (b.delta || 0) < 0) f = 1 - f;   // a loss drains outward
      pp[w * 3] = a.x + (b.x - a.x) * f; pp[w * 3 + 1] = a.y + (b.y - a.y) * f; pp[w * 3 + 2] = a.z + (b.z - a.z) * f;
      tmpC.set(burst ? b.color : "#7dffc8"); pc[w * 3] = tmpC.r; pc[w * 3 + 1] = tmpC.g; pc[w * 3 + 2] = tmpC.b;
    }
  }
  if (S.selected) {
    const selNode = S.byId.get(S.selected), focusAgent = selNode ? (selNode.kind === 1 ? selNode : selNode.agent) : null;
    S.links.forEach(([a, b, k], i) => {
      if (!focusAgent || (a !== focusAgent && b !== focusAgent) || w >= 160) return;
      for (let r = 0; r < (k === 1 ? 1 : 3) && w < 160; r++, w++) {
        const f = (t * 0.32 + r / 3 + hash("p" + i)) % 1;
        pp[w * 3] = a.x + (b.x - a.x) * f; pp[w * 3 + 1] = a.y + (b.y - a.y) * f; pp[w * 3 + 2] = a.z + (b.z - a.z) * f;
        tmpC.set(b.color); pc[w * 3] = tmpC.r; pc[w * 3 + 1] = tmpC.g; pc[w * 3 + 2] = tmpC.b;
      }
    });
  }
  parts.geometry.setDrawRange(0, w);
  parts.geometry.attributes.position.needsUpdate = true;
  parts.geometry.attributes.color.needsUpdate = true;
  // gimbal
  const sel = S.selected && S.byId.get(S.selected);
  ringGroup.visible = !!sel;
  if (sel) {
    ringGroup.position.set(sel.x, sel.y, sel.z);
    ringGroup.scale.setScalar(sel.kind === 1 ? shellRadius(sel, 0) * 0.7 : 18);
    ringGroup.children[0].quaternion.copy(camera.quaternion);
    ringGroup.children[0].rotateZ(t * 0.4);
    ringGroup.children[1].rotation.z = t * 0.25;
    ringGroup.children[2].rotation.x = t * 0.31;
  }
  return moving;
}

function updateHighlight() {
  S.orbitDirty = true;
  const sel = S.selected && S.byId.get(S.selected);
  const focusAgent = sel ? (sel.kind === 1 ? sel : sel.kind === 0 ? sel.agent : null) : null;
  const linked = new Set();
  if (focusAgent) S.splits.forEach(([a, b]) => { if (a === focusAgent.id) linked.add(b); if (b === focusAgent.id) linked.add(a); });
  for (const n of S.nodes) {
    let v = 1;
    if (focusAgent) {
      if (n === sel) v = 1.6;
      else if (n === focusAgent || (n.kind === 0 && n.agent === focusAgent)) v = 1.25;
      else if (n.kind === 2 || linked.has(n.id)) v = 0.9;
      else v = n.kind ? 0.35 : 0.12;
    }
    if (S.hover === n.id) v = Math.max(v, 1.5);
    n.hlTo = v;
  }
  S.laTo = new Float32Array(S.links.length); S.laCur = S.laCur && S.laCur.length === S.links.length ? S.laCur : new Float32Array(S.links.length);
  S.links.forEach(([a, b, k], i) => {
    let v = k === 0 ? (b.work ? 0.75 : 0.30) : k === 2 ? 0.34 : 0.055;
    if (focusAgent) v = (a === focusAgent || b === focusAgent) ? (k === 1 ? 0.5 : 1.05) : k === 1 ? 0.015 : 0.05;
    S.laTo[i] = v;
  });
}

// ---------------------------------------------------------------- camera: critically damped spring focus
const cam = { active: false, tx: spring(0, 40, 1), ty: spring(0, 40, 1), tz: spring(0, 40, 1), d: spring(1500, 40, 1), dir: new THREE.Vector3() };
function focusCamera(target, dist, snap) {
  cam.dir.copy(camera.position).sub(controls.target).normalize();
  if (!isFinite(cam.dir.x) || cam.dir.lengthSq() < 0.5) cam.dir.set(0.3, 0.25, 1).normalize();
  cam.tx.x = controls.target.x; cam.ty.x = controls.target.y; cam.tz.x = controls.target.z; cam.d.x = camera.position.distanceTo(controls.target);
  for (const s of [cam.tx, cam.ty, cam.tz, cam.d]) s.v = 0;
  cam.tx.t = target.x; cam.ty.t = target.y; cam.tz.t = target.z; cam.d.t = dist;
  cam.active = true;
  if (snap || REDUCED) { for (const s of [cam.tx, cam.ty, cam.tz, cam.d]) s.x = s.t; stepCam(0); cam.active = false; }
}
function stepCam(dt) {
  if (!cam.active) return false;
  let m = false;
  for (const s of [cam.tx, cam.ty, cam.tz, cam.d]) m = stepSpring(s, dt) | m;
  controls.target.set(cam.tx.x, cam.ty.x, cam.tz.x);
  camera.position.copy(controls.target).addScaledVector(cam.dir, cam.d.x);
  if (!m) cam.active = false;
  return m;
}
let freeCache = null;
addEventListener("resize", () => { freeCache = null; labelSize.clear(); });
if (document.fonts) document.fonts.addEventListener("loadingdone", () => labelSize.clear());
function freeArea() {
  if (freeCache) return freeCache;
  return (freeCache = freeAreaNow());
}
function freeAreaNow() {
  const g = document.querySelector('[data-panel="graph"]');
  const r = g ? g.getBoundingClientRect() : { left: 0, top: 0, width: innerWidth, height: innerHeight };
  return { x: r.left, y: r.top, w: Math.max(1, r.width), h: Math.max(1, r.height) };
}
function fitDist(r) {
  const f = freeArea();
  const vf = 2 * Math.atan(Math.tan((camera.fov * Math.PI) / 360) * (f.h / innerHeight));
  const hf = 2 * Math.atan(Math.tan((camera.fov * Math.PI) / 360) * (f.w / innerHeight));
  return (r / Math.sin(Math.min(vf, hf) / 2)) * 0.9;
}
function cloudBounds() {
  const pts = S.nodes.filter((n) => n.kind > 0).map((n) => [n.px.t, n.py.t, n.pz.t]);
  if (!pts.length) return { c: new THREE.Vector3(), r: 400 };
  const c = new THREE.Vector3();
  pts.forEach((p) => c.add(tmpV.set(p[0], p[1], p[2])));
  c.multiplyScalar(1 / pts.length);
  let r = 1;
  S.nodes.filter((n) => n.kind === 1).forEach((n) => { r = Math.max(r, Math.hypot(n.px.t - c.x, n.py.t - c.y, n.pz.t - c.z) + shellRadius({ sz: { x: n.sz.t } }, 2)); });
  return { c, r };
}
function frameOverview(snap) {
  const b = cloudBounds();
  S.center.copy(b.c); S.radius = b.r;
  if (snap) { controls.target.copy(b.c); camera.position.copy(b.c).add(new THREE.Vector3(0.32, 0.26, 1).normalize().multiplyScalar(fitDist(b.r))); controls.update(); }
  else focusCamera(b.c, fitDist(b.r), false);
}
function applySelection(id, fly) {
  S.selected = id && S.byId.has(id) ? id : null;
  updateHighlight();
  const n = S.selected && S.byId.get(S.selected);
  if (n && fly !== false) {
    const a = n.kind === 1 ? n : n.kind === 0 ? n.agent : null;
    if (a) focusCamera(new THREE.Vector3(a.px.t, a.py.t, a.pz.t), Math.max(260, fitDist(shellRadius({ sz: { x: a.sz.t } }, 2) * 1.35)), false);
  }
  kick(1800);
}

// ---------------------------------------------------------------- view offset: centre the scene in the free area between panels
function updateViewOffset() {
  const f = freeArea(), w = innerWidth, h = innerHeight;
  const dx = f.x + f.w / 2 - w / 2, dy = f.y + f.h / 2 - h / 2;
  if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) camera.clearViewOffset();
  else camera.setViewOffset(w, h, -dx, -dy, w, h);
  camera.updateProjectionMatrix();
}
function applySize() {
  const w = innerWidth, h = innerHeight;
  const dpr = Math.min(devicePixelRatio || 1, TIERS[tier][0]);
  renderer.setPixelRatio(dpr);
  renderer.setSize(w, h, false);
  composer.setPixelRatio(dpr);
  composer.setSize(w, h);
  const bs = TIERS[tier][2];
  bloom.setSize(Math.max(64, (w * dpr * bs) | 0), Math.max(64, (h * dpr * bs) | 0));
  bloom.enabled = TIERS[tier][1] && !LAB.nobloom;
  camera.aspect = w / h;
  updateViewOffset();
  const sc = (h * dpr) / (2 * Math.tan((camera.fov * Math.PI) / 360));
  nodeMat.uniforms.uScale.value = sc; partMat.uniforms.uScale.value = sc; dustMat.uniforms.uScale.value = sc;
  S.dpr = dpr;
}

// ---------------------------------------------------------------- labels (no truncation, never on a panel or another label)
const labelPool = [];
const labelSize = new Map(); // class|text|maxWidth -> [w, h]: no layout reads per frame
function panelRects() {
  return [...document.querySelectorAll("[data-panel]:not([data-panel=graph])")].map((el) => el.getBoundingClientRect()).filter((r) => r.width);
}
function project(n) {
  tmpV.set(n.x, n.y, n.z).project(camera);
  if (tmpV.z > 1) return null;
  return { x: (tmpV.x * 0.5 + 0.5) * innerWidth, y: (-tmpV.y * 0.5 + 0.5) * innerHeight, depth: camera.position.distanceTo(tmpV.set(n.x, n.y, n.z)) };
}
function discRadius(n, p) {   // what the eye reads as the node: its outer ring, sized exactly as the vertex shader sizes the sprite
  const blur = n.kind > 1 ? 0 : Math.min(1, Math.abs(p.depth - S.focusDist) / Math.max(1, S.focusDist) * 1.15);
  const px = Math.max(0, n.sz.x) * (n.work ? 1.35 * 1.1 : 1) * (1 + blur * 0.55) * nodeMat.uniforms.uScale.value / Math.max(1, p.depth);
  return Math.max(6, Math.min(340, px) / (S.dpr || 1) * 0.5);
}
const hits = (q, bx, by, bw, bh) => bx < q[0] + q[2] && q[0] < bx + bw && by < q[1] + q[3] && q[1] < by + bh;
function writeLabels() {
  const f = freeArea(), placed = [], discs = [];
  // a label never sits on another label or on another agent's node: every agent disc is an obstacle
  for (const n of S.nodes) if (n.kind >= 1) { const p = (n.screen = project(n)); if (p) { const r = Math.min(64, discRadius(n, p) * 0.8); discs.push([p.x - r, p.y - r, 2 * r, 2 * r, n]); } }
  const want = S.nodes.filter((n) => n.kind === 1 || n.id === S.selected || n.id === S.hover)
    .sort((a, b) => (b.id === S.selected) - (a.id === S.selected) || (b.id === S.hover) - (a.id === S.hover) || (!!b.work - !!a.work) || (!!b.ask - !!a.ask) || Math.abs(b.val) - Math.abs(a.val));
  let k = 0;
  for (const n of want) {
    const p = project(n);
    n.screen = p;
    if (!p) continue;
    const txt = n.kind === 1 ? n.label + "  " + fmt(n.val) + (n.work ? "  · working" + (n.wn > 1 ? " ×" + n.wn : "") : n.ask ? "  · asks" : "") : fmt(n.val) + "  " + n.title;
    if (n.kind === 0 && n.id !== S.selected) continue;            // hover text goes to the tooltip box
    let el = labelPool[k];
    if (!el) { el = document.createElement("div"); labelsEl.appendChild(el); labelPool.push(el); }
    const cls = "lbl" + (n.kind === 1 ? " hub" : " ev") + (n.work ? " work" : "") + (n.id === S.selected ? " sel" : "") + (S.selected && n.hlTo < 0.5 ? " dim" : "");
    if (el.className !== cls) el.className = cls;
    if (el.textContent !== txt) el.textContent = txt;
    if (el.style.display) el.style.display = "";
    const color = n.kind === 1 ? n.color : "";
    if (el._color !== color) { el.style.color = color; el._color = color; }
    const prio = n.id === S.selected || n.work || n.ask;
    const mw = prio ? Math.max(120, Math.min(f.w - 24, n.kind === 1 ? 9999 : 380)) + "px" : "";
    if (el._mw !== mw) { el.style.maxWidth = mw; el.style.whiteSpace = prio && n.kind === 1 ? "normal" : ""; el._mw = mw; }
    const key = cls + "|" + txt + "|" + mw;
    let sz = labelSize.get(key);
    if (!sz) { sz = [el.offsetWidth, el.offsetHeight]; labelSize.set(key, sz); if (labelSize.size > 600) labelSize.clear(); }
    const lw = sz[0], lh = sz[1];
    if (n.kind === 0 && lh > f.h * 0.3) { el.style.display = "none"; el._tf = ""; continue; }   // long event text: Detail shows it
    const r = n.kind === 1 ? discRadius(n, p) : Math.max(6, (n.sz.x * nodeMat.uniforms.uScale.value) / Math.max(1, p.depth) / (S.dpr || 1) * 0.35);
    let ok = false, x = 0, y = p.y - lh / 2;
    const cx = Math.min(f.x + f.w - 6 - lw, Math.max(f.x + 6, p.x - lw / 2));
    const cands = [[p.x + r + 6, p.y - lh / 2], [p.x - r - 6 - lw, p.y - lh / 2], [cx, p.y + r + 5], [cx, p.y - r - 5 - lh]];
    if (prio) {                                                     // working / selected / asking: also try the area's edge
      const cy = Math.min(f.y + f.h - 6 - lh, Math.max(f.y + 6, p.y + r + 5));
      cands.push([cx, cy]);
    }
    for (let pass = 0; pass < (prio ? 2 : 1) && !ok; pass++) {      // pass 2 (priority labels only): other nodes may be covered, labels never
      for (const cand of cands) {
        x = cand[0]; y = cand[1];
        const bx = x, by = y, bw = lw, bh = lh;
        if (bx < f.x + 4 || by < f.y + 4 || bx + bw > f.x + f.w - 4 || by + bh > f.y + f.h - 4) continue;
        if (placed.some((q) => hits(q, bx, by, bw, bh))) continue;
        if (pass === 0 && discs.some((q) => q[4] !== n && q[4] !== n.agent && hits(q, bx, by, bw, bh))) continue;
        ok = true; break;
      }
    }
    if (!ok) { el.style.display = "none"; el._tf = ""; continue; }
    placed.push([x - 9, y - 3, lw + 18, lh + 6]);
    const tf = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
    if (el._tf !== tf) { el.style.transform = tf; el._tf = tf; }
    k++;
  }
  for (let j = k; j < labelPool.length; j++) if (labelPool[j].style.display !== "none") { labelPool[j].style.display = "none"; labelPool[j]._tf = ""; }
  // screen positions for picking (all nodes)
  for (const n of S.nodes) if (n.kind === 0 || n.kind === 2) n.screen = project(n);
}

// ---------------------------------------------------------------- render loop + scheduler
let rafId = 0, activeUntil = 0, lastT = 0, lastDraw = 0, renders = 0, fpsT = 0, fpsN = 0, lowW = 0, highW = 0;
let visible = !document.hidden, lost = false, lastMode = "stopped";
const stats = { renders: 0, mode: "stopped", fps: 0, frameMs: 0 };
const running = () => !!rafId;
function canAnimate() { return visible && !document.hidden && !lost; }   // focus does not matter
function kick(ms) {
  activeUntil = Math.max(activeUntil, performance.now() + (ms || 1200));
  schedule();
}
function schedule() {
  if (!S.model || !canAnimate()) { stopLoop(); return; }
  if (!rafId) rafId = requestAnimationFrame(tick);
}
function stopLoop() { if (rafId) cancelAnimationFrame(rafId); rafId = 0; lastMode = "stopped"; lastT = 0; }
function tick() {
  rafId = 0;
  const now = performance.now();
  const active = now < activeUntil || S.busy;
  if (!active && REDUCED) { lastMode = "still"; return; }       // reduced motion: draw on change only
  const mode = active ? "active" : "ambient";
  if (now - lastDraw >= (active ? 0 : 1000 / AMBIENT_FPS) - 4) {
    lastMode = mode; lastDraw = now;
    const f0 = performance.now();
    frame(active);
    stats.frameMs = Math.round((stats.frameMs * 0.9 + (performance.now() - f0) * 0.1) * 100) / 100;
  }
  schedule();
}
function frame(isRaf) {
  const ts = performance.now(), t = ts / 1000;
  if (renders === 0 && S.bootT) {                // window was hidden at load: start the boot animation now
    const off = t - S.bootT; S.bootT = 0;
    const sp = nodePts.geometry.attributes.aSpawn.array;
    for (const n of S.nodes) if (n.spawn > -50) { n.spawn += off; sp[n.i] = n.spawn; }
    nodePts.geometry.attributes.aSpawn.needsUpdate = true;
  }
  const dt = lastT ? Math.min(0.05, (ts - lastT) / 1000) : 1 / 60;
  lastT = ts;
  let busy = writeScene(t, dt);
  busy = stepCam(dt) || busy;
  // slow drift: orbit the camera around its target when nothing else drives it
  if (!cam.active && lastMode === "ambient" && !REDUCED && !S.dragging) {
    const ang = dt * 0.0367; // autoRotateSpeed 0.35
    tmpV.copy(camera.position).sub(controls.target).applyAxisAngle(THREE.Object3D.DEFAULT_UP, ang);
    camera.position.copy(controls.target).add(tmpV);
  }
  const ctrlMoved = controls.update();             // during the ambient drift the rotation is ours, not user damping
  if (ctrlMoved && lastMode === "active") busy = true;
  const spawnBusy = S.nodes.some((n) => t - n.spawn < 1.2 && t - n.spawn > -3) || S.nodes.some((n) => t - n.changed < 2.5 && t - n.changed > -1);
  S.busy = busy || spawnBusy;
  S.focusDist = camera.position.distanceTo(controls.target);
  nodeMat.uniforms.uFocus.value = S.focusDist; dustMat.uniforms.uFocus.value = S.focusDist;
  nodeMat.uniforms.uTime.value = t; linkMat.uniforms.uTime.value = t; dustMat.uniforms.uTime.value = t;
  linkMat.uniforms.uFlow.value = REDUCED ? 0.2 : tier === 0 ? 0.4 : 1;
  dust.rotation.y = t * 0.006;
  sky.position.copy(camera.position);
  composer.render();
  if (window.__cbBeat) window.__cbBeat(ts);       // the small "working" dots pulse on this frame: no extra compositor frames
  renders++;
  stats.renders = renders;
  writeLabels();
  if (isRaf) {
    fpsN++;
    if (!fpsT) fpsT = ts;
    const el = ts - fpsT;
    if (el >= 2000) {
      const fps = (fpsN * 1000) / el; fpsN = 0; fpsT = ts; stats.fps = Math.round(fps * 10) / 10;
      if (fps < 50 && tier > 0) { if (++lowW >= 2) { tier--; downgrades++; lowW = 0; applySize(); } }
      else if (fps > 58.5 && tier < tierStart && downgrades < 3) { if (++highW >= 4) { tier++; highW = 0; applySize(); } }
      else lowW = 0;
    }
  } else { fpsN = 0; fpsT = 0; }
}
function renderOnce(snap) {
  if (!S.model || document.hidden || lost) { S.dirty = true; return; }
  if (snap) {
    for (const n of S.nodes) { for (const s of [n.px, n.py, n.pz, n.sz]) if (s) { s.x = s.t; s.v = 0; } n.hl = n.hlTo; n.spawn = Math.min(n.spawn, -100); }
    if (S.laCur) S.laCur.set(S.laTo);
    if (cam.active) { for (const s of [cam.tx, cam.ty, cam.tz, cam.d]) s.x = s.t; stepCam(0); cam.active = false; }
    if (nodePts) nodePts.geometry.attributes.aSpawn.array.fill(-100), (nodePts.geometry.attributes.aSpawn.needsUpdate = true);
  }
  lastT = 0;
  frame(false);
  S.dirty = false;
}

// ---------------------------------------------------------------- input
let down = null;
canvas.addEventListener("pointerdown", (e) => { down = { x: e.clientX, y: e.clientY, t: performance.now() }; S.dragging = true; cam.active = false; kick(1500); });
addEventListener("pointerup", (e) => {
  S.dragging = false;
  if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5 && e.target === canvas) {
    const n = pick(e.clientX, e.clientY);
    if (n && n.kind !== 2) window.__cbSelect && window.__cbSelect(n.id);
  }
  down = null; kick(1500);
});
canvas.addEventListener("dblclick", (e) => { if (!pick(e.clientX, e.clientY)) { window.__cbSelect && window.__cbSelect(null); frameOverview(false); kick(1500); } });
canvas.addEventListener("wheel", () => { cam.active = false; kick(1200); }, { passive: true });
controls.addEventListener("start", () => { cam.active = false; kick(1500); });
let hoverQueued = false;
canvas.addEventListener("pointermove", (e) => {
  if (S.dragging) return;
  if (hoverQueued) return; hoverQueued = true;
  requestAnimationFrame(() => {
    hoverQueued = false;
    const n = pick(e.clientX, e.clientY);
    const id = n && n.kind !== 2 ? n.id : null;
    canvas.style.cursor = id ? "pointer" : "grab";
    if (id !== S.hover) { S.hover = id; updateHighlight(); showTip(n, e.clientX, e.clientY); kick(500); }
    else if (id) showTip(n, e.clientX, e.clientY);
  });
});
canvas.addEventListener("pointerleave", () => { if (S.hover) { S.hover = null; updateHighlight(); showTip(null); kick(400); } });
function pick(x, y) {
  let best = null, bd = Infinity;
  for (const n of S.nodes) {
    const p = n.screen || (n.screen = project(n));
    if (!p) continue;
    const disc = (Math.max(0, n.sz.x) * nodeMat.uniforms.uScale.value) / Math.max(1, p.depth) / (S.dpr || 1);
    const r = n.kind === 1 ? Math.max(14, disc * 0.45) : Math.max(9, disc * 0.32);   // agents: hit area = visible glow
    const d = Math.hypot(p.x - x, p.y - y);
    if (d >= r) continue;
    const score = (n.kind === 1 ? 0 : 1e4) + d;            // agents beat passing events; among agents the nearest centre wins
    if (score < bd) { bd = score; best = n; }
  }
  return best;
}
function showTip(n, x, y) {
  if (!tipEl) return;
  if (!n || n.kind === 2) { tipEl.hidden = true; return; }
  tipEl.textContent = n.kind === 1 ? `${n.label} · ${fmt(n.val)} points · ${n.count} event${n.count === 1 ? "" : "s"}` : `${fmt(n.val)} · ${n.agent.label} · ${n.title}`;
  tipEl.hidden = false;
  const f = freeArea(), w = tipEl.offsetWidth, h = tipEl.offsetHeight;
  tipEl.style.transform = `translate(${Math.min(f.x + f.w - w - 8, Math.max(f.x + 8, x + 14)).toFixed(0)}px, ${Math.min(f.y + f.h - h - 8, Math.max(f.y + 8, y + 16)).toFixed(0)}px)`;
}

// visibility / focus
// focus/blur deliberately ignored: the window keeps moving while the owner works in another one
document.addEventListener("visibilitychange", () => {
  visible = !document.hidden;
  if (!visible) { stopLoop(); return; }
  if (S.dirty && renders > 0) renderOnce(true); // first show keeps the boot animation instead of snapping
  kick(renders ? 600 : 3200);
});
canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); lost = true; stopLoop(); }, false);
canvas.addEventListener("webglcontextrestored", () => { lost = false; applySize(); renderOnce(true); kick(600); }, false);
let resizeRaf = 0;
addEventListener("resize", () => {
  applySize();
  if (!resizeRaf) resizeRaf = requestAnimationFrame(() => { resizeRaf = 0; renderOnce(false); kick(300); });
  renderOnce(false); // repaint now: no stretched or blank frame while resizing
});

applySize();
window.CBScene = {
  ok: true,
  setData,
  select(id) { applySelection(id, true); },
  overview() { applySelection(null, false); frameOverview(false); kick(1500); },
  setVisible(f) { visible = !!f && !document.hidden; if (!visible) stopLoop(); else { if (S.dirty) renderOnce(true); kick(600); } },
  working() { return S.nodes.filter((n) => n.work).map((n) => n.id); },
  asking() { return S.nodes.filter((n) => n.ask).map((n) => n.id); },
  flows() {   // which links carry moving light right now, and why (for the gate)
    if (!linkSeg) return [];
    const lf = linkSeg.geometry.attributes.aFlow.array;
    return S.links.map(([a, b, k], i) => ({ to: b.id, kind: k, flow: Math.round(lf[i * 2] * 100) / 100 })).filter((x) => x.flow !== 0);
  },
  getView() { return { t: controls.target.toArray(), p: camera.position.toArray() }; },
  setView(v) { if (!v || !v.t || !v.p) return; cam.active = false; controls.target.fromArray(v.t); camera.position.fromArray(v.p); controls.update(); renderOnce(true); },
  nodeInfo(id) { const n = S.byId.get(id); return n && { kind: n.kind, fresh: !!n.fresh, spawn: n.spawn, changed: n.changed, now: nowS(), agent: n.agent && n.agent.id }; },
  pulsing() { const t = nowS(); return S.nodes.filter((n) => n.kind === 1 && t - n.changed >= 0 && t - n.changed < 6).map((n) => n.id); },
  setFocused() {},                                   // kept for older callers; focus no longer changes anything
  stats() {
    const gl = renderer.getContext(), ext = gl.getExtension("WEBGL_debug_renderer_info");
    return { ok: true, renders, mode: lastMode, running: running(), fps: stats.fps, frameMs: stats.frameMs, tier, dpr: S.dpr, nodes: S.nodes.length,
             links: S.links.length, selected: S.selected, focusDist: Math.round(S.focusDist),
             target: controls.target.toArray().map(Math.round), camera: camera.position.toArray().map(Math.round),
             renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "unknown" };
  },
  project(id) { const n = S.byId.get(id); if (!n) return null; const p = project(n); return p && { x: p.x, y: p.y }; },
  labels() { return labelPool.filter((l) => l.style.display !== "none").map((l) => { const r = l.getBoundingClientRect(); return { text: l.textContent, x: r.left, y: r.top, w: r.width, h: r.height }; }); },
  renderNow() { renderOnce(true); },
};
window.dispatchEvent(new Event("cbscene-ready"));
}
