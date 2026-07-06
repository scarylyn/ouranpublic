#!/usr/bin/env python3
"""Local web workbench: track translation progress and review lines yourself.

Run:
    .venv/bin/python tools/review_server.py            # serves translated/ on :5000
    .venv/bin/python tools/review_server.py --dir translated --port 5000
Then open http://127.0.0.1:5000

  * Dashboard  -> overall + per-file progress, status breakdown.
  * File view  -> Japanese | machine draft | your English (editable) | status,
                  with filtering and pagination. Edits save straight back into
                  the JSON the ROM-insert step reads. New Text is Shift-JIS
                  sanitized on save, so you can't accidentally create text the
                  game can't store.

Single-user, localhost only. No external calls.
"""

import argparse
import glob
import json
import os
import sys

from flask import Flask, request, jsonify, render_template_string, abort

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sanitize import sanitize, check  # noqa: E402
from status_model import (is_translatable, status_of, file_progress,  # noqa: E402
                          STATUS_LABEL, STATUSES)

ENCODING = "shiftjis"
app = Flask(__name__)
DATA_DIR = "translated"
VERSION_DIRS = []
PAGE_SIZE = 40


def list_files():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(DATA_DIR, "*.json")))


def _safe_json_path(base_dir, name):
    path = os.path.abspath(os.path.join(base_dir, name))
    if not path.startswith(os.path.abspath(base_dir) + os.sep):
        abort(404)
    return path


def load(name, base_dir=None):
    base_dir = base_dir or DATA_DIR
    path = _safe_json_path(base_dir, name)
    if not os.path.exists(path):
        abort(404)
    return path, json.load(open(path, encoding=ENCODING))


def json_dirs():
    dirs = []
    seen = set()
    for d in [DATA_DIR] + VERSION_DIRS:
        if not d:
            continue
        abs_dir = os.path.abspath(d)
        if abs_dir in seen or not os.path.isdir(abs_dir):
            continue
        if glob.glob(os.path.join(abs_dir, "*.json")):
            dirs.append({"path": d, "name": os.path.basename(abs_dir) or abs_dir})
            seen.add(abs_dir)
    return dirs


def load_optional(name, base_dir):
    path = _safe_json_path(base_dir, name)
    if not os.path.exists(path):
        return None
    return json.load(open(path, encoding=ENCODING))


def speaker_for(pts, idx):
    if pts[idx].get("Type") == "Speaker":
        return ""
    for j in range(idx - 1, max(idx - 8, -1), -1):
        if pts[j].get("Type") == "Speaker":
            return pts[j].get("New Text") or pts[j].get("Original Text", "")
    return ""


# --------------------------------------------------------------------------- #
DASH = """
<!doctype html><html><head><meta charset="utf-8"><title>Ouran Translation</title>
<style>{{css}}</style></head><body>
<div class="wrap">
<h1>桜蘭 Ouran — Translation Workbench</h1>
<div class="navline">
  <b>Working folder:</b> {{data_dir}}
  {% if versions|length > 1 %}<span>Comparing {{versions|length}} folders</span>{% endif %}
</div>
<div class="overall">
  <div class="bigbar"><div class="seg approved" style="width:{{pct.approved}}%"></div>
    <div class="seg ai" style="width:{{pct.ai}}%"></div>
    <div class="seg mt" style="width:{{pct.mt}}%"></div></div>
  <div class="legend">
    <span class="k approved"></span>Approved {{tot.approved}}
    <span class="k ai"></span>AI-reviewed {{tot.ai}}
    <span class="k mt"></span>Machine {{tot.mt}}
    <span class="k untranslated"></span>Untranslated {{tot.untranslated}}
    <b>&nbsp;&nbsp;{{done}}/{{translatable}} done ({{pct_done}}%)</b>
  </div>
</div>
<table class="files"><tr><th>File</th><th>Progress</th><th>Approved</th><th>AI</th><th>MT</th><th>Left</th><th>Compare</th></tr>
{% for f in files %}
<tr><td><a href="/file/{{f.name}}">{{f.name}}</a></td>
<td>{% if f.c.translatable == 0 %}<span class="muted">No script text</span>{% else %}<div class="bar"><div class="seg approved" style="width:{{f.p.approved}}%"></div>
<div class="seg ai" style="width:{{f.p.ai}}%"></div>
<div class="seg mt" style="width:{{f.p.mt}}%"></div></div>{% endif %}</td>
<td>{{f.c.approved}}</td><td>{{f.c.ai}}</td><td>{{f.c.mt}}</td><td>{{f.c.untranslated}}</td>
<td><a href="/compare/{{f.name}}">compare</a></td></tr>
{% endfor %}
</table></div></body></html>
"""

