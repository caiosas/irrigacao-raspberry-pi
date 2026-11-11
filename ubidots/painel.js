// Painel da irrigação no Ubidots (widget HTML Canvas).
// Lê as variáveis do device "irrigacao" e escreve comandos nas variáveis "bomba" e
// "modo_auto"; a aba Ubidots do Node-RED recebe esses valores e repassa para a Pi.
(function () {
  var DEV = 'irrigacao';
  var POLL = 10000;          // ms entre leituras normais
  var POLL_RAPIDO = 2000;    // ms logo após um comando
  var OFFLINE_MS = 6 * 60 * 1000;   // sensores chegam a cada 2 min
  var SERIES = [
    { v: 'solo', nome: 'Solo (%)', cor: '#1f77b4' },
    { v: 'umidade_ar', nome: 'Umid. ar (%)', cor: '#2ca02c' },
    { v: 'temperatura', nome: 'Temp. (°C)', cor: '#d62728' },
    { v: 'bomba', nome: 'Bomba (on=100)', cor: '#ff7f0e', escala: 100, degrau: true },
  ];
  var GAUGES = {
    solo: { el: 'g-solo', nome: 'Umidade do solo', un: '%', min: 0, max: 100, cortes: [30, 60], cores: ['#ca3838', '#e6b800', '#00a000'] },
    temperatura: { el: 'g-temp', nome: 'Temperatura', un: '°C', min: 0, max: 50, cortes: [18, 32], cores: ['#00b0f0', '#00a000', '#ca3838'] },
    umidade_ar: { el: 'g-umid', nome: 'Umidade do ar', un: '%', min: 0, max: 100, cortes: [40, 70], cores: ['#e6b800', '#00a000', '#00b0f0'] },
  };

  var st = { token: null, jwt: null, iniciado: false, last: {}, hist: {}, janelaH: 1,
             rapidoAte: 0, timer: null, histEm: 0, otimista: {} };
  var $ = function (id) { return document.getElementById(id); };

  // ---------- autenticação: o Ubidots entrega o token do visitante ao widget ----------
  var ub = null;
  try { ub = new window.Ubidots(); } catch (e) { ub = null; }
  if (ub) {
    ub.on('receivedToken', function (t) { if (t && !st.token) { st.token = t; iniciar(); } });
    ub.on('receivedJWTToken', function (t) { if (t && !st.jwt) { st.jwt = t; iniciar(); } });
  }
  function headers() {
    var h = { 'Content-Type': 'application/json' };
    if (st.token) h['X-Auth-Token'] = st.token;
    else if (st.jwt) h.Authorization = 'Bearer ' + st.jwt;
    return h;
  }
  function api(path, opts) {
    opts = opts || {};
    return fetch(window.location.origin + '/api' + path, {
      method: opts.method || 'GET', headers: headers(),
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (r) {
      if (!r.ok) { var e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
      return r.status === 204 ? null : r.json();
    });
  }

  // ---------- leitura ----------
  function lerUltimos() {
    return api('/v2.0/devices/~' + DEV + '/variables/?fields=label,lastValue&page_size=50').then(function (r) {
      st.last = {};
      (r.results || []).forEach(function (x) {
        if (x.lastValue && x.lastValue.timestamp) st.last[x.label] = x.lastValue;
      });
      renderEstado();
    });
  }
  function lerHistorico() {
    var inicio = Date.now() - st.janelaH * 3600 * 1000;
    st.histEm = Date.now();
    return Promise.all(SERIES.map(function (s) {
      return api('/v1.6/devices/' + DEV + '/' + s.v + '/values/?start=' + inicio + '&page_size=2000')
        .then(function (r) { st.hist[s.v] = (r.results || []).slice().reverse(); })
        .catch(function () { st.hist[s.v] = []; });
    })).then(renderGrafico);
  }
  function ciclo() {
    clearTimeout(st.timer);
    var p = lerUltimos();
    if (Date.now() - st.histEm > 60000) p = p.then(lerHistorico);
    p.catch(function (e) { setOnline('⚠️ erro ao ler (' + e.message + ')', true); })
     .then(function () {
       st.timer = setTimeout(ciclo, Date.now() < st.rapidoAte ? POLL_RAPIDO : POLL);
     });
  }
  function iniciar() {
    if (st.iniciado) return;
    st.iniciado = true;
    ciclo();
  }

  // ---------- comandos ----------
  function enviar(corpo, texto) {
    aviso('Enviando…');
    botoes(true);
    return api('/v1.6/devices/' + DEV + '/', { method: 'POST', body: corpo }).then(function () {
      st.rapidoAte = Date.now() + 20000;
      aviso(texto + ' Enviado; a Raspberry Pi aplica em alguns segundos.');
      setTimeout(ciclo, 1500);
    }).catch(function (e) {
      var msg = (e.status === 401 || e.status === 403)
        ? 'Sem permissão para enviar comandos com este acesso (link público é só leitura).'
        : 'Falha ao enviar (' + e.message + ').';
      aviso(msg, true);
      st.otimista = {};
      renderEstado();
    }).then(function () { botoes(false); });
  }
  function botoes(ocupado) { $('ir-ligar').disabled = ocupado; $('ir-desligar').disabled = ocupado; }
  function aviso(t, erro) { var a = $('ir-aviso'); a.textContent = t; a.className = 'ir-aviso' + (erro ? ' erro' : ''); }

  $('ir-ligar').addEventListener('click', function () {
    var auto = valor('modo_auto') === 1;
    if (valor('agua') === 0) aviso('Reservatório vazio: a Pi vai recusar ligar a bomba.', true);
    enviar({ bomba: 1 }, auto ? 'Pedido de uma dose de rega.' : 'Pedido para ligar a bomba.');
  });
  $('ir-desligar').addEventListener('click', function () { enviar({ bomba: 0 }, 'Pedido para desligar a bomba.'); });
  $('ir-modo').addEventListener('change', function (ev) {
    var v = ev.target.checked ? 1 : 0;
    st.otimista.modo_auto = { v: v, ate: Date.now() + 15000 };
    enviar({ modo_auto: v }, v ? 'Modo automático.' : 'Modo manual.');
  });
  Array.prototype.forEach.call(document.querySelectorAll('#ir-janela button'), function (b) {
    b.addEventListener('click', function () {
      Array.prototype.forEach.call(document.querySelectorAll('#ir-janela button'), function (x) { x.classList.remove('ativo'); });
      b.classList.add('ativo');
      st.janelaH = Number(b.getAttribute('data-h'));
      lerHistorico();
    });
  });

  // ---------- exibição ----------
  function valor(v) { return st.last[v] ? st.last[v].value : null; }
  function idade(ms) {
    var s = Math.round((Date.now() - ms) / 1000);
    if (s < 60) return 'há ' + Math.max(0, s) + ' s';
    if (s < 3600) return 'há ' + Math.round(s / 60) + ' min';
    if (s < 86400) return 'há ' + Math.round(s / 3600) + ' h';
    return 'há ' + Math.round(s / 86400) + ' d';
  }
  function setOnline(t, off) { var e = $('ir-online'); e.textContent = t; e.className = 'ir-online' + (off ? ' off' : ''); }

  function renderEstado() {
    Object.keys(GAUGES).forEach(function (k) { desenharGauge(GAUGES[k], valor(k)); });

    var agua = valor('agua'), bomba = valor('bomba');
    var ea = $('ir-agua');
    ea.textContent = agua === null ? '—' : (agua >= 0.5 ? '💧 Com água' : '⚠️ VAZIO');
    ea.className = agua !== null && agua < 0.5 ? 'alerta' : '';
    $('ir-bomba').textContent = bomba === null ? '—' : (bomba >= 0.5 ? '🟢 LIGADA' : '⚪ Desligada');
    var ctx = st.last.bomba && st.last.bomba.context;
    $('ir-motivo').textContent = (ctx && ctx.motivo) || '—';

    var otm = st.otimista.modo_auto;
    var modo = (otm && Date.now() < otm.ate) ? otm.v : valor('modo_auto');
    if (otm && valor('modo_auto') === otm.v) delete st.otimista.modo_auto;
    $('ir-modo').checked = modo === 1;

    var tsMax = 0;
    Object.keys(st.last).forEach(function (k) { tsMax = Math.max(tsMax, st.last[k].timestamp); });
    var tsSens = 0;
    ['solo', 'temperatura', 'umidade_ar'].forEach(function (k) { if (st.last[k]) tsSens = Math.max(tsSens, st.last[k].timestamp); });
    if (!tsMax) setOnline('⏳ aguardando dados da Raspberry Pi', true);
    else if (Date.now() - tsSens > OFFLINE_MS) setOnline('🔴 sem dados dos sensores ' + idade(tsSens), true);
    else setOnline('🟢 online · ' + new Date(tsMax).toLocaleTimeString('pt-BR'));

    var linhas = [
      ['Umidade do solo', 'solo', '%'], ['Temperatura', 'temperatura', ' °C'], ['Umidade do ar', 'umidade_ar', '%'],
      ['Reservatório (agua)', 'agua', ''], ['Bomba', 'bomba', ''], ['Modo automático', 'modo_auto', ''],
    ];
    $('ir-diag').innerHTML = linhas.map(function (l) {
      var x = st.last[l[1]];
      var txt = x ? (Math.round(x.value * 10) / 10) + l[2] + ' · ' + idade(x.timestamp) : 'sem dados';
      return '<div><span>' + l[0] + '</span><b>' + txt + '</b></div>';
    }).join('') + '<div><span>Atualizado</span><b>' + new Date().toLocaleTimeString('pt-BR') + '</b></div>';
  }

  function polar(cx, cy, r, a) { return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; }
  function arco(cx, cy, r, a0, a1) {
    var p0 = polar(cx, cy, r, a0), p1 = polar(cx, cy, r, a1);
    return 'M' + p0[0].toFixed(2) + ' ' + p0[1].toFixed(2) + ' A' + r + ' ' + r + ' 0 ' +
      (a1 - a0 > Math.PI ? 1 : 0) + ' 1 ' + p1[0].toFixed(2) + ' ' + p1[1].toFixed(2);
  }
  function desenharGauge(g, v) {
    var cx = 80, cy = 78, r = 60, a0 = Math.PI, a1 = 2 * Math.PI;
    var frac = v === null ? 0 : Math.max(0, Math.min(1, (v - g.min) / (g.max - g.min)));
    var cor = v === null ? '#c9cbd2' : (v < g.cortes[0] ? g.cores[0] : v < g.cortes[1] ? g.cores[1] : g.cores[2]);
    var svg = '<svg viewBox="0 0 160 100" role="img" aria-label="' + g.nome + '">' +
      '<path d="' + arco(cx, cy, r, a0, a1) + '" stroke="#e6e7eb" stroke-width="16" fill="none"/>' +
      (frac > 0 ? '<path d="' + arco(cx, cy, r, a0, a0 + frac * Math.PI) + '" stroke="' + cor + '" stroke-width="16" fill="none"/>' : '') +
      '<text x="80" y="74" text-anchor="middle" font-size="22" font-weight="700" fill="#1c1d21">' +
      (v === null ? '—' : (Math.round(v * 10) / 10)) + '</text>' +
      '<text x="80" y="92" text-anchor="middle" font-size="12" fill="#6b6f7b">' + g.un + '</text>' +
      '<text x="20" y="95" text-anchor="middle" font-size="10" fill="#6b6f7b">' + g.min + '</text>' +
      '<text x="140" y="95" text-anchor="middle" font-size="10" fill="#6b6f7b">' + g.max + '</text></svg>';
    $(g.el).innerHTML = svg + '<div class="nome">' + g.nome + '</div>';
  }

  function renderGrafico() {
    var box = $('ir-grafico');
    var W = Math.max(300, box.clientWidth || 600), H = box.clientHeight || 260;
    var m = { l: 34, r: 10, t: 10, b: 24 };
    var fim = Date.now(), ini = fim - st.janelaH * 3600 * 1000;
    var X = function (t) { return m.l + (t - ini) / (fim - ini) * (W - m.l - m.r); };
    var Y = function (v) { return H - m.b - Math.max(0, Math.min(100, v)) / 100 * (H - m.t - m.b); };
    var temDados = SERIES.some(function (s) { return (st.hist[s.v] || []).length; });
    if (!temDados) {
      box.innerHTML = '<div class="vazio">Aguardando dados… (os sensores são enviados a cada 2 min)</div>';
    } else {
      var g = '';
      [0, 25, 50, 75, 100].forEach(function (v) {
        g += '<line x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + Y(v) + '" y2="' + Y(v) + '" stroke="#eef0f3"/>' +
             '<text x="' + (m.l - 6) + '" y="' + (Y(v) + 4) + '" text-anchor="end" font-size="10" fill="#6b6f7b">' + v + '</text>';
      });
      for (var i = 0; i <= 4; i++) {
        var t = ini + i * (fim - ini) / 4;
        var d = new Date(t);
        var rot = ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
        g += '<text x="' + X(t) + '" y="' + (H - 6) + '" text-anchor="' + (i === 0 ? 'start' : i === 4 ? 'end' : 'middle') +
             '" font-size="10" fill="#6b6f7b">' + rot + '</text>';
      }
      SERIES.forEach(function (s) {
        var pts = (st.hist[s.v] || []).filter(function (p) { return p.timestamp >= ini; });
        if (!pts.length) return;
        var esc = s.escala || 1, dd = '';
        pts.forEach(function (p, j) {
          var x = X(p.timestamp).toFixed(1), y = Y(p.value * esc).toFixed(1);
          if (j === 0) dd += 'M' + x + ' ' + y;
          else if (s.degrau) dd += ' H' + x + ' V' + y;
          else dd += ' L' + x + ' ' + y;
        });
        if (s.degrau) dd += ' H' + X(fim).toFixed(1);
        g += '<path d="' + dd + '" fill="none" stroke="' + s.cor + '" stroke-width="2" stroke-linejoin="round"/>';
      });
      box.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + g + '</svg>';
    }
    $('ir-legenda').innerHTML = SERIES.map(function (s) {
      return '<span><i style="background:' + s.cor + '"></i>' + s.nome + '</span>';
    }).join('');
  }

  window.addEventListener('resize', function () { renderGrafico(); });
  Object.keys(GAUGES).forEach(function (k) { desenharGauge(GAUGES[k], null); });
  renderGrafico();
  // sem o objeto Ubidots (ex.: pré-visualização local), tenta um token de teste
  if (!ub && window.__IR_TOKEN__) { st.token = window.__IR_TOKEN__; iniciar(); }
})();
