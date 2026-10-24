/* Shared helpers: the run drawer, the step forms, and small DOM utilities. */

const api = {
  async get(url) { const r = await fetch(url); return r.json(); },
  async post(url, body) {
    const r = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    return r.json();
  },
};

const el = (tag, attrs = {}, kids = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v);
  }
  for (const kid of [].concat(kids)) if (kid) n.append(kid);
  return n;
};

function toast(msg, kind = 'ok') {
  const t = el('div', { class: `note ${kind}`, text: msg });
  Object.assign(t.style, {
    position: 'fixed', right: '16px', top: '60px', zIndex: 60,
    maxWidth: '380px', boxShadow: '0 4px 18px rgba(0,0,0,.18)',
  });
  document.body.append(t);
  setTimeout(() => t.remove(), 4200);
}

/* ------------------------------------------------------------------ drawer */

const Drawer = {
  node: null, pre: null, label: null, dot: null, source: null, stopBtn: null,
  asked: false,          // "Parar" already pressed: the next press forces

  init() {
    this.node = document.getElementById('drawer');
    if (!this.node) return;
    this.pre = this.node.querySelector('pre');
    this.label = this.node.querySelector('.label');
    this.dot = this.node.querySelector('.dot');
    this.stopBtn = this.node.querySelector('.stop');
    if (this.stopBtn) this.stopBtn.addEventListener('click', () => this.stop());
    if (this.node.dataset.job) {
      this.attach(this.node.dataset.job, this.node.dataset.running === '1', false);
    }
  },

  // The log is cached per tab so a page change repaints it at once instead of blanking.
  cached(jobId) {
    try { const c = JSON.parse(sessionStorage.getItem('drawerLog')); return c && c.id === jobId ? c.text : null; }
    catch (e) { return null; }
  },
  cache(jobId) {
    try { sessionStorage.setItem('drawerLog', JSON.stringify({ id: jobId, text: this.pre.textContent })); }
    catch (e) { /* storage blocked or full */ }
  },

  /* First press asks the script to stop at its next safe point; the second
     one kills it, which is only ever needed if it is wedged. */
  async stop() {
    const force = this.asked;
    if (force && !confirm(
      'Matar el proceso ahora mismo.\n\nSi está escribiendo tags, el fichero que '
      + 'tenga entre manos puede quedar a medias. Solo si se ha quedado colgado.'
      + '\n\n¿Matarlo?')) return;
    const d = await api.post('/api/job/stop', { force });
    if (!d.ok) { toast(d.error || 'No se ha podido parar.', 'bad'); return; }
    this.asked = true;
    if (this.stopBtn) this.stopBtn.textContent = 'Matar';
    toast(force ? 'Proceso matado.' : 'Parando en el siguiente punto seguro…', 'warn');
  },

  // fresh=false: re-attaching after a page load. A job that already ended is only
  // displayed, not "finished" again (no repeated toast, no onJobDone reload).
  attach(jobId, running, fresh = true) {
    this.asked = false;
    if (this.stopBtn) this.stopBtn.textContent = 'Parar';
    const old = fresh ? null : this.cached(jobId);
    this.pre.textContent = old || '';
    if (old) this.scroll();
    if (this.source) this.source.close();
    api.get(`/api/job?id=${encodeURIComponent(jobId)}`).then((d) => {
      const text = (d.lines || []).join('\n');
      if (text !== this.pre.textContent) { this.pre.textContent = text; this.scroll(); }
      this.cache(jobId);
      this.status(d.job, d.running);
      if (running || d.running) this.follow(jobId, d.next || 0);
      else if (fresh) this.finish(d.job);
    });
  },

  follow(jobId, from) {
    this.source = new EventSource(`/stream/${encodeURIComponent(jobId)}?from=${from}`);
    this.source.onmessage = (e) => {
      this.pre.textContent += (this.pre.textContent ? '\n' : '') + JSON.parse(e.data);
      this.scroll();
      this.cache(jobId);
    };
    this.source.addEventListener('done', (e) => {
      this.source.close();
      this.source = null;
      this.finish(JSON.parse(e.data));
    });
    this.source.onerror = () => { if (this.source) { this.source.close(); this.source = null; } };
  },

  status(job, running) {
    if (!job) return;
    const stopped = job.stopped || (!running && job.returncode === 130);
    this.dot.className = 'dot'
      + (running ? ' run' : (stopped ? '' : (job.returncode ? ' bad' : ' ok')));
    const name = job.total > 1
      ? `${job.label} ${job.index + 1}/${job.total} · ${job.step}`
      : job.step;
    const how = stopped ? 'detenido'
      : (job.returncode === 0 ? 'terminado' : `error ${job.returncode}`);
    this.label.textContent = running
      ? `${name}: en marcha…${job.stopping ? ' (parando)' : ''}`
      : `${name}: ${how} (${job.elapsed}s)`;
    document.querySelectorAll('[data-run],[data-run-chain]')
      .forEach((b) => { b.disabled = running; });
    if (this.stopBtn) this.stopBtn.hidden = !running;
  },

  finish(job) {
    this.status(job, false);
    if (!job) return;
    const what = job.total > 1 ? `«${job.label}»` : `El paso «${job.step}»`;
    if (job.stopped || job.returncode === 130) toast(`${what}: detenido.`, 'warn');
    else if (job.returncode === 0) toast(`${what}: terminado.`, 'ok');
    else toast(`${what} ha fallado en «${job.step}» (código ${job.returncode}).`, 'bad');
    setTimeout(() => { if (window.onJobDone) window.onJobDone(job); }, 200);
  },

  scroll() { this.pre.scrollTop = this.pre.scrollHeight; },
};