FILEVIEW = """
<!doctype html><html><head><meta charset="utf-8"><title>{{name}}</title>
<style>{{css}}</style></head><body>
<div class="wrap">
<p><a href="/">&larr; all files</a></p>
<h2>{{name}} &nbsp;<small>{{c.done}}/{{c.translatable}} done</small></h2>
<div class="bar big"><div class="seg approved" style="width:{{p.approved}}%"></div>
<div class="seg ai" style="width:{{p.ai}}%"></div><div class="seg mt" style="width:{{p.mt}}%"></div></div>
<div class="filters">
  Filter:
  {% for fl in ['all','untranslated','mt','ai','approved'] %}
  <a class="chip {{'on' if fl==flt else ''}}" href="?filter={{fl}}&page=1">{{fl}}</a>
  {% endfor %}
  <span class="pg">page {{page}}/{{pages}}
    {% if page>1 %}<a href="?filter={{flt}}&page={{page-1}}">prev</a>{% endif %}
    {% if page<pages %}<a href="?filter={{flt}}&page={{page+1}}">next</a>{% endif %}
  </span>
  <button id="btn-translate-all" onclick="translateAllUntranslated()" class="btn-primary">Auto-translate Page Untranslated</button>
  <button onclick="translateChecked()" class="btn-primary">Translate Checked</button>
  <span class="rangebox">Range <input id="range-start" type="number" min="0" placeholder="from"> <input id="range-end" type="number" min="0" placeholder="to"> <button onclick="translateRange()">Translate Range</button></span>
  <a class="chip" href="/compare/{{name}}">compare versions</a>
</div>
<table class="lines">
<tr><th><input type="checkbox" onclick="toggleChecks(this)"></th><th>#</th><th>Type / Speaker</th><th>Japanese</th><th>Machine draft</th><th>English (editable)</th><th>Status</th></tr>
{% if rows|length == 0 %}
<tr><td colspan="7" class="empty">No translatable script text in this file. It may be an asset-control script that references graphics.</td></tr>
{% endif %}
{% for r in rows %}
<tr id="r{{r.id}}" class="st-{{r.status}}">
  <td><input class="linecheck" type="checkbox" value="{{r.id}}"></td>
  <td class="id">{{r.id}}</td>
  <td class="meta"><b>{{r.type}}</b>{% if r.speaker %}<br><span class="spk">{{r.speaker}}</span>{% endif %}</td>
  <td class="jp">{{r.jp}}</td>
  <td class="mt">{{r.mt}}</td>
  <td class="en"><textarea data-id="{{r.id}}">{{r.en}}</textarea>
      <div class="rowbtns">
      <button onclick="autoTranslate({{r.id}})">🤖 auto</button>
      <button onclick="save({{r.id}},'approved')">✓ approve</button>
      <button onclick="save({{r.id}},'ai')">save</button>
      <span class="saved" id="s{{r.id}}"></span></div></td>
  <td><select data-id="{{r.id}}" onchange="save({{r.id}}, this.value)">
    {% for s in statuses %}<option value="{{s}}" {{'selected' if s==r.status else ''}}>{{labels[s]}}</option>{% endfor %}
  </select></td>
</tr>
{% endfor %}
</table></div>
<script>
async function save(id, status){
  const ta = document.querySelector('textarea[data-id="'+id+'"]');
  const r = await fetch('/api/save', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({file:'{{name}}', id:id, new_text:ta.value, status:status})});
  const j = await r.json();
  const tag = document.getElementById('s'+id);
  if(j.ok){ ta.value = j.new_text;
    document.getElementById('r'+id).className = 'st-'+j.status;
    tag.textContent='saved'; tag.className='saved ok'; }
  else { tag.textContent=j.error; tag.className='saved err'; }
  setTimeout(()=>{tag.textContent='';}, 2500);
}

async function autoTranslate(id) {
  const tag = document.getElementById('s'+id);
  tag.textContent = 'translating...';
  tag.className = 'saved info';
  try {
    const r = await fetch('/api/translate_line', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({file: '{{name}}', id: id})
    });
    const j = await r.json();
    if(j.ok){
      const ta = document.querySelector('textarea[data-id="'+id+'"]');
      ta.value = j.text;
      document.getElementById('r'+id).className = 'st-'+j.status;
      tag.textContent = 'translated';
      tag.className = 'saved ok';
    } else {
      tag.textContent = j.error || 'error';
      tag.className = 'saved err';
    }
  } catch(e) {
    tag.textContent = e.message || 'connection error';
    tag.className = 'saved err';
  }
  setTimeout(()=>{tag.textContent='';}, 2500);
}

async function translateAllUntranslated() {
  const btn = document.getElementById('btn-translate-all');
  const rows = Array.from(document.querySelectorAll('tr[class*="st-untranslated"]'));
  if (rows.length === 0) {
    alert('No untranslated lines on this page!');
    return;
  }
  if (!confirm(`Do you want to auto-translate all ${rows.length} untranslated lines on this page?`)) {
    return;
  }
  
  btn.disabled = true;
  let count = 0;
  for (const row of rows) {
    const id = row.id.replace('r', '');
    btn.textContent = `Translating... (${count}/${rows.length})`;
    
    const tag = document.getElementById('s'+id);
    tag.textContent = 'translating...';
    tag.className = 'saved info';
    try {
      const r = await fetch('/api/translate_line', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({file: '{{name}}', id: parseInt(id)})
      });
      const j = await r.json();
      if(j.ok){
        const ta = document.querySelector('textarea[data-id="'+id+'"]');
        ta.value = j.text;
        row.className = 'st-'+j.status;
        tag.textContent = 'translated';
        tag.className = 'saved ok';
        count++;
      } else {
        tag.textContent = j.error || 'error';
        tag.className = 'saved err';
        break; 
      }
    } catch(e) {
      tag.textContent = e.message || 'connection error';
      tag.className = 'saved err';
      break;
    }
    setTimeout(()=>{tag.textContent='';}, 2500);
  }
  btn.disabled = false;
  btn.textContent = `🤖 Auto-translate Page Untranslated`;
  alert(`Completed translating ${count} lines.`);
}

function checkedIds() {
  return Array.from(document.querySelectorAll('.linecheck:checked')).map(cb => parseInt(cb.value));
}

function toggleChecks(master) {
  document.querySelectorAll('.linecheck').forEach(cb => cb.checked = master.checked);
}

async function translateChecked() {
  const ids = checkedIds();
  if (!ids.length) {
    alert('Select at least one line first.');
    return;
  }
  if (!confirm(`Translate ${ids.length} selected lines?`)) {
    return;
  }
  for (const id of ids) {
    await autoTranslate(id);
  }
}

async function translateRange() {
  const start = parseInt(document.getElementById('range-start').value);
  const end = parseInt(document.getElementById('range-end').value);
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) {
    alert('Enter a valid start and end line number.');
    return;
  }
  if (!confirm(`Translate lines ${start} through ${end}?`)) {
    return;
  }
  for (let id = start; id <= end; id++) {
    const tag = document.getElementById('s'+id);
    if (tag) {
      await autoTranslate(id);
    } else {
      await fetch('/api/translate_line', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({file: '{{name}}', id: id})
      });
    }
  }
}
</script></body></html>
"""

