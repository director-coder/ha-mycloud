import os
import json
import re
import sys
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

SUPERVISOR_TOKEN = os.getenv("SUPERVISOR_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}

SUPERVISOR_BASE = "http://supervisor"
CORE_BASE = "http://supervisor/core"

CREDS_PATH = "/data/credentials.json"


def load_creds():
    if not os.path.exists(CREDS_PATH):
        return {}
    try:
        with open(CREDS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_creds(data):
    with open(CREDS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def addon_options():
    with open("/data/options.json", "r", encoding="utf-8") as f:
        return json.load(f)


def core_get_state(entity_id: str):
    url = f"{CORE_BASE}/api/states/{entity_id}"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


def supervisor_get_mounts():
    url = f"{SUPERVISOR_BASE}/mounts"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()["data"]


def sanitize_mount_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "share"


def build_mount_name(prefix: str, share_name: str, existing_names: set[str]) -> str:
    base = sanitize_mount_name(f"{prefix}_{share_name}")
    candidate = base
    i = 2
    while candidate in existing_names:
        candidate = f"{base}_{i}"
        i += 1
    return candidate


def extract_nas_ip(network_state: dict) -> str:
    attrs = network_state.get("attributes", {}) or {}
    return attrs.get("ip") or attrs.get("ip_address") or attrs.get("host") or ""


def extract_shares(shares_state: dict):
    attrs = shares_state.get("attributes", {}) or {}
    return attrs.get("shares") or []


def _extract_supervisor_error_text(resp: requests.Response) -> str:
    """
    Supervisor often returns JSON like:
      {"result":"error","message":"..."}
    or "ok" with "data". If not JSON, fall back to raw text.
    """
    txt = resp.text or ""
    try:
        j = resp.json()
        if isinstance(j, dict):
            if j.get("result") == "error" and j.get("message"):
                return str(j.get("message"))
            if j.get("message"):
                return str(j.get("message"))
            # some endpoints return {"error": "..."} style
            if j.get("error"):
                return str(j.get("error"))
        return txt
    except Exception:
        return txt


def _looks_like_auth_error(text: str) -> bool:
    t = (text or "").lower()
    return any(s in t for s in (
        "permission denied",
        "access denied",
        "authentication failed",
        "nt_status_logon_failure",
        "logon failure",
        "invalid credentials",
        "mount error(13)",
        "status_access_denied",
        "credentials",
        "username",
        "password",
    ))


@app.get("/")
def index():
    return """
<!doctype html><html><head><meta charset="utf-8"/>
<title>WD My Cloud Mounts</title>
<style>
body{font-family:system-ui,Arial;margin:16px}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid #ddd;padding:8px}
th{background:#f5f5f5;text-align:left}
button{padding:6px 10px;margin-right:6px}
small{color:#666}
</style></head>
<body>
<h2>WD My Cloud — Shares</h2>
<div id="meta"><small>Loading…</small></div>
<table id="tbl">
  <thead><tr><th>Share</th><th>Mount name</th><th>Status</th><th>Usage</th><th>Actions</th></tr></thead>
  <tbody></tbody>
</table>

<script>
async function api(path, opts){
  const r = await fetch(path, opts);
  const text = await r.text();
  let payload = null;
  try { payload = JSON.parse(text); } catch(e) {}

  if(!r.ok){
    // Prefer {error:"..."} if present
    if(payload && payload.error) throw new Error(payload.error);
    // Or Supervisor style {result:"error", message:"..."}
    if(payload && payload.result === 'error' && payload.message) throw new Error(payload.message);
    throw new Error(text);
  }
  return payload ?? {};
}

function btn(label, onclick){
  const b=document.createElement('button');
  b.textContent=label;
  b.onclick=onclick;
  return b;
}

async function load(){
  const data = await api('api/shares');
  document.getElementById('meta').innerHTML =
    `<small>NAS: ${data.nas_ip || '(unknown)'} | Protocol: ${data.protocol} | Default usage: ${data.default_usage}</small>`;

  const tb = document.querySelector('#tbl tbody');
  tb.innerHTML='';

  for(const row of data.rows){
    const tr=document.createElement('tr');

    const statusText = row.state || '-';

    tr.innerHTML = `<td>${row.share_name}</td>
                    <td>${row.mount_name}</td>
                    <td title="">${statusText}</td>
                    <td></td>
                    <td></td>`;

    // Usage dropdown (share / media / backup), persisted per-share in localStorage
    const usageTd = tr.children[3];
    const usageSel = document.createElement('select');
    for (const v of ['share','media','backup']) {
      const o = document.createElement('option');
      o.value = v;
      o.textContent = v;
      usageSel.appendChild(o);
    }
    const usageKey = `wdmc_usage_${row.share_name}`;
    const savedUsage = localStorage.getItem(usageKey);
    usageSel.value = savedUsage || (row.usage || 'share');
    usageSel.addEventListener('change', ()=> localStorage.setItem(usageKey, usageSel.value));
    usageTd.appendChild(usageSel);

    const statusTd = tr.children[2];
    const actions = tr.children[4];

    actions.appendChild(
      btn('Mount', async()=>{ 
        statusTd.textContent = '⏳ mounting…';
        statusTd.title = '';
        try {
          await api('api/mount', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ share_name: row.share_name, usage: usageSel.value })
          });
          await load(); // refresh from Supervisor mounts
        } catch (e) {
          const msg = String(e);
          const low = msg.toLowerCase();
          if (low.includes('authorization required') || low.includes('access denied') || low.includes('permission denied') || low.includes('logon')) {
            statusTd.textContent = '🔒 auth required';
          } else {
            statusTd.textContent = '⚠️ mount failed';
          }
          statusTd.title = msg;
          // не делаем load(), чтобы не затереть подсказку сразу
        }
      })
    );

    actions.appendChild(btn('Reload', async()=>{
      statusTd.textContent = '⏳ reloading…';
      statusTd.title = '';
      try {
        await api('api/reload', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({mount_name:row.mount_name})
        });
        await load();
      } catch(e){
        statusTd.textContent = '⚠️ reload failed';
        statusTd.title = String(e);
      }
    }));

    actions.appendChild(btn('Unmount', async()=>{
      statusTd.textContent = '⏳ unmounting…';
      statusTd.title = '';
      try {
        await api('api/unmount', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({mount_name:row.mount_name})
        });
        await load();
      } catch(e){
        statusTd.textContent = '⚠️ unmount failed';
        statusTd.title = String(e);
      }
    }));

    actions.appendChild(btn('Creds', async()=>{
      try{
        const cur = await api(`api/creds/${encodeURIComponent(row.share_name)}`);
        const u = prompt(`Username for ${row.share_name}`, cur.username || '');
        if(u === null) return;
        const p = prompt(`Password for ${row.share_name} (leave blank to keep)`, '');
        if(p === null) return;
        await api(`api/creds/${encodeURIComponent(row.share_name)}`, {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({username:u, password:p})
        });
        statusTd.textContent = '🔐 creds saved';
        statusTd.title = '';
      } catch(e){
        statusTd.textContent = '⚠️ creds failed';
        statusTd.title = String(e);
      }
    }));

    tb.appendChild(tr);
  }
}

load().catch(e=>{
  document.getElementById('meta').innerHTML = `<small style="color:#b00">${e}</small>`;
});
</script>
</body></html>
"""


@app.get("/api/shares")
def api_shares():
    opt = addon_options()

    shares_state = core_get_state(opt["shares_entity_id"])
    network_state = core_get_state(opt["network_entity_id"])

    nas_ip = extract_nas_ip(network_state)
    shares = extract_shares(shares_state)

    mounts_data = supervisor_get_mounts()
    mounts = mounts_data.get("mounts", [])

    mounts_by_share = {}
    existing_mount_names = set()

    for m in mounts:
        if m.get("name"):
            existing_mount_names.add(m["name"])
        if m.get("type") == "cifs" and m.get("share"):
            mounts_by_share[m["share"]] = m

    rows = []
    for s in shares:
        share_name = s.get("share_name")
        if not share_name:
            continue

        m = mounts_by_share.get(share_name)
        mount_name = m["name"] if m else build_mount_name("wdmc", share_name, existing_mount_names)

        rows.append({
            "share_name": share_name,
            "mount_name": mount_name,
            "state": (m.get("state") if m else None),
            "usage": (m.get("usage") if m else opt.get("default_usage", "share")),
        })

    return jsonify({
        "nas_ip": nas_ip,
        "protocol": opt.get("protocol", "cifs"),
        "default_usage": opt.get("default_usage", "share"),
        "rows": rows,
    })


@app.post("/api/mount")
def api_mount():
    opt = addon_options()
    payload = request.get_json(force=True)

    share_name = payload["share_name"]
    usage = payload.get("usage", opt.get("default_usage", "share"))

    network_state = core_get_state(opt["network_entity_id"])
    nas_ip = extract_nas_ip(network_state)
    if not nas_ip:
        return jsonify({"error": "NAS IP not found in network summary attributes"}), 400

    mounts_data = supervisor_get_mounts()
    existing_names = {m.get("name", "") for m in mounts_data.get("mounts", []) if m.get("name")}

    mount_name = build_mount_name("wdmc", share_name, existing_names)

    protocol = opt.get("protocol", "cifs")
    if protocol != "cifs":
        return jsonify({"error": "Only CIFS is implemented right now"}), 400

    creds = load_creds().get(share_name, {})
    username = creds.get("username", opt.get("cifs_username", ""))
    password = creds.get("password", opt.get("cifs_password", ""))

    body = {
        "name": mount_name,
        "usage": usage,
        "type": "cifs",
        "server": nas_ip,
        "share": share_name,
        "username": username,
        "password": password,
        "read_only": False,
    }

    r = requests.post(f"{SUPERVISOR_BASE}/mounts", headers=HEADERS, json=body, timeout=25)

    if not r.ok:
        err = _extract_supervisor_error_text(r)
        if _looks_like_auth_error(err):
            return jsonify({"error": "Authorization required: set username/password for this share."}), 401
        # Generic fail but include supervisor message
        return jsonify({"error": err[:500] if err else f"Mount failed with status {r.status_code}"}), 500

    # success
    try:
        return jsonify(r.json())
    except Exception:
        return jsonify({"ok": True})


@app.get("/api/creds/<share_name>")
def get_creds(share_name):
    creds = load_creds()
    c = creds.get(share_name, {})
    return jsonify({"username": c.get("username", ""), "has_password": bool(c.get("password"))})


@app.post("/api/creds/<share_name>")
def set_creds(share_name):
    payload = request.get_json(force=True)
    creds = load_creds()
    existing = creds.get(share_name, {})
    new_password = payload.get("password", "")
    if new_password == "":
        # keep existing password if user left blank
        new_password = existing.get("password", "")

    creds[share_name] = {
        "username": payload.get("username", ""),
        "password": new_password,
        "domain": payload.get("domain", ""),
        "vers": payload.get("vers", ""),
    }
    save_creds(creds)
    return jsonify({"ok": True})


@app.post("/api/reload")
def api_reload():
    payload = request.get_json(force=True)
    name = payload["mount_name"]
    r = requests.post(f"{SUPERVISOR_BASE}/mounts/{name}/reload", headers=HEADERS, timeout=25)
    if not r.ok:
        return jsonify({"error": _extract_supervisor_error_text(r)[:500]}), 500
    return jsonify(r.json())


@app.post("/api/unmount")
def api_unmount():
    payload = request.get_json(force=True)
    name = payload["mount_name"]
    r = requests.delete(f"{SUPERVISOR_BASE}/mounts/{name}", headers=HEADERS, timeout=25)
    if not r.ok:
        return jsonify({"error": _extract_supervisor_error_text(r)[:500]}), 500
    return jsonify(r.json())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8099)
