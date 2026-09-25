#!/usr/bin/env python3
"""Mokyklos skambutis.

  python3 skambutis.py ui       - konfiguravimas narsykleje (active)
  python3 skambutis.py daemon   - fone sukasi ir groja (passive)
  python3 skambutis.py info     - diagnostika: ka programa mato
  python3 skambutis.py test     - savikontrole
"""
import json, os, random, shutil, subprocess, sys, threading, time, webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
GARSAI = os.path.join(HERE, "garsai")
PRANESIMAI = os.path.join(HERE, "pranesimai")
SIGNALAI = ["BALTAS", "GELTONAS", "RAUDONAS"]
# UI sekcijos: tik ispejimas turi atskira aplanka, pradzia ir pabaiga - is bendro fondo
TIPAI = {"pries": "Prieš pamoką", "bendras": "Pamokos pradžia ir pabaiga"}
CFG = os.path.join(HERE, "config.json")
LOG = os.path.join(HERE, "skambutis.log")
PIDF = os.path.join(HERE, "daemon.pid")
PORT = 8777
EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".aiff")

DEFAULT = {
    "isjungti": [],        # takeliai, kuriu nenaudoti (pvz. "pries/varpelis.mp3")
    "pre_minutes": 2,
    "lead_ms": 200,        # kiek anksciau paleisti, kad garsas suskambetu tiksliai
    "ring_end": True,
    "days": [0, 1, 2, 3, 4],  # 0=pirmadienis
    "lessons": [   # 8 pamokos po 45 min, pertraukos 10 min
        {"start": "08:30", "end": "09:15"},
        {"start": "09:25", "end": "10:10"},
        {"start": "10:20", "end": "11:05"},
        {"start": "11:15", "end": "12:00"},   # po sios - ilgoji pertrauka (20 min)
        {"start": "12:20", "end": "13:05"},   # po sios - ilgoji pertrauka (20 min)
        {"start": "13:25", "end": "14:10"},
        {"start": "14:20", "end": "15:05"},
        {"start": "15:15", "end": "16:00"},
    ],
}


def load():
    try:
        with open(CFG, encoding="utf-8") as f:  # nezinomus raktus (pvz. sena "tracks") atmetam
            return {**DEFAULT, **{k: v for k, v in json.load(f).items() if k in DEFAULT}}
    except (FileNotFoundError, json.JSONDecodeError):
        save(DEFAULT)
        return dict(DEFAULT)


def save(cfg):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    if sys.stdout:  # pythonw.exe konsoles neturi
        print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def signal_file(name):
    """pranesimai/<VARDAS>.<ext> arba None. Vardas tik is SIGNALAI - jokio path traversal."""
    if name not in SIGNALAI:
        return None
    for e in EXT:
        p = os.path.join(PRANESIMAI, name + e)
        if os.path.exists(p):
            return p
    return None


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    cmd = {"darwin": ["open", path], "win32": ["explorer", path]}.get(sys.platform, ["xdg-open", path])
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def folder(tipas=None):
    """Tik "pries" turi savo aplanka; visa kita - garsai/ saknis."""
    return os.path.join(GARSAI, "pries") if tipas == "pries" else GARSAI


def rel(path):
    """Kelias configui: "varpelis.mp3" arba "pries/varpelis.mp3"."""
    return os.path.relpath(path, GARSAI).replace(os.sep, "/")


def files_in(tipas=None):
    """Visi aplanko failai, ir ijungti, ir isjungti."""
    p = folder(tipas)
    os.makedirs(p, exist_ok=True)
    return sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(EXT))


def pool(tipas=None, cfg=None):
    """Ijungti aplanko takeliai; jei pries/ neliko nė vieno - imam is bendro fondo."""
    off = set((cfg or load()).get("isjungti", []))
    files = [f for f in files_in(tipas) if rel(f) not in off]
    return files if files or tipas != "pries" else pool(None, cfg)


# --- grojimas ---------------------------------------------------------------

# WAV - SoundPlayer.PlaySync(): blokuoja iki pabaigos, jokiu metaduomenu nereikia
WIN_WAV = r"""
$ErrorActionPreference='Stop'
(New-Object System.Media.SoundPlayer '{path}').PlaySync()
"""