COMPARE = """
<!doctype html><html><head><meta charset="utf-8"><title>Compare {{name}}</title>
<style>{{css}}</style></head><body>
<div class="wrap wide">
<p><a href="/">&larr; all files</a> &nbsp; <a href="/file/{{name}}">edit {{name}}</a></p>
<h2>{{name}}</h2>
<form class="filters" method="get">
  <label>Left <select name="left">{% for v in versions %}<option value="{{v.path}}" {{'selected' if v.path==left else ''}}>{{v.name}}</option>{% endfor %}</select></label>
  <label>Right <select name="right">{% for v in versions %}<option value="{{v.path}}" {{'selected' if v.path==right else ''}}>{{v.name}}</option>{% endfor %}</select></label>
  <label>Filter <select name="filter">
    {% for fl in ['all','different','untranslated','mt','ai','approved'] %}<option value="{{fl}}" {{'selected' if fl==flt else ''}}>{{fl}}</option>{% endfor %}
  </select></label>
  <button>Apply</button>
  <span class="pg">page {{page}}/{{pages}}
    {% if page>1 %}<a href="?left={{left}}&right={{right}}&filter={{flt}}&page={{page-1}}">prev</a>{% endif %}
    {% if page<pages %}<a href="?left={{left}}&right={{right}}&filter={{flt}}&page={{page+1}}">next</a>{% endif %}
  </span>
  <button type="button" class="btn-primary" onclick="translateChecked()">Translate Checked In Working Folder</button>
  <span class="rangebox">Range <input id="range-start" type="number" min="0" placeholder="from"> <input id="range-end" type="number" min="0" placeholder="to"> <button type="button" onclick="translateRange()">Translate Range</button></span>
</form>
<table class="lines compare">
<tr><th><input type="checkbox" onclick="toggleChecks(this)"></th><th>#</th><th>Type</th><th>Japanese</th><th>{{left_name}}</th><th>{{right_name}}</th><th>Working English</th><th>Status</th></tr>
{% for r in rows %}
<tr id="r{{r.id}}" class="st-{{r.status}}">
  <td><input class="linecheck" type="checkbox" value="{{r.id}}"></td>
  <td class="id">{{r.id}}</td>
  <td class="meta"><b>{{r.type}}</b>{% if r.speaker %}<br><span class="spk">{{r.speaker}}</span>{% endif %}</td>
  <td class="jp">{{r.jp}}</td>
  <td class="variant"><div>{{r.left_text}}</div>{% if r.left_text %}<button onclick="copyVariant({{r.id}}, 'left')">Use left</button>{% endif %}</td>
  <td class="variant"><div>{{r.right_text}}</div>{% if r.right_text %}<button onclick="copyVariant({{r.id}}, 'right')">Use right</button>{% endif %}</td>
  <td class="en"><textarea data-id="{{r.id}}">{{r.en}}</textarea>
    <div class="rowbtns"><button onclick="save({{r.id}}, 'ai')">save</button><button onclick="save({{r.id}}, 'approved')">approve</button><span class="saved" id="s{{r.id}}"></span></div></td>
  <td>{{r.status}}</td>
</tr>
{% endfor %}
</table></div>
<script>
const currentFile = {{name|tojson}};
const leftDir = {{left|tojson}};
const rightDir = {{right|tojson}};

function toggleChecks(master) {
  document.querySelectorAll('.linecheck').forEach(cb => cb.checked = master.checked);
}

function checkedIds() {
  return Array.from(document.querySelectorAll('.linecheck:checked')).map(cb => parseInt(cb.value));
}

async function save(id, status){
  const ta = document.querySelector('textarea[data-id="'+id+'"]');
  const r = await fetch('/api/save', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({file:currentFile, id:id, new_text:ta.value, status:status})});
  const j = await r.json();
  const tag = document.getElementById('s'+id);
  if(j.ok){ ta.value = j.new_text; tag.textContent='saved'; tag.className='saved ok'; }
  else { tag.textContent=j.error; tag.className='saved err'; }
  setTimeout(()=>{tag.textContent='';}, 2500);
}

async function copyVariant(id, side) {
  const dir = side === 'left' ? leftDir : rightDir;
  const r = await fetch('/api/copy_variant', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({file:currentFile, id:id, dir:dir})});
  const j = await r.json();
  const tag = document.getElementById('s'+id);
  if(j.ok){
    document.querySelector('textarea[data-id="'+id+'"]').value = j.new_text;
    tag.textContent='copied';
    tag.className='saved ok';
  } else {
    tag.textContent=j.error || 'error';
    tag.className='saved err';
  }
  setTimeout(()=>{tag.textContent='';}, 2500);
}

async function translateLine(id) {
  const tag = document.getElementById('s'+id);
  tag.textContent = 'translating...';
  tag.className = 'saved info';
  const r = await fetch('/api/translate_line', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({file:currentFile, id:id})});
  const j = await r.json();
  if(j.ok){
    document.querySelector('textarea[data-id="'+id+'"]').value = j.text;
    tag.textContent='translated';
    tag.className='saved ok';
  } else {
    tag.textContent=j.error || 'error';
    tag.className='saved err';
  }
  setTimeout(()=>{tag.textContent='';}, 2500);
}

async function translateChecked() {
  const ids = checkedIds();
  if (!ids.length) {
    alert('Select at least one line first.');
    return;
  }
  if (!confirm(`Translate ${ids.length} selected lines in the working folder?`)) {
    return;
  }
  for (const id of ids) {
    await translateLine(id);
  }
}

async function translateRange() {
  const start = parseInt(document.getElementById('range-start').value);
  const end = parseInt(document.getElementById('range-end').value);
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) {
    alert('Enter a valid start and end line number.');
    return;
  }
  if (!confirm(`Translate lines ${start} through ${end} in the working folder?`)) {
    return;
  }
  for (let id = start; id <= end; id++) {
    const tag = document.getElementById('s'+id);
    if (tag) {
      await translateLine(id);
    } else {
      await fetch('/api/translate_line', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({file:currentFile, id:id})});
    }
  }
}
</script></body></html>
"""