/* -------------------------------------------------------------- step forms */

function stepParams(form) {
  const params = {};
  form.querySelectorAll('[data-param]').forEach((input) => {
    const name = input.dataset.param;
    if (input.type === 'checkbox' && input.dataset.multi) {
      params[name] = params[name] || [];
      if (input.checked) params[name].push(input.value);
    } else if (input.type === 'checkbox') {
      params[name] = input.checked;
    } else {
      params[name] = input.value;
    }
  });
  return params;
}

async function runStep(stepId, form, write) {
  if (write && !confirm(
    'Esto escribe los tags en los ficheros de música.\n\n'
    + 'Se guarda un registro undo_*.jsonl antes de tocar nada, pero conviene '
    + 'haber hecho antes una simulación.\n\n¿Seguir?')) return;
  const body = { params: form ? stepParams(form) : {}, write: !!write };
  if (write) body.confirm = 'APLICAR';
  const d = await api.post(`/api/run/${stepId}`, body);
  if (!d.ok) { toast(d.error || 'No se ha podido lanzar.', 'bad'); return; }
  Drawer.attach(d.job.id, true);
}

/* The chain takes each step's own options from the forms already on the page,
   so what you see under "Opciones y ejecución" is what it runs. */
function allStepParams() {
  const out = {};
  document.querySelectorAll('[data-step-form]').forEach((f) => {
    out[f.dataset.step] = stepParams(f);
  });
  return out;
}

async function runChain(chainId) {
  if (!confirm(
    'Se ejecutan todos los pasos y el último ESCRIBE los tags en los ficheros de música.\n\n'
    + 'Se guarda un registro undo_*.jsonl antes de tocar nada.\n\n¿Seguir?')) return;
  const d = await api.post(`/api/run-chain/${chainId}`, { params: allStepParams(), confirm: 'APLICAR' });
  if (!d.ok) { toast(d.error || 'No se ha podido lanzar.', 'bad'); return; }
  Drawer.attach(d.job.id, true);
}

document.addEventListener('DOMContentLoaded', () => {
  Drawer.init();
  document.querySelectorAll('[data-run]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const form = btn.closest('[data-step-form]');
      runStep(btn.dataset.run, form, btn.dataset.write === '1');
    });
  });
  document.querySelectorAll('[data-run-chain]').forEach((btn) => {
    btn.addEventListener('click', () => runChain(btn.dataset.runChain));
  });
});
