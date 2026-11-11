// Tiny timeline for the tutorial videos.
// Every effect is a Web Animation (or a handler) placed at a time in seconds, so the
// render script can jump to any frame with seek(t). Open the page normally to preview in real time.

const T = {
  handlers: [],               // functions f(t) run on every seek (typing, captions, counters)
  duration: 60,
};

// Animate `el` from time `t` for `dur` seconds. Keyframes as in element.animate().
function at(el, t, dur, keyframes, easing = "cubic-bezier(.22,.8,.3,1)") {
  el = typeof el === "string" ? document.querySelector(el) : el;
  if (!el) throw new Error("no element");
  el.animate(keyframes, { delay: t * 1000, duration: dur * 1000, fill: "both", easing });
}

// Show (fade + rise) and hide helpers.
function show(el, t, dur = 0.5, dy = 14) {
  at(el, t, dur, [{ opacity: 0, transform: `translateY(${dy}px)` }, { opacity: 1, transform: "none" }]);
}
function pop(el, t, dur = 0.45) {
  at(el, t, dur, [{ opacity: 0, transform: "scale(.85)" }, { opacity: 1, transform: "scale(1.04)", offset: 0.7 },
                  { opacity: 1, transform: "scale(1)" }]);
}
function hide(el, t, dur = 0.4) {
  at(el, t, dur, [{ opacity: 1 }, { opacity: 0 }], "ease");
}

// Type `text` into el between t and t + text.length / cps.
function typeText(el, text, t, cps = 22) {
  el = typeof el === "string" ? document.querySelector(el) : el;
  el.textContent = "";
  T.handlers.push((now) => {
    const n = Math.max(0, Math.min(text.length, Math.floor((now - t) * cps)));
    el.textContent = text.slice(0, n);
    el.classList.toggle("typing", now >= t && n < text.length);
  });
  return t + text.length / cps;
}

// Count a number up (e.g. summary cards).
function countUp(el, to, t, dur = 1, fmt = (v) => Math.round(v)) {
  el = typeof el === "string" ? document.querySelector(el) : el;
  T.handlers.push((now) => {
    const k = Math.max(0, Math.min(1, (now - t) / dur));
    el.textContent = fmt(to * (1 - Math.pow(1 - k, 3)));
  });
}

// Captions: [[start, end, html], ...] shown in the caption bar.
function captions(list) {
  const box = document.querySelector("#caption");
  const inner = box.querySelector("span");
  T.handlers.push((now) => {
    const c = list.find(([a, b]) => now >= a && now < b);
    inner.innerHTML = c ? c[2] : "";
    const k = c ? Math.min(1, (now - c[0]) / 0.35, (c[1] - now) / 0.35) : 0;
    box.style.opacity = Math.max(0, k);
    box.style.transform = `translate(-50%, ${(1 - Math.max(0, k)) * 12}px)`;
  });
}

// Step badge (top-left): [[start, end, "1", "Tulis pembayang"], ...]
function steps(list) {
  const box = document.querySelector("#step");
  T.handlers.push((now) => {
    const s = list.find(([a, b]) => now >= a && now < b);
    box.style.opacity = s ? 1 : 0;
    if (s) box.innerHTML = `<b>${s[2]}</b><span>${s[3]}</span>`;
  });
}

// Box of an element (or of several, joined) on the stage, as it looks right now.
function box(sel) {
  const els = [...document.querySelectorAll(sel)];
  const r = els.map((e) => e.getBoundingClientRect());
  const x = Math.min(...r.map((q) => q.left)), y = Math.min(...r.map((q) => q.top));
  return [x, y, Math.max(...r.map((q) => q.right)) - x, Math.max(...r.map((q) => q.bottom)) - y];
}