CSS = """
*{box-sizing:border-box} body{font:14px/1.5 system-ui,sans-serif;margin:0;background:#f4f4f6;color:#1a1a1f}
.wrap{max-width:1200px;margin:0 auto;padding:24px}
h1{font-weight:700} a{color:#4338ca;text-decoration:none} a:hover{text-decoration:underline}
.bigbar,.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:#e2e2e8}
.bar.big,.bigbar{height:20px}
.seg{height:100%} .seg.approved{background:#16a34a}.seg.ai{background:#0ea5e9}.seg.mt{background:#f59e0b}
.overall{margin:16px 0 28px} .legend{margin-top:8px;color:#444}
.k{display:inline-block;width:11px;height:11px;border-radius:3px;margin:0 5px 0 14px;vertical-align:middle}
.k.approved{background:#16a34a}.k.ai{background:#0ea5e9}.k.mt{background:#f59e0b}.k.untranslated{background:#cbd5e1}
table{border-collapse:collapse;width:100%;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.07)}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #eee;vertical-align:top}
th{background:#fafafc;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#666}
.files td .bar{width:220px}
 .navline{display:flex;gap:18px;color:#555;margin-top:-8px}.muted,.empty{color:#777}
.lines .jp{font-size:15px;max-width:240px} .lines .mt{color:#777;max-width:230px}
.wide{max-width:1600px}.compare .jp{max-width:310px}.compare textarea{width:260px}.variant{max-width:300px;white-space:pre-wrap}
.lines .id{color:#aaa;font-variant-numeric:tabular-nums} .meta .spk{color:#0ea5e9;font-size:12px}
textarea{width:300px;min-height:46px;font:14px system-ui;padding:6px;border:1px solid #d4d4dc;border-radius:6px;resize:vertical}
.rowbtns{margin-top:4px} button{font-size:12px;padding:3px 8px;margin-right:4px;border:1px solid #c7c7d1;border-radius:5px;background:#fff;cursor:pointer}
button:hover{background:#f0f0f5}
.saved{font-size:12px} .saved.ok{color:#16a34a} .saved.err{color:#dc2626} .saved.info{color:#0ea5e9}
.btn-primary{background:#4338ca !important;color:#fff !important;border-color:#4338ca !important}
.btn-primary:hover{background:#3730a3 !important;border-color:#3730a3 !important}
.filters{margin:14px 0;display:flex;align-items:center;flex-wrap:wrap;gap:10px} .chip{display:inline-block;padding:3px 11px;border-radius:14px;background:#e6e6ee;font-size:13px}
.rangebox{display:inline-flex;align-items:center;gap:5px}.rangebox input{width:76px;padding:4px;border:1px solid #d4d4dc;border-radius:5px}
.chip.on{background:#4338ca;color:#fff} .pg{margin-left:14px;color:#666} .pg a{margin:0 6px}
tr.st-untranslated{background:#fff} tr.st-mt td.en textarea{border-color:#f59e0b}
tr.st-ai td.en textarea{border-color:#0ea5e9} tr.st-approved{background:#f3fbf5}
select{padding:4px;border-radius:5px;border:1px solid #d4d4dc}
small{color:#888;font-weight:400}
"""

