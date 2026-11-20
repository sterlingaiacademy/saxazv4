/* ==========================================================================
   SAXAZ Summary Games v6: Simple, Intuitive Full-Screen 3D Drag-and-Drop Engine
   ========================================================================== */
(function () {
  var ASSET_V = '22';
  var TOK_FILES = {
    co2: 'tok_co2',
    h2o: 'tok_h2o',
    o2: 'tok_o2',
    light: 'tok_sunlight',
    glucose: 'tok_glucose',
    urea: 'tok_urea',
    nacl: 'tok_salt',
    protein: 'tok_protein',
    rbc: 'tok_rbc',
    wbc: 'tok_wbc',
    platelet: 'tok_platelet',
    plasma: 'tok_plasma',
    germ: 'tok_germ',
    urine: 'tok_urine_drop',
    food: 'tok_food_apple',
    chyme: 'tok_food_chyme',
    waste: 'tok_food_waste'
  };

  var reduceMotion = function () {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  };

  var clamp = function (v, a, b) { return Math.max(a, Math.min(b, v)); };

  /* Gentle WebAudio Chime Feedback */
  var _audioCtx = null;
  function tone(freq, dur, type, vol, slideTo) {
    if (['0', 'off'].includes(String(window.__saxazUserTtsMode || '').toLowerCase())) return;
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      if (!_audioCtx) _audioCtx = new Ctx();
      if (_audioCtx.state === 'suspended') _audioCtx.resume().catch(function () {});
      var osc = _audioCtx.createOscillator();
      var gain = _audioCtx.createGain();
      osc.type = type || 'triangle';
      var now = _audioCtx.currentTime;
      osc.frequency.setValueAtTime(freq, now);
      if (slideTo) osc.frequency.exponentialRampToValueAtTime(Math.max(40, slideTo), now + dur);
      gain.gain.setValueAtTime(vol || 0.08, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + dur);
      osc.connect(gain);
      gain.connect(_audioCtx.destination);
      osc.start(now);
      osc.stop(now + dur + 0.01);
    } catch (e) { /* audio optional */ }
  }

  function sfx(name) {
    try {
      if (window.SFX && typeof window.SFX['play' + name] === 'function') window.SFX['play' + name]();
    } catch (e) {}
    if (name === 'Select') tone(480, 0.11, 'triangle', 0.08, 660);
    else if (name === 'Error') tone(220, 0.16, 'sawtooth', 0.06, 150);
    else if (name === 'Success') {
      [523.25, 659.25, 783.99, 1046.5].forEach(function (f, i) {
        setTimeout(function () { tone(f, 0.18, 'triangle', 0.08, f * 1.02); }, i * 75);
      });
    }
  }

  /* Sprite-Sheet Cache & Atlas Frame Renderer */
  var SHEET_CACHE = {};
  function loadSheet(url, onReady) {
    if (!url) return;
    var entry = SHEET_CACHE[url];
    if (!entry) {
      entry = { img: new Image(), loaded: false, failed: false, cbs: [] };
      SHEET_CACHE[url] = entry;
      entry.img.decoding = 'async';
      entry.img.onload = function () {
        entry.loaded = true;
        var list = entry.cbs.slice();
        entry.cbs.length = 0;
        list.forEach(function (fn) { fn(entry.img); });
      };
      entry.img.onerror = function () { entry.failed = true; entry.cbs.length = 0; };
      entry.img.src = url;
    }
    if (entry.loaded && onReady) onReady(entry.img);
    else if (!entry.failed && onReady) entry.cbs.push(onReady);
  }

  function drawAtlasCell(ctx, img, frameIdx, cols, cellW, cellH) {
    if (!ctx || !img) return;
    var c = frameIdx % cols;
    var r = Math.floor(frameIdx / cols);
    ctx.clearRect(0, 0, cellW, cellH);
    ctx.drawImage(img, c * cellW, r * cellH, cellW, cellH, 0, 0, cellW, cellH);
  }

  var mol = function (id, cls) {
    var fn = TOK_FILES[id] || ('tok_' + id);
    return '<img class="gx-mol ' + (cls || '') + '" src="/static/images/saxaz_web/games/' + fn + '.webp?v=' + ASSET_V + '" alt="" draggable="false">';
  };
  window.sxMol = mol;

  function flowAlong(layer, pts, o) {
    o = o || {};
    if (!layer || !pts || pts.length < 2) return Promise.resolve();
    var el = document.createElement('div');
    el.className = 'gx-flow ' + (o.cls || '');
    el.innerHTML = o.html || mol(o.mol || 'o2');
    layer.appendChild(el);
    var frames = pts.map(function (p, i) {
      var s = i === 0 ? 0.6 : (i === pts.length - 1 && o.fade !== false ? 0.75 : 1.06);
      return {
        left: p[0] + '%',
        top: p[1] + '%',
        transform: 'translate(-50%, -50%) scale(' + s + ')',
        opacity: (i === pts.length - 1 && o.fade !== false) ? 0.1 : 1
      };
    });
    frames[0].opacity = 0;
    var dur = (o.dur || 1200) * (reduceMotion() ? 0.4 : 1);
    var anim = el.animate(frames, { duration: dur, delay: o.delay || 0, easing: 'cubic-bezier(.34,0,.2,1)', fill: 'both' });
    return new Promise(function (resolve) {
      anim.onfinish = function () { if (!o.keep) el.remove(); resolve(el); };
    });
  }

  function popAt(layer, x, y, text, cls) {
    if (!layer) return;
    var el = document.createElement('div');
    el.className = 'gx-pop ' + (cls || '');
    el.textContent = text;
    el.style.left = clamp(x, 14, 86) + '%';
    el.style.top = clamp(y, 14, 86) + '%';
    layer.appendChild(el);
    setTimeout(function () { el.remove(); }, 1350);
  }

  /* ------------------------------------------------------------------------
     Shared Game Base + Unified Smooth Drag-and-Drop & 2-Tap Matching
     ------------------------------------------------------------------------ */
  function gameBase(id) {
    var rootEl = null;
    var stageLoopRaf = 0;
    var stageBoostUntil = 0;

    return {
      gId: id,
      gDone: false,
      gStarted: false,
      gClaimed: false,
      gVisible: false,
      gMsg: '',
      gMood: '',
      gTimers: [],
      gRaf: 0,

      gInit: function () {
        var self = this;
        rootEl = self.$root;
        var key = typeof self.gameKey === 'function' ? self.gameKey(self.gId) : '';
        self.gClaimed = !!(key && typeof self.hasClaimed === 'function' && self.hasClaimed(key));
        if (self.gSetup) self.gSetup();
        if (self.gUsesDrag) self.dragInit();
        self.initStageLoopCanvas();

        if ('IntersectionObserver' in window) {
          var io = new IntersectionObserver(function (es) {
            var vis = es[0].isIntersecting;
            if (vis === self.gVisible) return;
            self.gVisible = vis;
            self.syncStageLoop(vis);
            if (self.gOnVisible) self.gOnVisible(vis);
          }, { threshold: 0.05 });
          io.observe(rootEl);
        } else {
          self.gVisible = true;
          self.syncStageLoop(true);
          if (self.gOnVisible) self.gOnVisible(true);
        }
      },

      initStageLoopCanvas: function () {
        var self = this;
        if (!rootEl || reduceMotion()) return;
        var cvs = rootEl.querySelector('.gx-stage-canvas');
        if (!cvs) return;
        var sheetUrl = cvs.getAttribute('data-gx-sheet');
        var cols = parseInt(cvs.getAttribute('data-gx-cols') || '4', 10);
        var total = parseInt(cvs.getAttribute('data-gx-frames') || '16', 10);
        var baseFps = parseFloat(cvs.getAttribute('data-gx-fps') || '10');
        var ctx = cvs.getContext ? cvs.getContext('2d') : null;
        var stage = self.stageEl();
        if (!ctx || !sheetUrl) return;

        self._stageAnim = {
          cvs: cvs, ctx: ctx, cols: cols, total: total, baseFps: baseFps,
          img: null, pos: 0, drawn: -1, lastTs: 0, stage: stage
        };
        loadSheet(sheetUrl, function (img) {
          self._stageAnim.img = img;
          drawAtlasCell(ctx, img, 0, cols, cvs.width, cvs.height);
          self._stageAnim.drawn = 0;
          if (stage) stage.classList.add('is-sheet-live');
          self.syncStageLoop(self.gVisible);
        });
      },

      boostStage: function (ms) { stageBoostUntil = performance.now() + (ms || 1400); },

      syncStageLoop: function (vis) {
        var self = this;
        var sa = self._stageAnim;
        if (!sa || !sa.img || reduceMotion()) return;
        if (!vis) {
          if (stageLoopRaf) { cancelAnimationFrame(stageLoopRaf); stageLoopRaf = 0; }
          sa.lastTs = 0;
          return;
        }
        if (stageLoopRaf) return;
        var step = function (ts) {
          if (!self.gVisible || document.hidden) { stageLoopRaf = 0; sa.lastTs = 0; return; }
          if (!sa.lastTs) sa.lastTs = ts;
          var dt = Math.min(0.05, Math.max(0.004, (ts - sa.lastTs) / 1000));
          sa.lastTs = ts;
          var fps = ts < stageBoostUntil ? sa.baseFps * 1.9 : sa.baseFps;
          sa.pos = (sa.pos + dt * fps) % sa.total;
          var fIdx = Math.floor(sa.pos);
          if (fIdx !== sa.drawn) {
            sa.drawn = fIdx;
            drawAtlasCell(sa.ctx, sa.img, fIdx, sa.cols, sa.cvs.width, sa.cvs.height);
          }
          stageLoopRaf = requestAnimationFrame(step);
        };
        stageLoopRaf = requestAnimationFrame(step);
      },

      gRoot: function () { return rootEl; },
      fxLayer: function () { return rootEl ? rootEl.querySelector('.gx-fx') : null; },
      stageEl: function () { return rootEl ? rootEl.querySelector('.gx-stage') : null; },

      later: function (fn, ms) {
        var t = setTimeout(fn, ms);
        this.gTimers.push(t);
        return t;
      },

      clearTimers: function () {
        this.gTimers.forEach(function (t) { clearTimeout(t); });
        this.gTimers = [];
      },

      say: function (msg, mood) { this.gMsg = msg; this.gMood = mood || ''; },
      oops: function (msg) { this.say(msg, 'bad'); sfx('Error'); },

      winGame: function (msg, cheer) {
        if (this.gDone) return;
        this.gDone = true;
        this.gStarted = true;
        this.boostStage(2500);
        this.say(msg || '', 'win');
        sfx('Success');
        var st = this.stageEl() || rootEl;
        if (!reduceMotion() && window.saxazConfetti && st) {
          var r = st.getBoundingClientRect();
          window.saxazConfetti(r.left + r.width / 2, r.top + r.height / 2, 46);
        }
        this.gClaimed = true;
        if (typeof this.onGameWon === 'function') this.onGameWon(this.gId, cheer || '');
      },

      gReplay: function () {
        this.clearTimers();
        cancelAnimationFrame(this.gRaf);
        this.gDone = false;
        this.gStarted = false;
        this.say('', '');
        var fx = this.fxLayer();
        if (fx) fx.innerHTML = '';
        if (rootEl) rootEl.querySelectorAll('[data-drag]').forEach(function (n) {
          n.classList.remove('is-gone', 'is-dragging', 'is-sel', 'is-snapping');
          n.style.removeProperty('display');
          n.style.removeProperty('--dx');
          n.style.removeProperty('--dy');
        });
        if (this.gSetup) this.gSetup();
        if (this.gOnVisible) this.gOnVisible(this.gVisible);
      },

      dragInit: function () {
        var self = this;
        var root = rootEl;
        var picked = null;

        var zoneAt = function (x, y) {
          var zs = root.querySelectorAll('[data-drop]');
          var best = null, bestDist = Infinity;
          for (var i = 0; i < zs.length; i++) {
            var r = zs[i].getBoundingClientRect();
            if (!r.width) continue;
            var pad = 16;
            if (x >= r.left - pad && x <= r.right + pad && y >= r.top - pad && y <= r.bottom + pad) {
              var cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
              var d = Math.hypot(x - cx, y - cy);
              if (d < bestDist) { bestDist = d; best = zs[i]; }
            }
          }
          return best;
        };

        var clearOver = function () {
          root.querySelectorAll('[data-drop].is-over').forEach(function (z) { z.classList.remove('is-over'); });
        };

        var settle = function (el, zoneEl, accepted) {
          el.classList.remove('is-dragging');
          el.style.removeProperty('--ds');
          el.classList.add('is-snapping');
          if (accepted && zoneEl) {
            var er = el.getBoundingClientRect();
            var zr = zoneEl.getBoundingClientRect();
            var cx = parseFloat(el.style.getPropertyValue('--dx')) || 0;
            var cy = parseFloat(el.style.getPropertyValue('--dy')) || 0;
            el.style.setProperty('--dx', (cx + (zr.left + zr.width / 2) - (er.left + er.width / 2)) + 'px');
            el.style.setProperty('--dy', (cy + (zr.top + zr.height / 2) - (er.top + er.height / 2)) + 'px');
            setTimeout(function () { el.classList.add('is-gone'); el.classList.remove('is-snapping'); }, 220);
            setTimeout(function () { if (el.classList.contains('is-gone')) el.style.display = 'none'; }, 520);
          } else {
            el.style.setProperty('--dx', '0px');
            el.style.setProperty('--dy', '0px');
            setTimeout(function () { el.classList.remove('is-snapping'); }, 380);
          }
        };

        var drop = function (el, zoneEl) {
          self.gStarted = true;
          var ok = !!(zoneEl && typeof self.onDropToken === 'function' &&
            self.onDropToken(el.getAttribute('data-drag'), zoneEl.getAttribute('data-drop'), el, zoneEl));
          if (zoneEl) {
            var cls = ok ? 'is-accept' : 'is-reject';
            zoneEl.classList.add(cls);
            setTimeout(function () { zoneEl.classList.remove(cls); }, ok ? 650 : 420);
          }
          if (ok) self.boostStage(1300);
          settle(el, zoneEl, ok);
        };

        root.addEventListener('pointerdown', function (e) {
          var el = e.target.closest('[data-drag]');
          if (!el || !root.contains(el) || el.classList.contains('is-gone') || self.gDone) return;
          e.preventDefault();
          try { el.setPointerCapture(e.pointerId); } catch (err) {}
          var sx = e.clientX, sy = e.clientY, moved = false;
          el.classList.remove('is-snapping');
          el.classList.add('is-dragging');
          el.style.setProperty('--ds', '1.08');
          var move = function (ev) {
            var dx = ev.clientX - sx, dy = ev.clientY - sy;
            if (!moved && Math.abs(dx) + Math.abs(dy) > 6) moved = true;
            el.style.setProperty('--dx', dx + 'px');
            el.style.setProperty('--dy', dy + 'px');
            clearOver();
            var z = zoneAt(ev.clientX, ev.clientY);
            if (z) z.classList.add('is-over');
          };
          var up = function (ev) {
            el.removeEventListener('pointermove', move);
            el.removeEventListener('pointerup', up);
            el.removeEventListener('pointercancel', up);
            clearOver();
            if (!moved) {
              settle(el, null, false);
              if (picked && picked !== el) picked.classList.remove('is-sel');
              picked = picked === el ? null : el;
              el.classList.toggle('is-sel', !!picked);
              if (picked) self.say('Card selected! Now tap the matching glowing spot on the 3D diagram.', 'hint');
              return;
            }
            drop(el, ev.type === 'pointercancel' ? null : zoneAt(ev.clientX, ev.clientY));
          };
          el.addEventListener('pointermove', move);
          el.addEventListener('pointerup', up);
          el.addEventListener('pointercancel', up);
        });

        root.addEventListener('click', function (e) {
          var z = e.target.closest('[data-drop]');
          if (!z || !picked) return;
          var el = picked;
          picked = null;
          el.classList.remove('is-sel');
          drop(el, z);
        });
      }
    };
  }


  /* ========================================================================
     1. LEAF: Simple Photosynthesis Drag & Drop
     ======================================================================== */
  window.sxGameLeaf = function () {
    return Object.assign(gameBase('leaf'), {
      gUsesDrag: true,
      lfCo2: 0,
      lfH2o: 0,
      lfSun: false,

      gSetup: function () {
        this.lfCo2 = 0;
        this.lfH2o = 0;
        this.lfSun = false;
      },

      lfGoal: function () {
        if (this.gDone) return 'Photosynthesis complete! Sunlight + Carbon Dioxide + Water made Glucose and Oxygen!';
        return 'Drag Sunlight onto Chloroplasts (top), 2 CO2 into Stoma Pore (bottom), and 2 Water into Xylem Pipe (right)!';
      },

      onDropToken: function (id, zone) {
        var self = this;
        var fx = self.fxLayer();
        if (id === 'o2') {
          self.oops('Leaves release Oxygen at the end — drag Sunlight, CO2, and Water into the leaf!');
          return false;
        }
        if (id === 'light') {
          if (zone !== 'palisade') { self.oops('Drop Sunlight onto the green Chloroplasts at the top of the leaf!'); return false; }
          self.lfSun = true;
          sfx('Select');
          popAt(fx, 42, 26, 'Sunlight Captured!', 'is-gold');
          self.say('Chlorophyll captured the Sunlight energy!', 'good');
          self.lfCheckWin();
          return true;
        }
        if (id === 'co2') {
          if (zone !== 'stoma') { self.oops('Carbon dioxide enters from air through the Stoma Pore at the bottom!'); return false; }
          self.lfCo2 += 1;
          sfx('Select');
          flowAlong(fx, [[43, 88], [43, 60], [43, 36]], { mol: 'co2', dur: 1100 });
          popAt(fx, 43, 66, '+CO2 Inside!', 'is-green');
          self.say('CO2 entered through the Stoma Pore!', 'good');
          self.lfCheckWin();
          return true;
        }
        if (id === 'h2o') {
          if (zone !== 'xylem') { self.oops('Water travels from roots through the blue Xylem Pipe on the right!'); return false; }
          self.lfH2o += 1;
          sfx('Select');
          flowAlong(fx, [[84, 58], [66, 46], [48, 35]], { mol: 'h2o', dur: 1100 });
          popAt(fx, 78, 48, '+Water Inside!', 'is-blue');
          self.say('Water flowed in from the Xylem Pipe!', 'good');
          self.lfCheckWin();
          return true;
        }
        return false;
      },

      lfCheckWin: function () {
        var self = this;
        if (self.lfSun && self.lfCo2 >= 2 && self.lfH2o >= 2 && !self.gDone) {
          var fx = self.fxLayer();
          flowAlong(fx, [[45, 34], [68, 38], [86, 42]], { mol: 'glucose', dur: 1350, fade: false });
          flowAlong(fx, [[38, 38], [43, 72], [43, 98]], { mol: 'o2', dur: 1450, delay: 200 });
          self.later(function () {
            self.winGame('Awesome! Carbon dioxide + Water + Sunlight -> Glucose + Oxygen!',
              'Amazing job! The leaf used sunlight, water, and carbon dioxide to make glucose and release oxygen!');
          }, 850);
        }
      }
    });
  };


  /* ========================================================================
     2. FOOD: Match the 5 Digestive Organs (Drag & Drop + Morphing Bolus)
     ======================================================================== */
  var DG_INFO = {
    mouth:      { short: '1. Mouth',       pos: [42, 21], hint: 'Mouth is spot #1 at the top where teeth chew food!', msg: 'Mouth matched! Teeth chew food and saliva breaks down starch.' },
    oesophagus: { short: '2. Food Pipe',   pos: [52, 37], hint: 'Food Pipe is spot #2 leading down to the stomach!', msg: 'Food Pipe matched! Food travels down to the stomach.' },
    stomach:    { short: '3. Stomach',     pos: [56, 55], hint: 'Stomach is spot #3 in the middle!', msg: 'Stomach matched! Acid and enzymes break down proteins.' },
    small:      { short: '4. Small Int.',  pos: [49, 73], hint: 'Small Intestine is spot #4 in the coiled center!', msg: 'Small Intestine matched! Digested food absorbs into blood!' },
    large:      { short: '5. Large Int.',  pos: [36, 66], hint: 'Large Intestine is spot #5 framing the outside!', msg: 'Large Intestine matched! Water reabsorbs and waste exits!' }
  };

  window.sxGameFood = function () {
    return Object.assign(gameBase('food'), {
      gUsesDrag: true,
      dgMatched: [],
      dgCurOrgan: 'mouth',

      gSetup: function () {
        this.dgMatched = [];
        this.dgCurOrgan = 'mouth';
      },

      dgShort: function (z) { return DG_INFO[z] ? DG_INFO[z].short : z; },

      dgBolusSprite: function () {
        var o = this.dgCurOrgan;
        if (o === 'mouth' || o === 'oesophagus') return '/static/images/saxaz_web/games/tok_food_apple.webp?v=' + ASSET_V;
        if (o === 'stomach' || o === 'small') return '/static/images/saxaz_web/games/tok_food_chyme.webp?v=' + ASSET_V;
        return '/static/images/saxaz_web/games/tok_food_waste.webp?v=' + ASSET_V;
      },

      dgBolusPosStyle: function () {
        var p = (DG_INFO[this.dgCurOrgan] || DG_INFO.mouth).pos;
        return 'left:' + (p[0] - 10) + '%;top:' + p[1] + '%;';
      },

      dgGoal: function () {
        if (this.gDone) return 'Complete Digestive Journey! Food traveled from Mouth -> Stomach -> Small Intestine -> Large Intestine!';
        return 'Drag (or tap) each Organ Card on the right onto its matching number (1 to 5) on the 3D body!';
      },

      onDropToken: function (id, zone) {
        var self = this;
        if (id !== zone) {
          self.oops(DG_INFO[id] ? DG_INFO[id].hint : 'Try matching that card to another numbered spot!');
          return false;
        }
        if (self.dgMatched.indexOf(id) === -1) self.dgMatched.push(id);
        self.dgCurOrgan = id;
        sfx('Select');
        var fx = self.fxLayer();
        var p = DG_INFO[id].pos;
        popAt(fx, p[0], p[1] - 8, DG_INFO[id].short + '!', 'is-gold');
        if (id === 'small') {
          flowAlong(fx, [[49, 73], [22, 64], [10, 56]], { mol: 'glucose', dur: 1000 });
        }
        self.say(DG_INFO[id].msg, 'good');

        if (self.dgMatched.length >= 5) {
          self.later(function () {
            self.winGame('All 5 Digestive Organs matched!',
              'Awesome! You matched every part of the human digestive system from the mouth to the intestines!');
          }, 600);
        }
        return true;
      }
    });
  };


  /* ========================================================================
     3. BREATHE: 4-Step Drag & Match on the 24-Frame 3D Lungs
     ======================================================================== */
  var BR_INFO = {
    trachea:   { pull: 0.55, hint: 'Fresh Oxygen enters at the top Windpipe (Trachea)!', msg: 'Air entered through the nose and down the Trachea!' },
    alveoli:   { pull: 0.92, hint: 'Drop Oxygen-to-Blood onto #2 Lungs on the left!', msg: 'Lungs loaded Oxygen into the blood!' },
    diaphragm: { pull: 1.00, hint: 'Drop Diaphragm Pull & Push onto #3 at the bottom of the chest!', msg: 'Diaphragm pulled down to expand the lungs!' },
    atp:       { pull: 0.35, hint: 'Drop Glucose + O2 -> ATP onto #4 Cell ATP Energy on the right!', msg: 'Cells combined Glucose + Oxygen to store energy in ATP!' }
  };

  window.sxGameBreathe = function () {
    return Object.assign(gameBase('breathe'), {
      gUsesDrag: true,
      brMatched: [],
      _brTargetPull: 0.2,
      _brCurPull: 0,
      _brSheet: null,
      _brDrawn: -1,

      gSetup: function () {
        var self = this;
        self.brMatched = [];
        self._brTargetPull = 0.2;
        self._brCurPull = 0;
        var cvs = self.gRoot() ? self.gRoot().querySelector('.gx-breathe-canvas') : null;
        if (cvs && !self._brBound) {
          self._brBound = true;
          self._brCvs = cvs;
          self._brCtx = cvs.getContext ? cvs.getContext('2d') : null;
          loadSheet(cvs.getAttribute('data-br-sheet'), function (img) {
            self._brSheet = img;
            self.drawBreatheFrame(0);
            var st = self.stageEl();
            if (st) st.classList.add('is-sheet-live');
          });
        }
      },

      drawBreatheFrame: function (pullVal) {
        if (!this._brCtx || !this._brSheet) return;
        var fIdx = clamp(Math.round(pullVal * 23), 0, 23);
        if (fIdx === this._brDrawn) return;
        this._brDrawn = fIdx;
        drawAtlasCell(this._brCtx, this._brSheet, fIdx, 6, this._brCvs.width, this._brCvs.height);
      },

      gOnVisible: function (vis) {
        var self = this;
        cancelAnimationFrame(self.gRaf);
        if (!vis || reduceMotion()) return;
        var last = performance.now();
        var tick = function (ts) {
          if (!self.gVisible || document.hidden) return;
          var dt = Math.min(0.05, Math.max(0.004, (ts - last) / 1000));
          last = ts;
          var wave = 0.5 - 0.5 * Math.cos((ts / 1000) * Math.PI * 1.1);
          var goal = self.gDone ? wave : clamp(self._brTargetPull * 0.7 + wave * 0.3, 0, 1);
          self._brCurPull += (goal - self._brCurPull) * Math.min(1, dt * 6);
          self.drawBreatheFrame(self._brCurPull);
          self.gRaf = requestAnimationFrame(tick);
        };
        self.gRaf = requestAnimationFrame(tick);
      },

      brGoal: function () {
        if (this.gDone) return 'Respiration complete! Oxygen entered the lungs, blood carried it to cells, and Glucose + O2 released ATP energy!';
        return 'Drag (or tap) each 3D Breathing Card onto its matching glowing zone (1 to 4) on the 3D Lungs!';
      },

      onDropToken: function (id, zone) {
        var self = this;
        if (id !== zone) {
          self.oops(BR_INFO[id] ? BR_INFO[id].hint : 'Try another glowing zone on the 3D Lungs!');
          return false;
        }
        if (self.brMatched.indexOf(id) === -1) self.brMatched.push(id);
        self._brTargetPull = BR_INFO[id].pull;
        sfx('Select');
        var fx = self.fxLayer();
        flowAlong(fx, [[50, 18], [50, 44], [38, 56]], { mol: id === 'atp' ? 'glucose' : 'o2', dur: 950 });
        popAt(fx, 50, 42, 'Matched!', 'is-blue');
        self.say(BR_INFO[id].msg, 'good');

        if (self.brMatched.length >= 4) {
          self.later(function () {
            self.winGame('All 4 Respiration steps matched! Glucose + O2 -> CO2 + H2O + ATP!',
              'Great job! You matched how oxygen enters the lungs and breaks down glucose to store ATP energy!');
          }, 650);
        }
        return true;
      }
    });
  };


  /* ========================================================================
     4. BLOOD: Meet the Blood Crew — Simple 4-Card Drag & Drop
     ======================================================================== */
  var BD = {
    rbc:      { name: 'Red Blood Cell', hint: 'Drop Red Blood Cell onto the red discs on the left!', done: 'Red Blood Cell: carries oxygen to every cell!' },
    wbc:      { name: 'White Blood Cell', hint: 'Drop White Blood Cell onto the white guardian at top-right!', done: 'White Blood Cell: fights germs and disease!' },
    platelet: { name: 'Platelets', hint: 'Drop Platelets onto the star shapes at bottom-right!', done: 'Platelets: rush to cuts and clot blood!' },
    plasma:   { name: 'Plasma', hint: 'Drop Plasma onto the golden liquid stream at top-left!', done: 'Plasma: liquid carrying food, hormones, and waste!' }
  };

  window.sxGameBlood = function () {
    return Object.assign(gameBase('blood'), {
      gUsesDrag: true,
      bdDone: [],

      gSetup: function () { this.bdDone = []; },
      bdName: function (z) { return BD[z] ? BD[z].name : ''; },

      bdGoal: function () {
        if (this.gDone) return 'All 4 Blood Crew heroes matched! RBCs, WBCs, Platelets, and Plasma work together nonstop.';
        return 'Drag (or tap) each 3D Blood Card on the right onto its matching crew member inside the vessel!';
      },

      onDropToken: function (id, zone) {
        var self = this;
        if (id !== zone) {
          self.oops(BD[id] ? BD[id].hint : 'Try another spot in the blood vessel.');
          return false;
        }
        if (self.bdDone.indexOf(id) === -1) self.bdDone.push(id);
        sfx('Select');
        self.say(BD[id].done, 'good');
        var fx = self.fxLayer();
        if (id === 'rbc') flowAlong(fx, [[8, 45], [30, 56]], { mol: 'o2', dur: 950 });
        else if (id === 'wbc') flowAlong(fx, [[92, 68], [70, 32]], { mol: 'germ', dur: 950 });
        else if (id === 'plasma') flowAlong(fx, [[10, 22], [44, 24]], { mol: 'glucose', dur: 950 });
        popAt(fx, 50, 42, BD[id].name + '!', 'is-gold');

        if (self.bdDone.length >= 4) {
          self.later(function () {
            self.winGame('Complete Blood Crew unlocked!',
              'Brilliant! Red blood cells carry oxygen, white blood cells fight disease, platelets clot cuts, and plasma carries food and waste!');
          }, 700);
        }
        return true;
      }
    });
  };


  /* ========================================================================
     5. PUMP: Easy 6-Tap Heart Super-Pump to 30 Feet!
     ======================================================================== */
  window.sxGamePump = function () {
    return Object.assign(gameBase('pump'), {
      pmFt: 0,
      pmBeats: 0,
      pmSqueeze: false,
      _pmSheet: null,
      _pmPos: 0,
      _pmDrawn: -1,

      gSetup: function () {
        var self = this;
        self.pmFt = 0;
        self.pmBeats = 0;
        self.pmSqueeze = false;
        var cvs = self.gRoot() ? self.gRoot().querySelector('.pm-heart-canvas') : null;
        if (cvs && !self._pmBound) {
          self._pmBound = true;
          self._pmCvs = cvs;
          self._pmCtx = cvs.getContext ? cvs.getContext('2d') : null;
          loadSheet(cvs.getAttribute('data-pm-sheet'), function (img) {
            self._pmSheet = img;
            drawAtlasCell(self._pmCtx, img, 0, 6, cvs.width, cvs.height);
            var st = self.stageEl();
            if (st) st.classList.add('is-sheet-live');
          });
        }
      },

      pmGoal: function () {
        if (this.gDone) return '30 FEET HIGH! Your heart creates enough pressure to pump blood to the top of a 3-storey building!';
        return 'Tap the 3D Heart 6 times to pump the blood fountain past the Student (6 ft) and Tree (15 ft) up to 30 feet!';
      },

      gOnVisible: function (vis) {
        var self = this;
        cancelAnimationFrame(self.gRaf);
        if (!vis || reduceMotion()) return;
        var last = performance.now();
        var tick = function (ts) {
          if (!self.gVisible || document.hidden) return;
          var dt = Math.min(0.06, Math.max(0.004, (ts - last) / 1000));
          last = ts;
          if (self._pmSheet && self._pmCtx) {
            var fps = 15 + (self.pmFt / 30) * 18;
            self._pmPos = (self._pmPos + dt * fps) % 36;
            var fIdx = Math.floor(self._pmPos);
            if (fIdx !== self._pmDrawn) {
              self._pmDrawn = fIdx;
              drawAtlasCell(self._pmCtx, self._pmSheet, fIdx, 6, self._pmCvs.width, self._pmCvs.height);
            }
          }
          self.gRaf = requestAnimationFrame(tick);
        };
        self.gRaf = requestAnimationFrame(tick);
      },

      pmDown: function (e) {
        if (e) e.preventDefault();
        if (this.gDone) return;
        this.pmSqueeze = true;
      },

      pmUp: function () {
        var self = this;
        if (!self.pmSqueeze) return;
        self.pmSqueeze = false;
        if (self.gDone) return;
        self.gStarted = true;
        self.pmBeats += 1;
        self.pmFt = Math.min(30, self.pmBeats * 5);
        sfx('Select');
        var fx = self.fxLayer();
        popAt(fx, 50, 22, self.pmBeats % 2 ? 'LUB! +5 ft' : 'DUB! +5 ft', 'is-red');
        flowAlong(fx, [[52, 48], [84, 24]], { mol: 'rbc', dur: 650 });
        self.say(self.pmFt + ' feet high!', 'good');
        if (self.pmFt >= 30) {
          self.winGame('30 FEET! Higher than a 3-storey building!',
            'Whoa! Thirty feet high! The pressure created by your heart is truly amazing!');
        }
      },

      pmPct: function () { return clamp((this.pmFt / 30) * 100, 0, 100); }
    });
  };


  /* ========================================================================
     6. KIDNEY: Calm 2-Zone Drag & Drop Filter Sorter
     ======================================================================== */
  window.sxGameKidney = function () {
    return Object.assign(gameBase('kidney'), {
      gUsesDrag: true,
      kdWasteDone: 0,
      kdKeepDone: 0,

      gSetup: function () {
        this.kdWasteDone = 0;
        this.kdKeepDone = 0;
      },

      kdFill: function () { return clamp((this.kdWasteDone / 3) * 100, 0, 100); },

      kdGoal: function () {
        if (this.gDone) return 'Blood sparkling clean! Kidneys removed Urea, Extra Salt & Water as Urine while keeping Glucose, Protein & RBCs!';
        return 'Drag Harmful Waste (Urea, Extra Salt, Extra Water) into the Kidneys (top) and Useful Items into the Bloodstream (bottom)!';
      },

      onDropToken: function (kind, zone, el) {
        var self = this;
        var itemName = (el && el.getAttribute('data-item-name')) || 'Item';
        var fx = self.fxLayer();

        if (kind !== zone) {
          if (kind === 'waste') {
            self.oops(itemName + ' is harmful waste! Drag it up into the Kidneys so Nephrons filter it out.');
          } else {
            self.oops(itemName + ' is useful to the body! Drag it into the green Bloodstream zone to keep it safe.');
          }
          return false;
        }

        sfx('Select');
        if (kind === 'waste') {
          self.kdWasteDone += 1;
          flowAlong(fx, [[32, 32], [36, 56], [46, 74]], { mol: 'urine', cls: 'is-urine', dur: 1100, fade: false });
          popAt(fx, 50, 28, 'Filtered to Urine!', 'is-gold');
          self.say(itemName + ' filtered out by Nephrons into urine!', 'good');
        } else {
          self.kdKeepDone += 1;
          popAt(fx, 50, 62, 'Kept Safe in Blood!', 'is-green');
          self.say(itemName + ' kept safely inside the bloodstream!', 'good');
        }

        if (self.kdWasteDone >= 3 && self.kdKeepDone >= 3) {
          self.later(function () {
            self.winGame('All 6 items sorted! Kidneys cleaned the blood!',
              'Super filter! Your kidneys removed urea, extra salt, and water while keeping glucose, protein, and blood cells inside the body!');
          }, 700);
        }
        return true;
      }
    });
  };


  /* ========================================================================
     7. TEAM: Drag Each Life-Process Job onto Its 3D Mascot Hero!
     ======================================================================== */
  var TEAM = [
    { id: 'nut', name: '1. Nutrition',      doneLabel: 'Gives Food & Fuel!',    img: 'mascot_nutrition',   color: '#16a34a', hint: 'Food & Fuel belongs to Nutrition (the green Apple Hero)!' },
    { id: 'res', name: '2. Respiration',    doneLabel: 'Releases ATP Energy!',  img: 'mascot_respiration', color: '#0284c7', hint: 'ATP Energy belongs to Respiration (the blue Lungs Hero)!' },
    { id: 'tra', name: '3. Transportation', doneLabel: 'Delivers to All Cells!',img: 'mascot_transport',   color: '#dc2626', hint: 'Delivery belongs to Transportation (the red Heart Hero)!' },
    { id: 'exc', name: '4. Excretion',      doneLabel: 'Removes Body Waste!',   img: 'mascot_excretion',   color: '#d97706', hint: 'Removing Waste belongs to Excretion (the golden Kidney Hero)!' }
  ];

  window.sxGameTeam = function () {
    return Object.assign(gameBase('team'), {
      gUsesDrag: true,
      tmTeam: TEAM,
      tmMatched: [],
      _heroSprites: null,
      _heroRaf: 0,

      gSetup: function () {
        var self = this;
        self.tmMatched = [];
        self.$nextTick(function () { self.initHeroCanvases(); });
      },

      initHeroCanvases: function () {
        var self = this;
        if (!self.gRoot() || reduceMotion()) return;
        if (!self._heroSprites) self._heroSprites = {};
        var canvases = self.gRoot().querySelectorAll('.tm-hero-canvas');
        canvases.forEach(function (cvs, idx) {
          var hid = cvs.getAttribute('data-hero-id');
          if (!hid || self._heroSprites[hid]) return;
          var ctx = cvs.getContext ? cvs.getContext('2d') : null;
          var url = cvs.getAttribute('data-hero-sheet');
          var mateCard = cvs.closest('.tm-mate');
          var sp = { cvs: cvs, ctx: ctx, img: null, pos: idx * 3.5, drawn: -1 };
          self._heroSprites[hid] = sp;
          loadSheet(url, function (img) {
            sp.img = img;
            drawAtlasCell(ctx, img, 0, 6, 220, 220);
            sp.drawn = 0;
            if (mateCard) mateCard.classList.add('is-hero-live');
          });
        });
        self.startHeroSpriteLoop();
      },

      startHeroSpriteLoop: function () {
        var self = this;
        if (self._heroRaf || reduceMotion()) return;
        var last = performance.now();
        var step = function (ts) {
          if (document.hidden) { self._heroRaf = 0; return; }
          var dt = Math.min(0.05, Math.max(0.004, (ts - last) / 1000));
          last = ts;
          if (self.gVisible && self._heroSprites) {
            Object.keys(self._heroSprites).forEach(function (hid) {
              var sp = self._heroSprites[hid];
              if (!sp || !sp.img) return;
              var cheering = self.tmMatched.indexOf(hid) !== -1 || self.gDone;
              var fps = cheering ? 16 : 13;
              sp.pos += dt * fps;
              var frameIdx = cheering ? (16 + (Math.floor(sp.pos) % 8)) : (Math.floor(sp.pos) % 16);
              if (frameIdx !== sp.drawn) {
                sp.drawn = frameIdx;
                drawAtlasCell(sp.ctx, sp.img, frameIdx, 6, 220, 220);
              }
            });
          }
          self._heroRaf = requestAnimationFrame(step);
        };
        self._heroRaf = requestAnimationFrame(step);
      },

      gOnVisible: function (vis) {
        if (vis) {
          this.initHeroCanvases();
          this.startHeroSpriteLoop();
        }
      },

      tmGoal: function () {
        if (this.gDone) return 'Team Complete! Nutrition, Respiration, Transportation, and Excretion work together nonstop to keep us alive!';
        return 'Drag (or tap) each Job Card below onto the matching Life-Process Hero above!';
      },

      onDropToken: function (id, zone) {
        var self = this;
        var found = TEAM.filter(function (m) { return m.id === id; })[0];
        if (id !== zone) {
          self.oops(found ? found.hint : 'Try dropping onto another Hero!');
          return false;
        }
        if (self.tmMatched.indexOf(id) === -1) self.tmMatched.push(id);
        sfx('Select');
        self.say((found ? found.name : 'Hero') + ' powered up!', 'good');

        if (self.tmMatched.length >= 4) {
          self.later(function () {
            self.winGame('All 4 Life-Process Heroes matched!',
              'You nailed it! Nutrition gives food, Respiration gives energy, Transportation delivers it, and Excretion cleans the waste!');
          }, 600);
        }
        return true;
      }
    });
  };

  window.SX_GAME_HELPERS = {
    flowAlong: flowAlong,
    popAt: popAt,
    gameBase: gameBase,
    mol: mol,
    sfx: sfx,
    clamp: clamp
  };
})();