# mp3/m4a/... - MediaPlayer. Trukmes gali ir nepavykti nuskaityti, tai NE klaida:
# tada tiesiog laikom procesa gyva, kad garsas nebutu nukirstas.
WIN_MP3 = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationCore
$p = New-Object System.Windows.Media.MediaPlayer
$p.Open([uri]'{path}')
$n = 0
while (-not $p.NaturalDuration.HasTimeSpan -and $n -lt 50) {{ Start-Sleep -m 100; $n++ }}
$p.Volume = 1.0
$p.Play()
if ($p.NaturalDuration.HasTimeSpan) {{
  Start-Sleep -s ([int]$p.NaturalDuration.TimeSpan.TotalSeconds + 1)
}} else {{
  Start-Sleep -s 30
}}
"""


def play(path):
    """Groja faila sinchroniskai sisteminiu grotuvu."""
    if sys.platform == "darwin":
        cmd = ["afplay", path]
    elif sys.platform == "win32":
        exe = shutil.which("powershell") or \
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        ps = WIN_WAV if path.lower().endswith(".wav") else WIN_MP3
        cmd = [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA",
               "-Command", ps.format(path=path.replace("'", "''"))]
    else:
        for exe in ("paplay", "aplay", "ffplay", "mpv", "cvlc"):
            if shutil.which(exe):
                cmd = [exe, path]
                if exe == "ffplay":
                    cmd = [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
                elif exe == "cvlc":
                    cmd = [exe, "--play-and-exit", path]
                break
        else:
            log("KLAIDA: nerastas garso grotuvas")
            return
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        err = " ".join((r.stderr or "").split())[-300:]
        log(f"GROTUVO KLAIDA ({os.path.basename(path)}): rc={r.returncode} {err}")


def ring(tipas, label):
    tracks = pool(tipas)
    if not tracks:
        log(f"{label}: nera garso takeliu (idek mp3 i garsai/)")
        return
    t = random.choice(tracks)
    log(f"{label}: groja {os.path.basename(t)}")
    play(t)


# --- tvarkarastis -----------------------------------------------------------

def minus(hhmm, minutes):
    h, m = map(int, hhmm.split(":"))
    total = (h * 60 + m - minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def bell_times(cfg, d=None):
    """{'HH:MM': etikete} siai dienai. Tuscia, jei ne mokslo diena."""
    d = d or date.today()
    if d.weekday() not in cfg["days"]:
        return {}
    out = {}
    for i, les in enumerate(cfg["lessons"], 1):
        out[minus(les["start"], cfg["pre_minutes"])] = ("pries", f"{i} pam. -{cfg['pre_minutes']} min")
        out[les["start"]] = ("pradzia", f"{i} pam. pradžia")
        if cfg.get("ring_end"):
            out[les["end"]] = ("pabaiga", f"{i} pam. pabaiga")
    return out


def next_bell(cfg):
    t = bell_times(cfg)
    now = datetime.now().strftime("%H:%M")
    future = sorted(x for x in t if x > now)
    return (future[0], t[future[0]][1]) if future else None


# --- passive dalis ----------------------------------------------------------

def daemon():
    log("startas")
    beat()
    last, hb = None, time.time()
    while True:
        cfg = load()  # perskaitom kas sekunde -> UI pakeitimai veikia is karto
        # grotuvo startas uztrunka, tad prabundam lead_ms anksciau uz sekundes riba
        lead = min(max(cfg.get("lead_ms", 0) / 1000, 0.0), 60.0)
        now = datetime.now()
        time.sleep(1.0 - (now.microsecond / 1e6 + lead) % 1.0)
        if time.time() - hb > 5:  # heartbeat: UI mato, kad fonas tikrai sukasi
            hb = time.time()
            beat()
        now = (datetime.now() + timedelta(seconds=lead)).strftime("%H:%M")
        if now == last:
            continue
        last = now
        hit = bell_times(cfg).get(now)
        if hit:
            # atskiroj gijoj: ilgas takelis neturi blokuoti sekancio skambucio
            threading.Thread(target=ring, args=hit, daemon=True).start()


AUTOSTART = {
    "darwin": os.path.expanduser("~/Library/LaunchAgents/lt.mokykla.skambutis.plist"),
    "win32": os.path.expanduser(
        "~/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/skambutis.bat"),
    "linux": os.path.expanduser("~/.config/systemd/user/skambutis.service"),
}.get(sys.platform)

SCRIPT = os.path.abspath(__file__)


def pyw():
    """Windows: pythonw.exe, kad nesimatytu konsoles lango."""
    return sys.executable.replace("python.exe", "pythonw.exe") if sys.platform == "win32" else sys.executable


def daemon_state():
    """(pid, ar gyvas) is heartbeat failo. Veikia ir kai demona paleido OS."""
    try:
        d = json.load(open(PIDF))
        return d["pid"], time.time() - d["ts"] < 15
    except Exception:
        return None, False


def beat():
    with open(PIDF, "w") as f:
        json.dump({"pid": os.getpid(), "ts": time.time()}, f)


def spawn():
    """Paleidzia demona atsieta nuo konsoles (Ctrl+C terminale jo nenuzudo)."""
    kw = ({"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32"
          else {"start_new_session": True})
    subprocess.Popen([pyw(), SCRIPT, "daemon"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>lt.mokykla.skambutis</string>
  <key>ProgramArguments</key><array><string>{exe}</string><string>{script}</string><string>daemon</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
"""

