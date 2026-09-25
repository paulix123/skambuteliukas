#!/usr/bin/env python3
"""Mokyklos skambutis.

  python3 skambutis.py ui       - konfiguravimas narsykleje (active)
  python3 skambutis.py daemon   - fone sukasi ir groja (passive)
  python3 skambutis.py test     - savikontrole
"""
import json, os, random, shutil, subprocess, sys, threading, time, webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
GARSAI = os.path.join(HERE, "garsai")
CFG = os.path.join(HERE, "config.json")
LOG = os.path.join(HERE, "skambutis.log")
PIDF = os.path.join(HERE, "daemon.pid")
PORT = 8777
EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".aiff")

DEFAULT = {
    "tracks": [],          # failu vardai is garsai/ aplanko
    "pre_minutes": 2,
    "lead_ms": 200,        # kiek anksciau paleisti, kad garsas suskambetu tiksliai
    "ring_end": True,
    "days": [0, 1, 2, 3, 4],  # 0=pirmadienis
    "lessons": [
        {"start": "08:00", "end": "08:45"},
        {"start": "08:55", "end": "09:40"},
    ],
}


def load():
    try:
        with open(CFG) as f:
            return {**DEFAULT, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        save(DEFAULT)
        return dict(DEFAULT)


def save(cfg):
    with open(CFG, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def available_tracks():
    os.makedirs(GARSAI, exist_ok=True)
    return sorted(f for f in os.listdir(GARSAI) if f.lower().endswith(EXT))


# --- grojimas ---------------------------------------------------------------

WIN_PS = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName PresentationCore
$p = New-Object System.Windows.Media.MediaPlayer
$p.Open([uri]'{path}')
# metaduomenys uzsikrauna asinchroniskai - laukiam iki 5 s
$n = 0
while (-not $p.NaturalDuration.HasTimeSpan -and $n -lt 50) {{ Start-Sleep -m 100; $n++ }}
$p.Volume = 1.0
$p.Play()
if ($p.NaturalDuration.HasTimeSpan) {{
  Start-Sleep -s ([int]$p.NaturalDuration.TimeSpan.TotalSeconds + 1)
}} else {{
  Write-Error "nepavyko nuskaityti trukmes (trukstamas kodekas?), grojam 15 s"
  Start-Sleep -s 15
}}
"""


def play(path):
    """Groja faila sinchroniskai sisteminiu grotuvu."""
    if sys.platform == "darwin":
        cmd = ["afplay", path]
    elif sys.platform == "win32":
        exe = shutil.which("powershell") or \
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        cmd = [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA",
               "-Command", WIN_PS.format(path=path.replace("'", "''"))]
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
    if r.returncode or (r.stderr or "").strip():
        log(f"GROTUVO KLAIDA ({os.path.basename(path)}): rc={r.returncode} {(r.stderr or '').strip()[:400]}")


def ring(cfg, label):
    tracks = [t for t in cfg["tracks"] if os.path.exists(os.path.join(GARSAI, t))]
    if not tracks:
        log(f"{label}: nera garso takeliu")
        return
    t = random.choice(tracks)
    log(f"{label}: groja {t}")
    play(os.path.join(GARSAI, t))


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
        out[minus(les["start"], cfg["pre_minutes"])] = f"{i} pam. − {cfg['pre_minutes']} min"
        out[les["start"]] = f"{i} pam. pradžia"
        if cfg.get("ring_end"):
            out[les["end"]] = f"{i} pam. pabaiga"
    return out


def next_bell(cfg):
    t = bell_times(cfg)
    now = datetime.now().strftime("%H:%M")
    future = sorted(x for x in t if x > now)
    return (future[0], t[future[0]]) if future else None


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
        label = bell_times(cfg).get(now)
        if label:
            # atskiroj gijoj: ilgas takelis neturi blokuoti sekancio skambucio
            threading.Thread(target=ring, args=(cfg, label), daemon=True).start()


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
<p class="muted">Failai iš aplanko <code id="garsai"></code>. Įmesk mp3/wav ten ir spausk „Atnaujinti“.
Skambučiui parenkamas atsitiktinis iš pažymėtų.</p>
<ul id="tracks"></ul>
<div class="row">
  <button onclick="load()">Atnaujinti sąrašą</button>
  <button onclick="post('/test',{})">Groti bandomąjį</button>
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
  tracks.innerHTML = d.available.length ? "" : "<li class='muted'>Aplankas tuščias</li>";
  d.available.forEach(f=>{
    const li=document.createElement("li");
    li.innerHTML=`<label><input type="checkbox" ${cfg.tracks.includes(f)?"checked":""} data-f="${f}"> ${f}</label>`;
    tracks.appendChild(li);
  });
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
  cfg.tracks=[...tracks.querySelectorAll("input:checked")].map(c=>c.dataset.f);
  cfg.days=[...days.querySelectorAll("input:checked")].map(c=>+c.dataset.d);
  cfg.pre_minutes=+pre.value; cfg.ring_end=end.checked; cfg.lead_ms=+lead.value;
  cfg.lessons=cfg.lessons.filter(l=>l.start&&l.end).sort((a,b)=>a.start.localeCompare(b.start));
  return cfg;
}
async function save(){const r=await post("/save",collect());cfg=r.cfg;drawLessons();flash("Išsaugota");refresh()}
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
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        cfg = load()
        if self.path == "/":
            self._send(PAGE, "text/html")
        elif self.path == "/data":
            self._send(json.dumps({"cfg": cfg, "available": available_tracks(), "garsai": GARSAI}))
        elif self.path == "/log":
            try:
                lines = open(LOG).read().splitlines()[-20:]
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
            threading.Thread(target=ring, args=(cfg, "bandomasis"), daemon=True).start()
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

def selftest():
    cfg = {**DEFAULT, "lessons": [{"start": "08:00", "end": "08:45"}], "pre_minutes": 2}
    t = bell_times(cfg, date(2026, 9, 21))  # pirmadienis
    assert t == {"07:58": "1 pam. − 2 min", "08:00": "1 pam. pradžia", "08:45": "1 pam. pabaiga"}, t
    assert bell_times(cfg, date(2026, 9, 20)) == {}  # sekmadienis
    assert minus("00:01", 2) == "23:59"
    assert minus("08:00", 0) == "08:00"
    assert "08:45" not in bell_times({**cfg, "ring_end": False}, date(2026, 9, 21))
    print("OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ui"
    if cmd == "daemon":
        daemon()
    elif cmd == "play":
        play(sys.argv[2])
    elif cmd == "test":
        selftest()
    else:
        ui()
