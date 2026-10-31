/* Daily Brief layout. Flows the memo into letter sheets, gives the calendar and each supporting
   sheet its own page, builds the calendar with measured labels, fills page references, and reports fit,
   sheet count, minimum font size, and calendar labels moved under the grid as attributes on <html>
   for render_briefing.py. Reads the global DATA object. */
(function () {
  var h = document.documentElement;
  if (location.hash === '#phone') {
    h.classList.add('m'); h.classList.add('pp');
    var P = DATA.phone_page;
    document.write('<style>@page{size:' + P[0] + 'in ' + P[1] + 'in;margin:.34in .3in}' +
      '@media screen{html.pp body{width:' + (P[0] - 0.6) + 'in;max-width:none;margin:0;padding:0}}</style>');
  } else if (window.matchMedia && matchMedia('screen and (max-width: 700px)').matches) {
    h.classList.add('m');
  }
  var moved = [];

  function el(tag, cls, inner) {
    var d = document.createElement(tag);
    if (cls) d.className = cls;
    if (inner != null) d.innerHTML = inner;
    return d;
  }
  function mins(t) { var p = t.split(':'); return +p[0] * 60 + (+p[1]); }
  function clock(m) {
    var hh = Math.floor(m / 60) % 24, mm = m % 60, h12 = hh % 12 || 12;
    return h12 + ':' + (mm < 10 ? '0' : '') + mm;
  }
  function hourLabel(hh) { return hh === 12 ? 'Noon' : (hh % 12 || 12) + (hh < 12 || hh === 24 ? ' am' : ' pm'); }
  function fits(lab) { return lab.scrollHeight <= lab.clientHeight + 1 && lab.scrollWidth <= lab.clientWidth + 1; }

  function calendar(body, phone) {
    var a = DATA.h0 * 60, b = DATA.h1 * 60, span = b - a;
    if (phone) body.style.height = DATA.phone_cal_height + 'px';
    var H = body.clientHeight - 8, W = body.clientWidth, AX = phone ? 44 : 58, GAP = phone ? 5 : 8;
    body.style.flex = 'none'; body.style.height = (H + 8) + 'px';
    var px = H / span, inner = W - AX - 2 * GAP, LH = 17;
    var hasFam = DATA.cal.some(function (x) { return x.lane === 'family'; });
    var meW = hasFam ? inner * (phone ? 0.66 : 0.62) : inner, famW = inner - meW;
    var lanes = { me: { left: AX + GAP, width: meW }, family: { left: AX + 2 * GAP + meW, width: famW } };
    var head = body.parentNode.querySelector('.cal-head');
    if (head) {
      head.style.gridTemplateColumns = AX + 'px ' + meW + 'px ' + (hasFam ? famW + 'px' : '');
      if (!hasFam) { var fh = head.querySelector('.fh'); if (fh) fh.remove(); }
    }
    function Y(m) { return (Math.max(a, Math.min(b, m)) - a) * px; }
    function endOf(x) { return x.end ? mins(x.end) : mins(x.start) + 15; }

    for (var hr = DATA.h0; hr <= DATA.h1; hr++) {
      var line = el('div', 'hr', '<span>' + hourLabel(hr) + '</span>');
      line.style.top = Y(hr * 60) + 'px';
      body.appendChild(line);
    }
    var meBusy = [];
    ['me', 'family'].forEach(function (laneName) {
      var L = lanes[laneName], failed = [];
      var items = DATA.cal.filter(function (x) { return x.lane === laneName && mins(x.start) < b && endOf(x) > a; })
        .map(function (x) { return { x: x, s: Math.max(a, mins(x.start)), e: Math.min(b, endOf(x)), segs: [] }; })
        .sort(function (u, v) { return u.s - v.s || (v.e - v.s) - (u.e - u.s); });
      var colEnds = [];
      items.forEach(function (it) {
        var c = 0;
        while (c < colEnds.length && colEnds[c] > it.s) c++;
        colEnds[c] = it.e; it.col = c;
        if (laneName === 'me') meBusy.push([it.s, it.e]);
      });
      // Overlapping blocks share the columns of their cluster for their whole duration, as in Google Calendar.
      var clusters = [];
      items.forEach(function (it) {
        var c = clusters[clusters.length - 1];
        if (c && it.s < c.e) { c.list.push(it); c.e = Math.max(c.e, it.e); } else clusters.push({ e: it.e, list: [it] });
      });
      clusters.forEach(function (c) {
        var n = Math.max.apply(null, c.list.map(function (it) { return it.col; })) + 1;
        c.list.forEach(function (it) { it.segs = [{ t0: it.s, t1: it.e, r: it.col, k: n }]; });
      });
      items.forEach(function (it) {
        var x = it.x, cls = 'seg' + (laneName === 'family' ? ' fam' : '') + (x.main ? ' main' : '');
        var best = null, bestArea = -1;
        it.segs.forEach(function (sg, j) {
          var d = el('div', cls + (j > 0 ? ' no-top' : '') + (j < it.segs.length - 1 ? ' no-bot' : ''));
          var w = L.width / sg.k;
          d.style.left = (L.left + w * sg.r) + 'px'; d.style.width = (w - (sg.k > 1 ? 3 : 0)) + 'px';
          d.style.top = Y(sg.t0) + 'px'; d.style.height = Math.max(Y(sg.t1) - Y(sg.t0) - (j === it.segs.length - 1 ? 1 : 0), 3) + 'px';
          body.appendChild(d);
          var area = (Y(sg.t1) - Y(sg.t0)) * w;
          if (area > bestArea) { bestArea = area; best = d; }
        });
        var note = x.note ? ' <span class="nt">' + x.note + '</span>' : '';
        var full = '<span class="tm">' + x.time + '</span><span class="bt">' + x.label + '</span>' + note;
        var start = '<span class="tm">' + x.start_text + '</span><span class="bt">' + x.label + '</span>' + note;
        var bare = '<span class="tm">' + x.start_text + '</span><span class="bt">' + x.label + '</span>';
        var lab = el('div', 'blab');
        best.appendChild(lab);
        var placed = [full, start, bare].some(function (html) { lab.innerHTML = html; return fits(lab); });
        if (!placed) { lab.innerHTML = ''; failed.push({ it: it, x: x, text: start, bare: bare }); }
      });

      // Labels that do not fit inside a short block go just below or above it, or onto one shared line
      // across back-to-back short blocks. The list under the grid is the last resort.
      var occ = items.map(function (it) { return [Y(it.s), Y(it.e)]; });
      function freeV(y0, y1) { return y0 >= 0 && y1 <= H + 6 && occ.every(function (o) { return y1 <= o[0] + 0.5 || y0 >= o[1] - 0.5; }); }
      function putOut(html, top, cls) {
        var d = el('div', 'olab' + (cls ? ' ' + cls : ''), html);
        d.style.left = (L.left + 2) + 'px'; d.style.width = (L.width - 4) + 'px'; d.style.top = top + 'px';
        body.appendChild(d);
        if (d.scrollWidth > d.clientWidth + 1) { d.remove(); return false; }
        occ.push([top, top + LH]);
        if (laneName === 'me') meBusy.push([a + top / px, a + (top + LH) / px]);
        return true;
      }
      function tryNear(html, s, e) {
        var below = Y(e) + 0.5, above = Y(s) - 0.5 - LH;
        if (freeV(below, below + LH) && putOut(html, below)) return true;
        if (freeV(above, above + LH) && putOut(html, above)) return true;
        return false;
      }
      var groups = [];
      failed.sort(function (u, v) { return u.it.s - v.it.s; }).forEach(function (f) {
        var g = groups[groups.length - 1];
        if (g && f.it.s <= g.e) { g.list.push(f); g.e = Math.max(g.e, f.it.e); } else groups.push({ s: f.it.s, e: f.it.e, list: [f] });
      });
      groups.forEach(function (g) {
        var html = g.list.map(function (f) { return f.text; }).join(' · ');
        var mid = (Y(g.s) + Y(g.e) - LH) / 2;
        if (g.list.length > 1 && Y(g.e) - Y(g.s) >= LH && putOut(html, mid, 'grp')) return;
        if (tryNear(html, g.s, g.e)) return;
        if (g.list.length === 1 && tryNear(g.list[0].bare, g.s, g.e)) return;
        g.list.forEach(function (f) {
          if (g.list.length > 1 && (tryNear(f.text, f.it.s, f.it.e) || tryNear(f.bare, f.it.s, f.it.e))) return;
          moved.push(f.x.start_text + ' ' + f.x.label);
        });
      });
    });

    // Notes for preferences without a set time, then open time in the column for the user.
    (DATA.cal_notes || []).forEach(function (n) {
      var t = mins(n.after), top = Y(t) + 4;
      var d = el('div', 'cnote', n.text);
      d.style.left = (lanes.me.left + 4) + 'px'; d.style.width = (lanes.me.width - 8) + 'px'; d.style.top = top + 'px';
      body.appendChild(d);
      var hgt = d.offsetHeight, moves = 0;
      function hit() { return meBusy.filter(function (iv) { return Y(iv[0]) < top + hgt && Y(iv[1]) > top; }); }
      while (hit().length && moves++ < 10) { top = Math.max.apply(null, hit().map(function (iv) { return Y(iv[1]); })) + 3; }
      d.style.top = top + 'px';
      var bottom = top + hgt;
      var clash = hit().length > 0 || bottom > H + 6;
      if (clash) { d.remove(); moved.push(n.text); } else meBusy.push([a + top / px, a + bottom / px]);
    });
    meBusy.sort(function (u, v) { return u[0] - v[0]; });
    var cur = a;
    meBusy.concat([[b, b]]).forEach(function (iv) {
      if (iv[0] - cur >= 45 && Y(iv[0]) - Y(cur) >= 22) {
        var g = el('div', 'gap', 'Open');
        g.style.left = (lanes.me.left + 6) + 'px'; g.style.top = (Y(cur) + 3) + 'px';
        body.appendChild(g);
      }
      cur = Math.max(cur, iv[1]);
    });
    var over = body.parentNode.querySelector('.cal-over');
    if (over && moved.length) over.innerHTML = '<b>Also on the calendar:</b> ' + moved.join('; ') + '.';
  }

  function paginate() {
    var flow = document.getElementById('flow');
    if (h.classList.contains('m')) return 1;
    var tpl = document.getElementById('sheet-tpl'), sheets = [], body = null;
    var parts = [].slice.call(flow.children);
    function over(bd) { return bd.scrollHeight > bd.clientHeight + 1; }
    function newSheet() {
      var s = tpl.content.firstElementChild.cloneNode(true);
      document.body.insertBefore(s, flow); sheets.push(s);
      return s.querySelector('.body');
    }
    function rowsOf(box) {
      return [].filter.call(box.children.length && box.tagName === 'TABLE' ? box.querySelectorAll(':scope > tbody > tr, :scope > tr') : box.children,
        function (r) { return !r.querySelector('th'); });
    }
    function trySplit(sec) {
      var box = sec.querySelector('.split');
      if (!box) return false;
      var rows = rowsOf(box), k = rows.length;
      if (k < 2) return false;
      while (k > 1 && over(body)) { k--; rows[k].style.display = 'none'; }
      if (over(body) || k === rows.length) { rows.forEach(function (r) { r.style.display = ''; }); return false; }
      var cont = sec.cloneNode(true);
      rows.slice(k).forEach(function (r) { r.remove(); });
      ['data-break', 'data-ref', 'data-page'].forEach(function (x) { cont.removeAttribute(x); });
      var crows = rowsOf(cont.querySelector('.split'));
      crows.slice(0, k).forEach(function (r) { r.remove(); });
      crows.slice(k).forEach(function (r) { r.style.display = ''; });
      [].forEach.call(cont.querySelectorAll('.mhead, .intro, .assess'), function (n) { n.remove(); });
      var hd = cont.querySelector('h2, h1.sheet-title');
      if (hd) hd.textContent = hd.textContent + ' (continued)';
      body = newSheet();
      place(cont, true);
      return true;
    }
    function place(sec, fresh) {
      if (!fresh && sec.getAttribute('data-break') && body.children.length) body = newSheet();
      body.appendChild(sec);
      if (sec.getAttribute('data-ref')) sec.setAttribute('data-page', sheets.length);
      if (!over(body)) return;
      if (trySplit(sec)) return;
      // Keep the navigation note with a short final memo section instead of giving it a page alone.
      var prev = sec.previousElementSibling;
      if (sec.querySelector('.mfoot') && prev && prev.querySelector('h2') && prev.offsetHeight < body.clientHeight / 3) {
        body.removeChild(sec); body.removeChild(prev);
        body = newSheet(); place(prev, true); place(sec, true);
        return;
      }
      if (body.children.length > 1) { body.removeChild(sec); body = newSheet(); place(sec, true); }
    }
    body = newSheet();
    sheets[0].classList.add('first');
    parts.forEach(function (sec) { place(sec, false); });
    flow.style.display = 'none';
    sheets.forEach(function (s, i) { s.querySelector('.pg').textContent = 'Page ' + (i + 1) + ' of ' + sheets.length; });
    sheets[sheets.length - 1].classList.add('last');
    return sheets.length;
  }

  function fillRefs(phone) {
    [].forEach.call(document.querySelectorAll('[data-refto]'), function (span) {
      var target = document.querySelector('[data-ref="' + span.getAttribute('data-refto') + '"]');
      if (!target) return;
      span.textContent = phone ? 'below' : 'page ' + target.getAttribute('data-page');
    });
  }

  function minFont() {
    var min = 99, where = '';
    [].forEach.call(document.querySelectorAll('body *'), function (n) {
      if (!n.getClientRects().length) return;
      var own = [].some.call(n.childNodes, function (c) { return c.nodeType === 3 && c.textContent.trim(); });
      if (!own) return;
      var fs = parseFloat(getComputedStyle(n).fontSize);
      if (fs < min) { min = fs; where = n.className || n.tagName; }
    });
    return [min, where];
  }

  function done(n) {
    var bad = [];
    if (!h.classList.contains('m')) {
      [].forEach.call(document.querySelectorAll('.sheet .body'), function (bd, i) {
        if (bd.scrollHeight > bd.clientHeight + 1) bad.push(i + 1);
        if (bd.children.length === 1 && bd.firstElementChild.querySelector('.mfoot')) bad.push('navigation-only:' + (i + 1));
      });
      var cal = document.querySelector('.s-cal');
      if (cal && cal.scrollHeight > cal.clientHeight + 1) bad.push('calendar');
    }
    var mf = minFont();
    h.setAttribute('data-sheets', n);
    h.setAttribute('data-moved', moved.join('|'));
    h.setAttribute('data-minfont', mf[0].toFixed(2) + ' ' + mf[1]);
    h.setAttribute('data-fit', bad.length ? 'overflow:' + bad.join(',') : 'ok');
  }

  function run() {
    var phone = h.classList.contains('m');
    var n = paginate();
    var body = document.getElementById('cal');
    if (body) {
      var sec = body.closest('.s-cal'), over = sec.querySelector('.cal-over');
      calendar(body, phone);
      for (var i = 0; !phone && i < 4; i++) {
        var extra = sec.scrollHeight - sec.clientHeight;
        if (extra <= 1) break;
        var hgt = body.clientHeight - extra - 2;
        body.innerHTML = ''; if (over) over.innerHTML = ''; moved = [];
        body.style.height = hgt + 'px';
        calendar(body, phone);
      }
    }
    fillRefs(phone);
    done(n);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var ready = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
    ready.then(function () { setTimeout(run, 30); });
  });
})();