UNIT = """[Unit]
Description=Mokyklos skambutis
[Service]
ExecStart={exe} {script} daemon
Restart=always
[Install]
WantedBy=default.target
"""


def autostart_on():
    """Iraso i OS autostarta IR paleidzia dabar. Grazina zinute vartotojui."""
    if not AUTOSTART:
        spawn()
        return "Paleista, bet autostartas siai sistemai nepalaikomas (zr. README)"
    os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
    if sys.platform == "darwin":
        open(AUTOSTART, "w").write(PLIST.format(exe=sys.executable, script=SCRIPT, log=LOG))
        subprocess.run(["launchctl", "unload", AUTOSTART],
                       capture_output=True)  # jei buvo senas
        r = subprocess.run(["launchctl", "load", "-w", AUTOSTART], capture_output=True, text=True)
        if r.returncode:
            return f"launchctl klaida: {r.stderr.strip()}"
        for _ in range(30):  # laukiam, ar tikrai uzsikure
            time.sleep(0.2)
            if daemon_state()[1]:
                return "Veikia fone, startuos ir po perkrovimo"
        subprocess.run(["launchctl", "unload", AUTOSTART], capture_output=True)
        os.remove(AUTOSTART)
        spawn()  # bent siai sesijai
        return ("Autostartas neveikia: macOS neleidzia fono procesui skaityti sio aplanko. "
                "Perkelk programos aplanka is Documents/Desktop i namu katalogo sakni (pvz. ~/skambutis) "
                "ir paspausk dar karta. Kol kas skambutis veikia tik iki perkrovimo.")
    if sys.platform == "win32":
        open(AUTOSTART, "w").write(f'@echo off\r\nstart "" "{pyw()}" "{SCRIPT}" daemon\r\n')
        spawn()
        return "Veikia fone, startuos ir po perkrovimo"
    open(AUTOSTART, "w").write(UNIT.format(exe=sys.executable, script=SCRIPT))
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "skambutis.service"], capture_output=True)
        return "Veikia fone, startuos ir po perkrovimo"
    spawn()
    return "Paleista, bet systemd nerastas - autostartas neiraytas"


def autostart_off():
    """Isima is autostarto ir sustabdo."""
    if AUTOSTART and os.path.exists(AUTOSTART):
        if sys.platform == "darwin":
            subprocess.run(["launchctl", "unload", "-w", AUTOSTART], capture_output=True)
        elif sys.platform == "linux" and shutil.which("systemctl"):
            subprocess.run(["systemctl", "--user", "disable", "--now", "skambutis.service"],
                           capture_output=True)
        os.remove(AUTOSTART)
    pid, alive = daemon_state()
    if pid and alive:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    if os.path.exists(PIDF):
        os.remove(PIDF)
    return "Sustabdyta"


# --- active dalis: UI narsykleje --------------------------------------------

