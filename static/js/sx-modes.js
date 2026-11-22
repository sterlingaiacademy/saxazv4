/* Dark mode helper: keep brand colours true.
   The page is colour-inverted in dark mode (see saxaz-modes.css). That turns white surfaces dark and
   dark text light, which is what we want, but it would also turn the black header into light grey
   and the saxaz yellow into brown. This marks every element whose own background is near-black or a
   strong colour (yellow, green, red, blue...) with data-sx-keep, which flips it back to its real colour.
   Only the outermost such element is marked, so nothing is flipped twice. */
(function () {
  var KEEP = 'data-sx-keep';
  var pending = new Set();
  var fullPending = false;
  var timer = null;

  function isDark() { return document.documentElement.getAttribute('data-sx-mode') === 'dark'; }

  // returns null (transparent-ish) or { l: lightness, s: saturation }
  function hsl(c) {
    var m = /rgba?\(([^)]+)\)/.exec(c || '');
    if (!m) return null;
    var p = m[1].split(',').map(function (x) { return parseFloat(x); });
    var a = p.length > 3 ? p[3] : 1;
    if (!(a >= 0.6)) return null;
    var r = p[0] / 255, g = p[1] / 255, b = p[2] / 255;
    var max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
    var s = max === min ? 0 : (l > 0.5 ? (max - min) / (2 - max - min) : (max - min) / (max + min));
    return { l: l, s: s };
  }
  function strong(h) { return !!h && h.s > 0.45 && h.l > 0.22 && h.l < 0.82; }   // yellow, green, red, blue...
  function keepColour(bg) {
    var h = hsl(bg);
    if (!h) return false;
    return h.l < 0.2 || strong(h);                  // saxaz black bars / buttons, or a strong colour
  }

  function decide(el) {
    if (el === document.body || el === document.documentElement) return;
    var anc = el.parentElement && el.parentElement.closest('[' + KEEP + ']');
    var want = false;
    if (!anc) {
      var cs = window.getComputedStyle(el);
      // data-sx-paper: always shown in its real light colours (the scratchpad, so ink matches the chosen colour)
      want = el.hasAttribute('data-sx-paper') || keepColour(cs.backgroundColor);
      // Coloured text / icons with no box of their own (e.g. red "Not quite", gold titles, coloured icons)
      if (!want && el.childElementCount === 0 && !hsl(cs.backgroundColor) && strong(hsl(cs.color))) want = true;
      if (!want && el.tagName === 'svg' && !hsl(cs.backgroundColor)) {
        if (strong(hsl(cs.color))) want = true;
        else {
          // drawings / progress rings coloured on their shapes (stroke or fill), not via text colour
          var shapes = el.querySelectorAll('circle, path, rect, line, polyline, polygon, ellipse');
          for (var k = 0; k < shapes.length && k < 40; k++) {
            var ss = window.getComputedStyle(shapes[k]);
            if (strong(hsl(ss.stroke)) || strong(hsl(ss.fill))) { want = true; break; }
          }
        }
      }
    }
    if (want) { if (!el.hasAttribute(KEEP)) el.setAttribute(KEEP, ''); }
    else if (el.hasAttribute(KEEP)) el.removeAttribute(KEEP);
  }

  function processTree(root) {
    if (!root || root.nodeType !== 1 || !root.isConnected) return;
    decide(root);
    var all = root.getElementsByTagName('*');
    for (var i = 0; i < all.length; i++) decide(all[i]);
  }

  function clearAll() {
    var marked = document.querySelectorAll('[' + KEEP + ']');
    for (var i = 0; i < marked.length; i++) marked[i].removeAttribute(KEEP);
  }

  function flush() {
    timer = null;
    if (!isDark()) { pending.clear(); fullPending = false; return; }
    if (fullPending) { fullPending = false; pending.clear(); processTree(document.body); return; }
    var list = Array.from(pending); pending.clear();
    list.forEach(processTree);
  }

  function schedule(el) {
    if (el) pending.add(el); else fullPending = true;
    if (!timer) timer = setTimeout(flush, 120);
  }

  var obs = new MutationObserver(function (muts) {
    if (!isDark()) return;
    for (var i = 0; i < muts.length; i++) {
      var mu = muts[i];
      if (mu.type === 'attributes') {
        if (mu.attributeName === KEEP) continue;
        schedule(mu.target);
      } else {
        for (var j = 0; j < mu.addedNodes.length; j++) {
          if (mu.addedNodes[j].nodeType === 1) schedule(mu.addedNodes[j]);
        }
      }
    }
  });

  function start() {
    obs.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'style', 'open', 'hidden'] });
    document.addEventListener('transitionend', function (e) { if (isDark() && e.target && e.target.nodeType === 1) schedule(e.target); }, true);
    if (isDark()) schedule(null);
  }

  window.addEventListener('sx-mode-change', function () {
    if (isDark()) schedule(null); else clearAll();
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
  window.addEventListener('load', function () { if (isDark()) schedule(null); });
})();
