# Mokyklos skambutis

Pamokų skambutis nešiojamam kompiuteriui, prijungtam prie mokyklos kolonėlių.
Dvi dalys viename faile:

- **passive** (`daemon`) – sukasi fone, tyli, žiūri laikrodį ir groja skambutį;
- **active** (`ui`) – konfiguravimo langas naršyklėje.

Kiekvienai pamokai skambutis skamba **du kartus**: N min prieš pradžią
(numatyta 2) ir tiksliai pamokos pradžios minutę. Papildomai – į pamokos
pabaigą (galima išjungti).

Takelis kiekvienam skambučiui parenkamas **atsitiktinai** iš pažymėtų.

Numatytas tvarkaraštis – 8 pamokos po 45 min, pradžia 08:30, pertraukos 10 min,
po 4-os ir po 5-os pamokos ilgosios po 20 min:

| Pam. | Laikas | | Pam. | Laikas |
|---|---|---|---|---|
| 1 | 08:30–09:15 | | 5 | 12:20–13:05 |
| 2 | 09:25–10:10 | | 6 | 13:25–14:10 |
| 3 | 10:20–11:05 | | 7 | 14:20–15:05 |
| 4 | 11:15–12:00 | | 8 | 15:15–16:00 |

Viso 24 skambučiai per dieną. Keičiama UI'e.

## Ko reikia

Tik Python 3.8+ ir naršyklė. Jokių bibliotekų diegti nereikia.

- **Windows**: parsisiųsti iš python.org, diegiant pažymėti *Add Python to PATH*.
- **macOS**: `python3` jau yra.
- **Linux**: bet kuris grotuvas – `paplay`, `ffplay`, `mpv` ar `cvlc`.

## Paleidimas

| Sistema | Ką daryti |
|---|---|
| Windows | dukart spragtelėti `paleisti.bat` |
| macOS | dukart spragtelėti `paleisti.command` |
| bet kur | `python3 skambutis.py ui` |

Naršyklėje atsidaro <http://127.0.0.1:8777/>. Puslapis pasiekiamas tik iš to
paties kompiuterio.

## Naudojimas

1. **Garso takeliai** – mp3/wav failus įmesti į aplanką `garsai/` šalia
   programos, puslapyje spausti `Atnaujinti sąrašą` ir pažymėti varneles.
   `Groti bandomąjį` patikrina, ar girdėti per kolonėles.
2. **Pamokos** – `+ Pridėti pamoką`, nustatyti pradžios ir pabaigos laiką.
   Nereikalingą pašalinti `✕`. Rikiuojama automatiškai išsaugant.
3. **Nustatymai** – kiek minučių prieš pamoką skambinti, ar skambinti į
   pabaigą, kuriomis savaitės dienomis (numatyta Pr–Pn), ir `Paleisti anksčiau`
   (ms) – kompensacija garso grotuvo startui.
4. `💾 Išsaugoti` – įrašoma į `config.json`.
5. `▶️ Paleisti fone` – startuoja passive dalį **ir įrašo ją į sistemos
   autostartą**: po kompiuterio perkrovimo skambutis pasileidžia pats.
   Daugiau nieko daryti nereikia. Šalia rodoma būsena ir kada sekantis
   skambutis. `⏹ Stabdyti foną` – sustabdo ir išima iš autostarto.

Puslapyje spausk `✕ Uždaryti`, kai baigei – terminalą ir naršyklę galima
uždaryti, **fone veikiantis skambutis lieka dirbti.** Konfigūracija
perskaitoma kas sekundę, tad pakeitimai įsigalioja iš karto.

Kur įrašomas autostartas:

| Sistema | Kur |
|---|---|
| Windows | `Startup` aplankas – `skambutis.bat`, paleidžia `pythonw` be lango |
| macOS | `~/Library/LaunchAgents/lt.mokykla.skambutis.plist` (launchd, su `KeepAlive` – prikelia, jei procesas nulūžtų) |
| Linux | `~/.config/systemd/user/skambutis.service` |

**macOS ypatybė:** launchd negali paleisti programos, gulinčios `Documents`,
`Desktop` ar `Downloads` aplankuose (sistemos apsauga). Laikyk aplanką namų
katalogo šaknyje, pvz. `~/skambutis`. Programa tai pastebi ir pasako pati.

**Svarbu:** kompiuteris turi nemiegoti. macOS: Sistemos nustatymai → Lock
Screen / Baterija, išjungti miegą. Windows: Power → *Put the computer to
sleep: Never*. Ir patikrinti, kad garsas nebūtų užtildytas.

## Automatinis startas – rankiniu būdu

Paprastai to nereikia, tai padaro mygtukas `▶️ Paleisti fone`. Jei nori
susikonfigūruoti pats:

**Windows.** `Win+R` → `shell:startup` → į atsidariusį aplanką įmesti
`skambutis.bat`:

```bat
@echo off
cd /d "C:\kelias\iki\skambutis"
start "" pythonw skambutis.py daemon
```

**macOS.** Sukurti `~/Library/LaunchAgents/lt.mokykla.skambutis.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>Label</key><string>lt.mokykla.skambutis</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/kelias/iki/skambutis/skambutis.py</string>
    <string>daemon</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
```

Tada `launchctl load ~/Library/LaunchAgents/lt.mokykla.skambutis.plist`.

## Failai

| Failas | Kam |
|---|---|
| `skambutis.py` | visa programa |
| `garsai/` | garso takeliai |
| `config.json` | nustatymai (sukuriamas automatiškai) |
| `skambutis.log` | kas ir kada skambėjo |
| `daemon.pid` | fone veikiančio proceso ID |

## Komandos

```
python3 skambutis.py ui       # konfiguravimas naršyklėje
python3 skambutis.py daemon   # fonas, be lango
python3 skambutis.py test     # savikontrolė
```

## Jei kas neveikia

| Problema | Ką tikrinti |
|---|---|
| Neskamba | `skambutis.log` – ar yra įrašas apie skambutį; ar pažymėtas bent vienas takelis |
| `nėra garso takelių` | aplankas `garsai/` tuščias arba nepažymėta nė viena varnelė |
| `nerastas garso grotuvas` (Linux) | `sudo apt install pulseaudio-utils` |
| Puslapis neatsidaro | rankiniu būdu <http://127.0.0.1:8777/>; prievadą keisti `PORT` eilutėje |
| Po perkrovimo neveikia (macOS) | aplankas guli `Documents`/`Desktop` – perkelti į `~/skambutis` ir spausti mygtuką iš naujo |
| Skambutis vėluoja | kompiuteris užmigo – žr. „Svarbu“ aukščiau |
| Garsas pusę sekundės vėluoja / skuba | pakoreguoti `Paleisti anksčiau` (ms). Matuojama su chronometru: 0 = be kompensacijos |
