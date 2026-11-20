"""Single-file UI. No build step, no framework, no CDN."""

INDEX_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>voice-forge</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --line:#262b36; --ink:#e7e9ee; --muted:#8c93a3; --accent:#7c9cff; --ok:#3ecf8e; --bad:#ff6b6b; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.5 ui-sans-serif,system-ui,sans-serif; background:var(--bg); color:var(--ink); }
  header { display:flex; gap:12px; align-items:center; padding:14px 20px; border-bottom:1px solid var(--line); }
  header h1 { font-size:16px; margin:0; font-weight:600; letter-spacing:.3px; }
  .pill { font-size:12px; padding:2px 9px; border-radius:999px; border:1px solid var(--line); color:var(--muted); }
  .pill.up { color:var(--ok); border-color:#1f4d3a; }
  .pill.down { color:var(--bad); border-color:#4d2020; }
  main { max-width:1000px; margin:0 auto; padding:22px 20px 60px; display:grid; gap:18px; }
  section { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin:0 0 12px; }
  label { display:block; font-size:12px; color:var(--muted); margin:8px 0 4px; }
  input, textarea, select { width:100%; background:#0d0f14; color:var(--ink); border:1px solid var(--line); border-radius:8px; padding:9px 10px; font:inherit; }
  textarea { min-height:120px; resize:vertical; font-family:ui-monospace,monospace; font-size:13px; }
  .row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  button { background:var(--accent); color:#0b0d12; border:0; border-radius:8px; padding:9px 16px; font-weight:600; cursor:pointer; margin-top:12px; }
  button.ghost { background:transparent; color:var(--ink); border:1px solid var(--line); }
  button:disabled { opacity:.5; cursor:not-allowed; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th { text-align:left; font-size:11px; text-transform:uppercase; color:var(--muted); font-weight:600; padding-bottom:8px; }
  td { padding:8px 0; border-top:1px solid var(--line); vertical-align:middle; }
  code { font-family:ui-monospace,monospace; font-size:13px; color:var(--accent); }
  pre { background:#0d0f14; border:1px solid var(--line); border-radius:8px; padding:12px; overflow:auto; font-size:12px; }
  .actions { display:flex; gap:8px; flex-wrap:wrap; }
  .muted { color:var(--muted); font-size:13px; }
</style>
</head>
<body>
<header>
  <h1>voice-forge</h1>
  <span id="engine" class="pill">…</span>
  <span class="muted" id="engine-detail"></span>
  <span style="flex:1"></span>
  <button class="ghost" onclick="engine('up')">encender</button>
  <button class="ghost" onclick="engine('warm')">calentar</button>
  <button class="ghost" onclick="engine('down')">apagar</button>
</header>

<main>
  <section>
    <h2>Catálogo de voces</h2>
    <table><thead><tr><th>slug</th><th>nombre</th><th>origen</th><th>idioma</th><th></th></tr></thead>
    <tbody id="voices"><tr><td colspan="5" class="muted">cargando…</td></tr></tbody></table>
  </section>

  <section>
    <h2>1 · Crear voz por prompt</h2>
    <div class="row">
      <div><label>slug</label><input id="d-slug" placeholder="narrador-terror"></div>
      <div><label>nombre</label><input id="d-name" placeholder="Narrador de terror"></div>
    </div>
    <label>descripción de la voz</label>
    <textarea id="d-desc" placeholder="Hombre de 60 años, voz grave y rasposa, susurrante, ritmo lento, agotado, español neutro"></textarea>
    <div class="row">
      <div><label>candidatas</label><input id="d-count" type="number" value="4" min="1" max="8"></div>
      <div><label>elegir (índice)</label><input id="d-pick" type="number" value="0" min="0" max="7"></div>
    </div>
    <button onclick="designVoice()">crear</button>
  </section>

  <section>
    <h2>2 · Clonar una voz desde un audio</h2>
    <div class="row">
      <div><label>fichero</label><input id="a-file" type="file" accept="audio/*"></div>
      <div><label>slug</label><input id="a-slug" placeholder="mi-clon"></div>
    </div>
    <label>transcripción (opcional, mejora la fidelidad)</label>
    <input id="a-text" placeholder="Lo que dice el clip">
    <button onclick="addVoice()">clonar</button>
  </section>

  <section>
    <h2>3 · Narrar un diálogo</h2>
    <label>guion (YAML)</label>
    <textarea id="r-script">title: demo
lines:
  - voice: narrador-terror
    text: "La casa llevaba veinte años vacía."
    emotion: { melancholic: 0.45, calm: 0.60 }
    speed: 0.95
    pause_after_ms: 500
  - voice: narrador-terror
    text: "Entonces, alguien cerró la puerta."
    emotion: { afraid: 0.70, surprised: 0.30 }
    speed: 0.88
    pause_after_ms: 0</textarea>
    <button onclick="render()">narrar</button>
  </section>

  <section>
    <h2>Resultado</h2>
    <pre id="out">—</pre>
  </section>
</main>

<script>
const $ = (id) => document.getElementById(id);
const show = (data) => { $('out').textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2); };

async function api(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  let body; try { body = JSON.parse(text); } catch { body = text; }
  if (!response.ok) throw new Error((body && body.error) || body || response.statusText);
  return body;
}

async function engineStatus() {
  try {
    const s = await api('/api/engine');
    const up = s.status === 'up' || s.status === 'already-up';
    $('engine').className = 'pill ' + (up ? 'up' : 'down');
    $('engine').textContent = up ? 'motor encendido' : 'motor apagado';
    $('engine-detail').textContent = s.models ? Object.keys(s.models).join(' · ') : '';
  } catch (e) {
    $('engine').className = 'pill down'; $('engine').textContent = 'sin motor';
  }
}

async function engine(action) {
  show('…');
  try { show(await api('/api/engine/' + action, { method: 'POST' })); }
  catch (e) { show('error: ' + e.message); }
  engineStatus();
}

async function loadVoices() {
  try {
    const voices = await api('/api/voices');
    if (!voices.length) { $('voices').innerHTML = '<tr><td colspan="5" class="muted">catálogo vacío</td></tr>'; return; }
    $('voices').innerHTML = voices.map(v => `
      <tr><td><code>${v.slug}</code></td><td>${v.name}</td><td>${v.origin}</td><td>${v.language}</td>
      <td style="text-align:right"><button class="ghost" onclick="removeVoice('${v.slug}')">borrar</button></td></tr>`).join('');
  } catch (e) { $('voices').innerHTML = `<tr><td colspan="5" class="muted">${e.message}</td></tr>`; }
}

async function designVoice() {
  show('generando…');
  try {
    const body = {
      description: $('d-desc').value, slug: $('d-slug').value, name: $('d-name').value || null,
      candidates: Number($('d-count').value), pick: Number($('d-pick').value),
    };
    show(await api('/api/voices/design', { method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body) }));
    loadVoices();
  } catch (e) { show('error: ' + e.message); }
}

async function addVoice() {
  show('clonando…');
  try {
    const form = new FormData();
    const file = $('a-file').files[0];
    if (!file) throw new Error('elige un fichero');
    form.append('file', file);
    form.append('slug', $('a-slug').value);
    if ($('a-text').value) form.append('transcript', $('a-text').value);
    show(await api('/api/voices', { method:'POST', body: form }));
    loadVoices();
  } catch (e) { show('error: ' + e.message); }
}

async function render() {
  show('narrando…');
  try { show(await api('/api/dialogues/render', { method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({ script: $('r-script').value }) })); }
  catch (e) { show('error: ' + e.message); }
}

async function removeVoice(slug) {
  if (!confirm('¿borrar ' + slug + '?')) return;
  try { await api('/api/voices/' + slug, { method:'DELETE' }); loadVoices(); }
  catch (e) { show('error: ' + e.message); }
}

engineStatus(); loadVoices(); setInterval(engineStatus, 5000);
</script>
</body>
</html>
"""