PAGE = """<!doctype html><html lang="lt"><meta charset="utf-8">
<title>Mokyklos skambutis</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 :root{color-scheme:light dark}
 body{font:16px system-ui,sans-serif;max-width:720px;margin:24px auto;padding:0 16px}
 h1{font-size:22px} h2{font-size:17px;margin:28px 0 8px}
 table{border-collapse:collapse;width:100%} td,th{padding:6px 8px;text-align:left}
 th{font-size:13px;opacity:.7;font-weight:600}
 input[type=time],input[type=number]{font:inherit;padding:4px 6px}
 button{font:inherit;padding:6px 12px;margin-right:6px;cursor:pointer}
 .row{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:10px 0}
 .bar{position:sticky;bottom:0;background:Canvas;padding:12px 0;border-top:1px solid #8884}
 .pill{padding:3px 10px;border:1px solid #8888;border-radius:99px;font-size:14px}
 .muted{opacity:.7;font-size:14px} label{cursor:pointer}
 ul{list-style:none;padding:0} li{padding:3px 0}
</style>
<h1>🔔 Mokyklos skambutis</h1>

<h2>Garso takeliai</h2>
<p class="muted">Įspėjimas prieš pamoką turi atskirą aplanką <code>garsai/pries/</code>;
kol jis tuščias, skamba tas pats, kas pradžiai ir pabaigai. Bendras fondas –
<code id="garsai"></code>. Jei aplanke keli failai, parenkamas atsitiktinis.</p>
<div id="takeliai"></div>
<div class="row">
  <button onclick="post('/aplankas',{kuris:'garsai'})">📂 Bendras fondas</button>
  <button onclick="load()">Atnaujinti sąrašus</button>
</div>

<h2>Pamokos</h2>
<table id="lessons"><thead><tr><th>Nr.</th><th>Pradžia</th><th>Pabaiga</th><th></th></tr></thead><tbody></tbody></table>
<div class="row"><button onclick="addLesson()">+ Pridėti pamoką</button></div>

<h2>Nustatymai</h2>
<div class="row">
  <label>Skambinti prieš pamoką: <input type="number" id="pre" min="0" max="30" style="width:60px"> min</label>
</div>
<div class="row"><label><input type="checkbox" id="end"> Skambinti ir į pamokos pabaigą</label></div>
<div class="row">
  <label>Paleisti anksčiau: <input type="number" id="lead" min="0" max="5000" step="50" style="width:80px"> ms</label>
  <span class="muted">kompensuoja garso grotuvo startą (numatyta 200)</span>
</div>
<div class="row" id="days"></div>

<h2>Civilinės saugos pranešimai</h2>
<p class="muted">Groja tik paspaudus. Failai aplanke <code id="pranesimai"></code>,
keliauja kartu su programa per git.</p>
<div class="row" id="signalai"></div>
<div class="row"><button onclick="post('/aplankas',{kuris:'pranesimai'})">📂 Atidaryti pranešimų aplanką</button></div>

<details style="margin-top:28px"><summary class="muted">Žurnalas (kas ir kada skambėjo, klaidos)</summary>
<pre id="log" style="font-size:12px;overflow:auto;max-height:240px;white-space:pre-wrap"></pre></details>

<div class="bar row">
  <button onclick="save()">💾 Išsaugoti</button>
  <button id="dbtn" onclick="toggle()"></button>
  <button onclick="quit()">✕ Uždaryti</button>
  <span class="pill" id="auto"></span>
  <span class="pill" id="status"></span>
  <span class="muted" id="next"></span>
</div>

<script>
const DAYS=["Pr","An","Tr","Kt","Pn","Št","Sk"];
let cfg=null;
async function post(u,b){const r=await fetch(u,{method:"POST",body:JSON.stringify(b)});return r.json()}
async function load(){
  const d=await (await fetch("/data")).json(); cfg=d.cfg;
  garsai.textContent=d.garsai;
  takeliai.innerHTML=Object.entries(d.tipai).map(([k,pav])=>`
    <div style="border:1px solid #8884;border-radius:8px;padding:10px 14px;margin:8px 0">
      <b>${pav}</b>
      <ul>${d.failai[k].length
        ? d.failai[k].map(f=>`<li><label><input type="checkbox" data-rel="${f.rel}" ${f.on?"checked":""}
            onchange="save()"> ${f.name}</label></li>`).join("")
        : "<li class='muted'>(aplankas tuščias)</li>"}</ul>
      ${d.savi[k]?"":`<div class="muted">Gros iš bendro fondo: ${d.gros[k].join(", ")||"nieko"}</div>`}
      <button onclick="post('/aplankas',{kuris:'${k}'})">📂 Aplankas</button>
      <button onclick="post('/test',{tipas:'${k}'})">▶ Groti</button>
    </div>`).join("");
  pranesimai.textContent=d.garsai.replace(/garsai$/,"pranesimai");
  const SPALVOS={BALTAS:["#f5f5f5","#111"],GELTONAS:["#f5c518","#111"],RAUDONAS:["#d33","#fff"]};
  signalai.innerHTML=Object.entries(d.signalai).map(([n,yra])=>{
    const [bg,fg]=SPALVOS[n];
    return `<button onclick="post('/signalas',{name:'${n}'})" ${yra?"":"disabled title='Failo nėra'"}
      style="background:${bg};color:${fg};border:1px solid #8888;padding:10px 18px;font-weight:600">${n}${yra?"":" (nėra)"}</button>`;
  }).join("");
  drawLessons();
  pre.value=cfg.pre_minutes; end.checked=cfg.ring_end; lead.value=cfg.lead_ms;
  days.innerHTML=DAYS.map((n,i)=>`<label><input type="checkbox" data-d="${i}" ${cfg.days.includes(i)?"checked":""}> ${n}</label>`).join(" ");
  refresh();
}
function drawLessons(){
  const tb=lessons.tBodies[0]; tb.innerHTML="";
  cfg.lessons.forEach((l,i)=>{
    const tr=tb.insertRow();
    tr.innerHTML=`<td>${i+1}</td>
      <td><input type="time" value="${l.start}" onchange="cfg.lessons[${i}].start=this.value"></td>
      <td><input type="time" value="${l.end}" onchange="cfg.lessons[${i}].end=this.value"></td>
      <td><button onclick="cfg.lessons.splice(${i},1);drawLessons()">✕</button></td>`;
  });
}
function addLesson(){cfg.lessons.push({start:"08:00",end:"08:45"});drawLessons()}
function collect(){
  cfg.days=[...days.querySelectorAll("input:checked")].map(c=>+c.dataset.d);
  cfg.isjungti=[...takeliai.querySelectorAll("input[data-rel]:not(:checked)")].map(c=>c.dataset.rel);
  cfg.pre_minutes=+pre.value; cfg.ring_end=end.checked; cfg.lead_ms=+lead.value;
  cfg.lessons=cfg.lessons.filter(l=>l.start&&l.end).sort((a,b)=>a.start.localeCompare(b.start));
  return cfg;
}
async function save(){const r=await post("/save",collect());cfg=r.cfg;flash("Išsaugota");await load()}
async function toggle(){dbtn.disabled=true;await save();const r=await post("/daemon",{});dbtn.disabled=false;flash(r.msg||"");refresh()}
async function quit(){
  await save(); await post("/quit",{});
  document.body.innerHTML="<h1>🔔 Uždaryta</h1><p>Kortelę gali uždaryti. Fone veikiantis skambutis lieka dirbti.</p>";
}
function flash(t){status.textContent=t;setTimeout(()=>status.textContent="",4000)}
async function refresh(){
  const s=await (await fetch("/status")).json();
  dbtn.textContent=s.running?"⏹ Stabdyti foną":"▶️ Paleisti fone";
  auto.textContent=s.running?(s.autostart?"✅ Veikia fone · startuos ir po perkrovimo":"⚠️ Veikia fone, bet po perkrovimo nestartuos"):"⏸ Nesukasi";
  fetch("/log").then(r=>r.json()).then(d=>log.textContent=d.log||"(tuščias)");
  next.textContent=s.next?`Sekantis: ${s.next[0]} (${s.next[1]})`:"Šiandien daugiau skambučių nėra";
}
load(); setInterval(refresh,5000);
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype="application/json"):
        b = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        cfg = load()
        if self.path == "/":
            self._send(PAGE, "text/html")
        elif self.path == "/data":
            self._send(json.dumps({
                "cfg": cfg, "garsai": GARSAI, "tipai": TIPAI,
                "failai": {k: [{"name": os.path.basename(f), "rel": rel(f),
                                "on": rel(f) not in cfg.get("isjungti", [])}
                               for f in files_in(k)] for k in TIPAI},
                "gros": {k: [os.path.basename(f) for f in pool(k, cfg)] for k in TIPAI},
                "savi": {k: pool(k, cfg) != pool(None, cfg) or k != "pries" for k in TIPAI},
                "signalai": {n: bool(signal_file(n)) for n in SIGNALAI}}))
        elif self.path == "/log":
            try:
                lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()[-20:]
            except OSError:
                lines = []
            self._send(json.dumps({"log": "\n".join(lines)}))
        elif self.path == "/status":
            self._send(json.dumps({"running": daemon_state()[1], "next": next_bell(cfg),
                                   "autostart": bool(AUTOSTART and os.path.exists(AUTOSTART))}))
        else:
            self.send_error(404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        cfg = load()
        if self.path == "/save":
            new = json.loads(body)
            cfg = {**cfg, **{k: new[k] for k in DEFAULT if k in new}}
            save(cfg)
            self._send(json.dumps({"cfg": cfg}))
        elif self.path == "/test":
            tipas = json.loads(body).get("tipas")
            threading.Thread(target=ring, args=(tipas, f"bandomasis ({tipas or 'bendras'})"),
                             daemon=True).start()
            self._send("{}")
        elif self.path == "/signalas":
            p = signal_file(json.loads(body).get("name", ""))
            if p:
                threading.Thread(target=play, args=(p,), daemon=True).start()
            self._send(json.dumps({"ok": bool(p)}))
        elif self.path == "/aplankas":
            k = json.loads(body).get("kuris")
            open_folder(PRANESIMAI if k == "pranesimai" else folder(k if k in TIPAI else None))
            self._send("{}")
        elif self.path == "/quit":
            self._send("{}")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        elif self.path == "/daemon":
            msg = autostart_off() if daemon_state()[1] else autostart_on()
            time.sleep(1.2)  # spejam pagauti pirma heartbeat
            self._send(json.dumps({"running": daemon_state()[1], "msg": msg}))
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


def ui():
    os.makedirs(GARSAI, exist_ok=True)
    load()
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Konfiguravimas: {url}   (Ctrl+C uzdaryti)")
    threading.Timer(0.7, webbrowser.open, (url,)).start()
    try:
        HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except OSError as e:
        print(f"Nepavyko atidaryti prievado {PORT}: {e}\nGal langas jau atidarytas? {url}")
    except KeyboardInterrupt:
        print("\nUzdaryta. Fone veikiantis skambutis lieka dirbti.")


# --- savikontrole -----------------------------------------------------------

def info():
    """Diagnostika: ka programa realiai mato."""
    cfg = load()
    print(f"skriptas    : {SCRIPT}")
    print(f"python      : {sys.executable}")
    print(f"config      : {CFG}")
    print(f"isjungti    : {cfg.get('isjungti')}")
    print(f"pamoku      : {len(cfg['lessons'])}, dienos: {cfg['days']}, pries: {cfg['pre_minutes']} min")
    for tipas, pav in TIPAI.items():
        p = folder(tipas if tipas == "pries" else None)
        visi = os.listdir(p) if os.path.isdir(p) else ["<NERA APLANKO>"]
        print(f"\n{pav}  ({p})")
        print(f"  aplanke      : {visi}")
        print(f"  tinkami      : {[os.path.basename(f) for f in files_in(tipas)]}")
        print(f"  gros         : {[os.path.basename(f) for f in pool(tipas, cfg)]}")
    print(f"\npranesimai  : {[n for n in SIGNALAI if signal_file(n)]}")
    pid, alive = daemon_state()
    print(f"fonas       : pid={pid} gyvas={alive}")
    print(f"autostartas : {AUTOSTART if AUTOSTART and os.path.exists(AUTOSTART) else 'neiraytas'}")
    nb = next_bell(cfg)
    print(f"sekantis    : {nb or 'siandien daugiau nera'}")


def selftest():
    cfg = {**DEFAULT, "lessons": [{"start": "08:00", "end": "08:45"}], "pre_minutes": 2}
    t = bell_times(cfg, date(2026, 9, 21))  # pirmadienis
    assert t == {"07:58": ("pries", "1 pam. -2 min"),
                 "08:00": ("pradzia", "1 pam. pradžia"),
                 "08:45": ("pabaiga", "1 pam. pabaiga")}, t
    assert bell_times(cfg, date(2026, 9, 20)) == {}  # sekmadienis
    assert minus("00:01", 2) == "23:59"
    assert minus("08:00", 0) == "08:00"
    assert "08:45" not in bell_times({**cfg, "ring_end": False}, date(2026, 9, 21))
    for _, lab in t.values():  # Windows lokale (cp1252) turi suvirskinti kiekviena etikete
        lab.encode("cp1252")
    print("OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ui"
    if cmd == "daemon":
        daemon()
    elif cmd == "play":
        play(sys.argv[2])
    elif cmd == "test":
        selftest()
    elif cmd == "info":
        info()
    else:
        ui()
