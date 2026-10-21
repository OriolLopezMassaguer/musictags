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
    position: 'fixed', right: '16px', bottom: '58px', zIndex: 60,
    maxWidth: '380px', boxShadow: '0 4px 18px rgba(0,0,0,.18)',
  });
  document.body.append(t);
  setTimeout(() => t.remove(), 4200);
}

/* ------------------------------------------------------------------ drawer */

const Drawer = {
  node: null, pre: null, label: null, dot: null, source: null,

  init() {
    this.node = document.getElementById('drawer');
    if (!this.node) return;
    this.pre = this.node.querySelector('pre');
    this.label = this.node.querySelector('.label');
    this.dot = this.node.querySelector('.dot');
    this.node.querySelector('.bar').addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      this.node.classList.toggle('open');
    });
    const stop = this.node.querySelector('.stop');
    if (stop) stop.addEventListener('click', () => api.post('/api/job/stop'));
    if (this.node.dataset.job) this.attach(this.node.dataset.job, this.node.dataset.running === '1');
  },

  open() { this.node.classList.add('open'); },

  attach(jobId, running) {
    this.open();
    this.pre.textContent = '';
    if (this.source) this.source.close();
    api.get(`/api/job?id=${encodeURIComponent(jobId)}`).then((d) => {
      this.pre.textContent = (d.lines || []).join('\n');
      this.scroll();
      this.status(d.job, d.running);
      if (running || d.running) this.follow(jobId, d.next || 0);
      else this.finish(d.job);
    });
  },

  follow(jobId, from) {
    this.source = new EventSource(`/stream/${encodeURIComponent(jobId)}?from=${from}`);
    this.source.onmessage = (e) => {
      this.pre.textContent += (this.pre.textContent ? '\n' : '') + JSON.parse(e.data);
      this.scroll();
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
    this.dot.className = 'dot' + (running ? ' run' : (job.returncode ? ' bad' : ' ok'));
    this.label.textContent = running
      ? `${job.step}: en marcha…`
      : `${job.step}: ${job.returncode === 0 ? 'terminado' : 'error ' + job.returncode} (${job.elapsed}s)`;
    document.querySelectorAll('[data-run]').forEach((b) => { b.disabled = running; });
    const stop = this.node.querySelector('.stop');
    if (stop) stop.hidden = !running;
  },

  finish(job) {
    this.status(job, false);
    if (job && job.returncode === 0) toast(`Paso «${job.step}» terminado.`, 'ok');
    else if (job) toast(`El paso «${job.step}» ha fallado (código ${job.returncode}).`, 'bad');
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

document.addEventListener('DOMContentLoaded', () => {
  Drawer.init();
  document.querySelectorAll('[data-run]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const form = btn.closest('[data-step-form]');
      runStep(btn.dataset.run, form, btn.dataset.write === '1');
    });
  });
});
