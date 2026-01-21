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
    with open(CREDS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_creds(data):
    with open(CREDS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def addon_options():
    # Supervisor injects add-on options into /data/options.json
    import json
    with open("/data/options.json", "r", encoding="utf-8") as f:
        return json.load(f)

def core_get_state(entity_id: str):
    print("DEBUG: SUPERVISOR_TOKEN len =", len(SUPERVISOR_TOKEN), file=sys.stderr, flush=True)

    test = requests.get(
        f"{CORE_BASE}/api/config",
        headers=HEADERS,
        timeout=10
    )
    print(
        "DEBUG: core/api/config status =",
        test.status_code,
        test.text[:200],
        file=sys.stderr,
        flush=True
    )

    url = f"{CORE_BASE}/api/states/{entity_id}"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()

def supervisor_get_mounts():
    r = requests.get("http://supervisor/info", headers=HEADERS, timeout=10)
    print("DEBUG supervisor/info", r.status_code, r.text[:120], file=sys.stderr, flush=True)

    url = f"{SUPERVISOR_BASE}/mounts"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()["data"]  # { mounts: [...], default_backup_mount: ... }

def sanitize_mount_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = "share"
    return name

def build_mount_name(prefix: str, share_name: str, existing_names: set[str]) -> str:
    base = sanitize_mount_name(f"{prefix}_{share_name}")
    candidate = base
    i = 2
    while candidate in existing_names:
        candidate = f"{base}_{i}"
        i += 1
    return candidate

def extract_nas_ip(network_state: dict) -> str:
    # Тут зависит от того, как именно ваша интеграция кладёт IP в attributes.
    # Предположим: attributes.ip или attributes.ip_address
    attrs = network_state.get("attributes", {}) or {}
    return attrs.get("ip") or attrs.get("ip_address") or attrs.get("host") or ""

def extract_shares(shares_state: dict):
    attrs = shares_state.get("attributes", {}) or {}
    shares = attrs.get("shares") or []
    # expected: [{share_name:..., path:...}, ...]
    return shares

@app.get("/")
def index():
    # Простая HTML-страница (Ingress)
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
async function api(path, opts){ const r=await fetch(path, opts); if(!r.ok) throw new Error(await r.text()); return r.json(); }
function btn(label, onclick){ const b=document.createElement('button'); b.textContent=label; b.onclick=onclick; return b; }

async function load(){
  const data = await api('api/shares');
  document.getElementById('meta').innerHTML =
    `<small>NAS: ${data.nas_ip || '(unknown)'} | Protocol: ${data.protocol} | Default usage: ${data.default_usage}</small>`;
  const tb = document.querySelector('#tbl tbody'); tb.innerHTML='';
  for(const row of data.rows){
    const tr=document.createElement('tr');
    tr.innerHTML = `<td>${row.share_name}</td><td>${row.mount_name}</td><td>${row.state || '-'}</td>
                    <td>${row.usage}</td><td></td>`;
    const actions = tr.children[4];
actions.appendChild(
  btn('Mount', async()=>{ 
    try {
      await api('api/mount', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          share_name: row.share_name,
          usage: row.usage
        })
      });
    } catch (e) {
      const msg = String(e).toLowerCase();

      if (msg.includes('authorization') || msg.includes('access denied')) {
        alert(`🔒 Authorization required for share "${row.share_name}".\nPlease set username/password.`);
        return; // НЕ делаем load(), статус пока "-"
      } else {
        alert(e);
        return;
      }
    }

    // если дошли сюда — mount прошёл успешно
    await load();
  })
);

    actions.appendChild(btn('Reload', async()=>{ await api('api/reload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mount_name:row.mount_name})}); await load(); }));
    actions.appendChild(btn('Unmount', async()=>{ await api('api/unmount',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mount_name:row.mount_name})}); await load(); }));
    actions.appendChild(btn('Creds', async()=>{
  const cur = await api(`api/creds/${encodeURIComponent(row.share_name)}`);
  const u = prompt(`Username for ${row.share_name}`, cur.username || '');
  if(u === null) return;
  const p = prompt(`Password for ${row.share_name} (leave blank to keep)`, '');
  if(p === null) return;
  await api(`api/creds/${encodeURIComponent(row.share_name)}`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({username:u, password:p})
  });
  await load();
}));
    tb.appendChild(tr);
  }
}
load().catch(e=>{ document.getElementById('meta').innerHTML = `<small style="color:#b00">${e}</small>`; });
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
        existing_mount_names.add(m["name"])
        # для cifs удобно мапить по share
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

    shares_state = core_get_state(opt["shares_entity_id"])
    network_state = core_get_state(opt["network_entity_id"])
    nas_ip = extract_nas_ip(network_state)
    if not nas_ip:
        return jsonify({"error": "NAS IP not found in network summary attributes"}), 400

    mounts_data = supervisor_get_mounts()
    existing_names = {m["name"] for m in mounts_data.get("mounts", [])}

    mount_name = build_mount_name("wdmc", share_name, existing_names)

    protocol = opt.get("protocol", "cifs")

    if protocol == "cifs":
        creds = load_creds().get(share_name, {})
        username = creds.get("username", opt.get("cifs_username",""))
        password = creds.get("password", opt.get("cifs_password",""))
        body = {
            "name": mount_name,
            "usage": usage,
            "type": "cifs",
            "server": nas_ip,
            "share": share_name,
            "username": username,
            "password": password,
            "read_only": False,
            "has_creds": bool(creds.get(share_name, {}).get("password") or creds.get(share_name, {}).get("username")),
        }
    else:
        # если решите NFS: "path" должен быть экспортируемым путём на NAS,
        # а ваши /mnt/HD/... обычно не то, что экспортировано (надо брать NFS export path).
        return jsonify({"error": "NFS not implemented in this skeleton"}), 400

        r = requests.post(f"{SUPERVISOR_BASE}/mounts", headers=HEADERS, json=body, timeout=20)

        if not r.ok:
            txt = (r.text or "").lower()

            if any(s in txt for s in (
                "permission denied",
                "access denied",
                "authentication failed",
                "logon failure",
                "mount error(13)",
                "status_access_denied",
            )):
                return jsonify({
                    "error": "Authorization required for this share. Please set username/password."
                }), 401

            return jsonify({"error": r.text[:500]}), 500