// Mouse cursor: path = [[t, target, click?], ...]; target is a selector (aims a little left of its
// centre, like a hand on a text box) or [x, y] in stage pixels.
function cursor(path) {
  const c = document.querySelector("#cursor");
  const ring = document.querySelector("#click");
  const ease = (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);
  const where = (p) => {
    if (Array.isArray(p[1])) return p[1];
    const [x, y, w, h] = box(p[1]);
    return [x + Math.min(w / 2, 90), y + h / 2];
  };
  T.handlers.push((now) => {
    let i = path.findIndex((p) => p[0] > now);
    if (i === -1) i = path.length;
    const a = path[Math.max(0, i - 1)], b = path[Math.min(path.length - 1, i)];
    const [ax, ay] = where(a), [bx, by] = where(b);
    const k = b[0] === a[0] ? 1 : ease(Math.max(0, Math.min(1, (now - a[0]) / Math.min(0.9, b[0] - a[0]))));
    const x = ax + (bx - ax) * k, y = ay + (by - ay) * k;
    c.style.transform = `translate(${x}px, ${y}px)`;
    c.style.opacity = now < path[0][0] ? 0 : 1;
    const clickAt = path.filter((p) => p[2] && p[0] <= now).pop();
    const since = clickAt ? now - clickAt[0] : 9;
    const [cx, cy] = clickAt ? where(clickAt) : [0, 0];
    ring.style.opacity = since < 0.5 ? 1 - since / 0.5 : 0;
    ring.style.transform = `translate(${cx}px, ${cy}px) scale(${0.4 + since * 2})`;
    c.querySelector("svg").style.transform = since < 0.15 ? "scale(.85)" : "scale(1)";
  });
}

// Spotlight ring around elements: [[start, end, selector], ...]. Glides between back-to-back items.
function spotlight(list) {
  const s = document.querySelector("#spot");
  T.handlers.push((now) => {
    const i = list.findIndex(([a, b]) => now >= a && now < b);
    if (i < 0) { s.style.opacity = 0; return; }
    const [a, b, sel] = list[i];
    const to = box(sel);
    const prev = list[i - 1] && Math.abs(list[i - 1][1] - a) < 0.05 ? box(list[i - 1][2]) : null;
    const k = prev ? 1 - Math.pow(1 - Math.min(1, (now - a) / 0.5), 3) : 1;
    const [X, Y, W, H] = to.map((v, j) => (prev ? prev[j] + (v - prev[j]) * k : v));
    s.style.left = X - 8 + "px"; s.style.top = Y - 8 + "px";
    s.style.width = W + 16 + "px"; s.style.height = H + 16 + "px";
    const fadeIn = prev ? 1 : Math.min(1, (now - a) / 0.3);
    const next = list[i + 1] && Math.abs(list[i + 1][0] - b) < 0.05;
    s.style.opacity = Math.min(fadeIn, next ? 1 : (b - now) / 0.3);
  });
}

// Fill a CSS ring (conic gradient) to `frac` between t and t + dur.
function ring(el, frac, colour, t, dur = 1.2) {
  el = typeof el === "string" ? document.querySelector(el) : el;
  T.handlers.push((now) => {
    const k = Math.max(0, Math.min(1, (now - t) / dur));
    const deg = 360 * frac * (1 - Math.pow(1 - k, 3));
    el.style.background = `conic-gradient(${colour} ${deg}deg, #E6E1D6 0)`;
  });
}

// Toggle a class between two times (e.g. pressed buttons, selected rows).
function classBetween(el, cls, t0, t1 = 1e9) {
  el = typeof el === "string" ? document.querySelector(el) : el;
  T.handlers.push((now) => el.classList.toggle(cls, now >= t0 && now < t1));
}

// Jump to time t (seconds). Used by the renderer, and by the preview loop.
function seek(t) {
  for (const a of document.getAnimations()) {
    a.pause();
    a.currentTime = t * 1000;
  }
  for (const h of T.handlers) h(t);
  const bar = document.querySelector("#progress i");
  if (bar) bar.style.width = (100 * t) / T.duration + "%";
}
window.seek = seek;

// Preview in real time when opened normally (the renderer adds ?render).
function start(duration) {
  T.duration = duration;
  window.DURATION = duration;
  document.fonts.ready.then(() => {
    window.READY = true;
    seek(0);
    if (location.search.includes("render")) return;
    const t0 = performance.now();
    const loop = () => {
      const t = ((performance.now() - t0) / 1000) % (duration + 1);
      seek(t);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  });
}