translation_engine = None
speaker_map = None
subs = None


def get_engine():
    global translation_engine, speaker_map, subs
    if translation_engine is None:
        from translate import load_glossary, GLOSSARY_PATH, ArgosEngine, SugoiApiEngine, SugoiLocalEngine
        
        backend = app.config.get("TRANSLATE_BACKEND", "argos")
        glossary_path = app.config.get("GLOSSARY_PATH", GLOSSARY_PATH)
        no_glossary = app.config.get("NO_GLOSSARY", False)
        
        sm, l_subs = load_glossary(glossary_path)
        speaker_map = sm
        subs = [] if no_glossary else l_subs
        
        if backend == "argos":
            translation_engine = ArgosEngine()
        elif backend == "sugoi-api":
            translation_engine = SugoiApiEngine(
                api_url=app.config.get("API_URL"),
                model_name=app.config.get("API_MODEL"),
                api_key=app.config.get("API_KEY"),
                system_prompt=app.config.get("SYSTEM_PROMPT")
            )
        elif backend == "sugoi-local":
            translation_engine = SugoiLocalEngine(
                model_path=app.config.get("MODEL_PATH"),
                repo_id=app.config.get("REPO_ID"),
                filename=app.config.get("MODEL_FILENAME"),
                n_gpu_layers=app.config.get("N_GPU_LAYERS"),
                system_prompt=app.config.get("SYSTEM_PROMPT")
            )
    return translation_engine, speaker_map, subs