@app.get("/api/creds/<share_name>")
def get_creds(share_name):
    creds = load_creds()
    c = creds.get(share_name, {})
    # пароль не отдаём обратно в UI (можно отдавать флаг что он сохранён)
    return jsonify({"username": c.get("username",""), "has_password": bool(c.get("password"))})

@app.post("/api/creds/<share_name>")
def set_creds(share_name):
    payload = request.get_json(force=True)
    creds = load_creds()
    creds[share_name] = {
        "username": payload.get("username",""),
        "password": payload.get("password",""),
        "domain": payload.get("domain",""),
        "vers": payload.get("vers",""),
    }
    save_creds(creds)
    return jsonify({"ok": True})

@app.post("/api/reload")
def api_reload():
    payload = request.get_json(force=True)
    name = payload["mount_name"]
    r = requests.post(f"{SUPERVISOR_BASE}/mounts/{name}/reload", headers=HEADERS, timeout=20)
    if not r.ok:
        return jsonify({"error": r.text}), 500
    return jsonify(r.json())

@app.post("/api/unmount")
def api_unmount():
    payload = request.get_json(force=True)
    name = payload["mount_name"]
    r = requests.delete(f"{SUPERVISOR_BASE}/mounts/{name}", headers=HEADERS, timeout=20)
    if not r.ok:
        return jsonify({"error": r.text}), 500
    return jsonify(r.json())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8099)