@app.route("/")
def dashboard():
    files = []
    tot = {s: 0 for s in STATUSES}
    translatable = 0
    for name in list_files():
        d = json.load(open(os.path.join(DATA_DIR, name), encoding=ENCODING))
        c = file_progress(d["pointers"])
        for s in STATUSES:
            tot[s] += c[s]
        translatable += c["translatable"]
        t = max(c["translatable"], 1)
        p = {s: round(c[s] / t * 100, 1) for s in STATUSES}
        files.append({"name": name, "c": c, "p": p})
    T = max(translatable, 1)
    pct = {s: round(tot[s] / T * 100, 1) for s in STATUSES}
    done = translatable - tot["untranslated"]
    return render_template_string(DASH, css=CSS, files=files, tot=tot, pct=pct,
                                  translatable=translatable, done=done,
                                  pct_done=round(done / T * 100, 1),
                                  data_dir=DATA_DIR, versions=json_dirs())


@app.route("/file/<name>")
def fileview(name):
    path, d = load(name)
    pts = d["pointers"]
    flt = request.args.get("filter", "all")
    page = max(int(request.args.get("page", 1)), 1)
    rows_all = []
    for idx, p in enumerate(pts):
        if not is_translatable(p):
            continue
        st = status_of(p)
        if flt != "all" and st != flt:
            continue
        rows_all.append({
            "id": idx, "type": p.get("Type"), "speaker": speaker_for(pts, idx),
            "jp": p["Original Text"], "mt": p.get("MT Text", ""),
            "en": p.get("New Text", ""), "status": st,
        })
    pages = max((len(rows_all) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(page, pages)
    rows = rows_all[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    c = file_progress(pts)
    t = max(c["translatable"], 1)
    p = {s: round(c[s] / t * 100, 1) for s in STATUSES}
    return render_template_string(FILEVIEW, css=CSS, name=name, rows=rows, c=c, p=p,
                                  flt=flt, page=page, pages=pages,
                                  statuses=STATUSES, labels=STATUS_LABEL)


def version_name(path):
    abs_path = os.path.abspath(path)
    for version in json_dirs():
        if os.path.abspath(version["path"]) == abs_path:
            return version["name"]
    return os.path.basename(abs_path) or abs_path


def compare_text(pointers, idx):
    if not pointers or idx >= len(pointers):
        return ""
    pointer = pointers[idx]
    return pointer.get("New Text") or pointer.get("MT Text", "")


@app.route("/compare/<name>")
def compare(name):
    versions = json_dirs()
    if not versions:
        abort(404)
    left = request.args.get("left") or versions[0]["path"]
    right = request.args.get("right") or (versions[1]["path"] if len(versions) > 1 else versions[0]["path"])
    valid_dirs = {os.path.abspath(v["path"]) for v in versions}
    if os.path.abspath(left) not in valid_dirs or os.path.abspath(right) not in valid_dirs:
        abort(404)

    _, base = load(name)
    left_data = load_optional(name, left)
    right_data = load_optional(name, right)
    base_pts = base["pointers"]
    left_pts = left_data["pointers"] if left_data else None
    right_pts = right_data["pointers"] if right_data else None
    flt = request.args.get("filter", "all")
    page = max(int(request.args.get("page", 1)), 1)

    rows_all = []
    for idx, pointer in enumerate(base_pts):
        if not is_translatable(pointer):
            continue
        st = status_of(pointer)
        left_text = compare_text(left_pts, idx)
        right_text = compare_text(right_pts, idx)
        if flt == "different" and left_text == right_text:
            continue
        if flt in STATUS_LABEL and st != flt:
            continue
        rows_all.append({
            "id": idx,
            "type": pointer.get("Type", ""),
            "speaker": speaker_for(base_pts, idx),
            "status": st,
            "jp": pointer.get("Original Text", ""),
            "left_text": left_text,
            "right_text": right_text,
            "en": pointer.get("New Text", ""),
        })

    pages = max((len(rows_all) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(page, pages)
    rows = rows_all[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    return render_template_string(
        COMPARE,
        css=CSS,
        name=name,
        versions=versions,
        left=left,
        right=right,
        left_name=version_name(left),
        right_name=version_name(right),
        flt=flt,
        rows=rows,
        page=page,
        pages=pages,
    )


@app.route("/api/save", methods=["POST"])
def save():
    body = request.get_json(force=True)
    name = body.get("file")
    idx = body.get("id")
    new_text = body.get("new_text", "")
    status = body.get("status", "ai")
    path, d = load(name)
    pts = d["pointers"]
    if not isinstance(idx, int) or idx < 0 or idx >= len(pts):
        return jsonify(ok=False, error="bad id"), 400
    bad = check(new_text)
    if bad:
        return jsonify(ok=False, error="unsupported char: " + " ".join(bad)), 400
    clean = sanitize(new_text)
    pts[idx]["New Text"] = clean
    pts[idx]["Status"] = status if status in STATUS_LABEL else "ai"
    json.dump(d, open(path, "w", encoding=ENCODING), ensure_ascii=False, indent=4)
    return jsonify(ok=True, new_text=clean, status=pts[idx]["Status"])


@app.route("/api/copy_variant", methods=["POST"])
def copy_variant():
    body = request.get_json(force=True)
    name = body.get("file")
    idx = body.get("id")
    source_dir = body.get("dir")
    valid_dirs = {os.path.abspath(v["path"]) for v in json_dirs()}
    if os.path.abspath(source_dir or "") not in valid_dirs:
        return jsonify(ok=False, error="bad source folder"), 400
    source = load_optional(name, source_dir)
    if source is None:
        return jsonify(ok=False, error="source file missing"), 404
    path, target = load(name)
    source_pts = source["pointers"]
    target_pts = target["pointers"]
    if not isinstance(idx, int) or idx < 0 or idx >= len(target_pts) or idx >= len(source_pts):
        return jsonify(ok=False, error="bad id"), 400
    new_text = source_pts[idx].get("New Text") or source_pts[idx].get("MT Text", "")
    bad = check(new_text)
    if bad:
        return jsonify(ok=False, error="unsupported char: " + " ".join(bad)), 400
    clean = sanitize(new_text)
    target_pts[idx]["New Text"] = clean
    target_pts[idx]["Status"] = "ai"
    json.dump(target, open(path, "w", encoding=ENCODING), ensure_ascii=False, indent=4)
    return jsonify(ok=True, new_text=clean, status="ai")


@app.route("/api/translate_line", methods=["POST"])
def translate_line():
    body = request.get_json(force=True)
    name = body.get("file")
    idx = body.get("id")
    path, d = load(name)
    pts = d["pointers"]
    if not isinstance(idx, int) or idx < 0 or idx >= len(pts):
        return jsonify(ok=False, error="bad id"), 400
    
    p = pts[idx]
    is_spk = p.get("Type") == "Speaker"
    
    try:
        engine, smap, lsubs = get_engine()
        from translate import translate_string
        new_text = translate_string(p["Original Text"], engine, smap, lsubs, is_spk)
        clean = sanitize(new_text)
        p["MT Text"] = clean
        p["New Text"] = clean
        p["Status"] = "mt"
        json.dump(d, open(path, "w", encoding=ENCODING), ensure_ascii=False, indent=4)
        return jsonify(ok=True, text=clean, status="mt")
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


def main(argv=None):
    global DATA_DIR, VERSION_DIRS
    from translate import GLOSSARY_PATH
    ap = argparse.ArgumentParser(description="Translation review web workbench")
    ap.add_argument("--dir", default="translated", help="dir of JSON files to review")
    ap.add_argument("--compare-dir", action="append", default=[],
                    help="additional JSON directory to show in the side-by-side compare view")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--host", default="127.0.0.1")
    
    ap.add_argument("--glossary", default=GLOSSARY_PATH)
    ap.add_argument("--no-glossary", action="store_true",
                    help="Do not pre-substitute glossary terms in the prompt (recommended for smart LLMs like Sugoi)")
    ap.add_argument("--backend", default="argos", choices=["argos", "sugoi-api", "sugoi-local"],
                    help="Translation backend to use: 'argos' (default Argos Translate), "
                         "'sugoi-api' (Sugoi 14B or generic LLM via local API like Ollama/llama.cpp/LM Studio), "
                         "or 'sugoi-local' (local .gguf file via llama-cpp-python)")
    ap.add_argument("--api-url", default="http://localhost:11434/v1",
                    help="API URL for 'sugoi-api' backend (default: http://localhost:11434/v1 for Ollama)")
    ap.add_argument("--api-model", default="sugoi-14b",
                    help="Model name for 'sugoi-api' backend (default: sugoi-14b)")
    ap.add_argument("--api-key", default="sk-dummy",
                    help="API key for 'sugoi-api' backend (optional)")
    ap.add_argument("--model-path", help="Path to the .gguf model file for 'sugoi-local' backend")
    ap.add_argument("--repo-id", help="HuggingFace repository ID for 'sugoi-local' backend (e.g. sugoitoolkit/Sugoi-14B-Ultra-GGUF)")
    ap.add_argument("--model-filename", help="Model filename on HuggingFace for 'sugoi-local' backend (e.g. Sugoi-14B-Ultra-F16.gguf)")
    ap.add_argument("--n-gpu-layers", type=int, default=-1,
                    help="Number of GPU layers to offload for 'sugoi-local' backend (-1 for all, 0 for CPU)")
    ap.add_argument("--system-prompt", help="Custom system prompt to override the default localizer prompt")
    args = ap.parse_args(argv)
    
    DATA_DIR = args.dir
    VERSION_DIRS = args.compare_dir
    app.config["TRANSLATE_BACKEND"] = args.backend
    app.config["GLOSSARY_PATH"] = args.glossary
    app.config["NO_GLOSSARY"] = args.no_glossary
    app.config["API_URL"] = args.api_url
    app.config["API_MODEL"] = args.api_model
    app.config["API_KEY"] = args.api_key
    app.config["MODEL_PATH"] = args.model_path
    app.config["REPO_ID"] = args.repo_id
    app.config["MODEL_FILENAME"] = args.model_filename
    app.config["N_GPU_LAYERS"] = args.n_gpu_layers
    app.config["SYSTEM_PROMPT"] = args.system_prompt
    
    if VERSION_DIRS:
        print("compare dirs: " + ", ".join(os.path.abspath(d) for d in VERSION_DIRS))
    print(f"serving {os.path.abspath(DATA_DIR)} at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
