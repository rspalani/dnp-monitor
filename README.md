# DNP tools

Programs for the 800 MHz DNP spectrometer of the Griffin group (MIT, Francis
Bitter Magnet Laboratory):

| Part | What it is |
|---|---|
| [DNP monitor](#dnp-monitor) (`dnp_monitor.py`, `dnp_logviewer.py`) | MAS, temperature, and LN2 monitoring and logging; described below |
| [`frequency_profile/`](frequency_profile/) | DNP frequency profiles: TopSpin acquisition scripts that step the mm-wave frequency, a live viewer, and post-run phasing; see [its README](frequency_profile/README.md) |

## DNP monitor

A monitoring and logging program for a Bruker DNP spectrometer, written for the
800 MHz system in the Griffin group (MIT, Francis Bitter Magnet Laboratory). It
runs on the Topspin PC and shows, logs, and partly controls:

- **Bruker MAS3 controllers** (any number; two here: `MAS3-test-stand` and
  `MAS3-above-console`): spin rate, bearing, drive, and bearing-sense pressures,
  frame cooling, and the spin-rate RMSD over 10 s and 2 min. **Read-only.**
- **Lake Shore 336 temperature controller**: bearing (input A) and drive (input B)
  temperatures, setpoints, heater output and range, ramp, and PID, with controls
  for setpoint, ramp, PID, heater range, and ALL OFF.
- **AMI Model 1700 LN2 level meter** on the heat exchanger: level, autofill
  state, and valve, with controls for the fill start/stop levels and an
  Off / Fill / Auto mode.

A companion **log viewer** plots any time range of the saved logs.

| File | What it is |
|---|---|
| `dnp_monitor.py` | The monitor (one window, runs all the time) |
| `dnp_logviewer.py` | The log viewer (separate window; opened from the monitor's top bar or on its own) |
| `dnp_monitor.conf.example` | Example configuration, with placeholder addresses |

### Requirements

- Linux with an X display (developed for openSUSE Leap 15.1 on the Topspin PC)
- Python 3.6 or newer, with `numpy`, `matplotlib` (3.3 or newer), and `tkinter`
- Optional: `pandas` makes the log viewer load long ranges several times faster
  (on Python 3.6: `python3 -m pip install --user "pandas==1.1.5"`)

No other packages are needed; the instruments are reached with the standard library.

### Installation

Everything lives in one folder, by default `/home/nmrsu/dnp_monitor`
(`BASE_DIR` in both programs, or `--base-dir`). Logs are written into
sub-folders of it.

**New installation**

```bash
git clone https://github.com/rspalani/dnp-monitor.git /home/nmrsu/dnp_monitor
cd /home/nmrsu/dnp_monitor
cp dnp_monitor.conf.example dnp_monitor.conf
chmod 600 dnp_monitor.conf
# edit dnp_monitor.conf: the instruments' real addresses
python3 dnp_monitor.py
```

**Folder that already has the programs, config, and logs** (e.g. the current
Topspin PC): the config and logs are ignored by git, so the folder can be turned
into a clone without touching them.

```bash
cd /home/nmrsu/dnp_monitor
git init
git remote add origin https://github.com/rspalani/dnp-monitor.git
git fetch origin
git checkout -f -b main origin/main     # replaces only the programs (and adds frequency_profile/)
```

**Updating later**: close the monitor, then `git pull` in that folder, and start it again.

### Configuration

`dnp_monitor.conf` is read once at start-up (restart after editing). If it is
missing, the monitor writes one with the placeholder addresses. Sections:

- `[MAS3-...]`, one per controller, in display order: `ip`, `user`, `password`
  (used only to read the pressures), `read_pressures`. The section name is also
  the log-folder name, so renaming it starts a new history.
- `[LakeShore336]`: `host`, `port` (7777 for the Ethernet interface).
- `[AMI1700]`: `ip`, `poll_seconds` (10 to 3600; 60 is plenty), `enabled`.
  The AMI gets its address by DHCP; if it changes, read the new one on the
  instrument's network screen.

The real file stays only on the instrument PC (it is in `.gitignore`).

### Using the monitor

```bash
python3 /home/nmrsu/dnp_monitor/dnp_monitor.py
```

Only one copy runs at a time (a lock file in the base folder).

- **Plots**: past 24 h and past 30 min. The toolbar zooms and pans; *Follow live*
  switches back on by itself 30 s after the last zoom or pan. Under the Lake Shore
  plots, traces can be hidden for diagnosis (bearing/drive, temperature/setpoint/
  heater); they come back by themselves after 30 s.
- **Control** checkboxes (Lake Shore, AMI 1700): every change to an instrument
  needs Control ticked. Control locks itself after 30 s without edits. Edited
  fields turn amber until applied.
- **Lake Shore**: setpoint, ramp, PID, and heater range per output take effect
  with *Apply* (one write per value, read back, never retried). **ALL OFF** (under
  Control, no confirmation) sets both heaters to Off immediately.
- **AMI 1700 Mode** (acts at once, under Control):
  - *Off*: fill start set to 0.0 %, which disables autofill (manual: "If the
    START value is set to 0.0% the autofill function will be disabled"). A fill
    under way is stopped by briefly lowering the fill stop below the level.
  - *Fill*: fill start raised just above the present level; the instrument opens
    the valve and closes it at its own fill-stop level, with its fill timeout
    still active. Afterwards the monitor restores the start level (to the saved
    value, or to 0 if it was Off).
  - *Auto*: the saved fill start.

  The instrument's remote (SCPI) commands cannot switch its own AUTOFILL /
  M-OPEN / M-CLOSED modes, so the instrument stays in AUTOFILL and the modes are
  made with the documented fill-level commands. M-OPEN, M-CLOSED, and a fill
  timeout must be handled on the instrument's front panel; the buttons are greyed
  out then. The saved start level is kept in `ami1700_mode.json`, so a restart
  of the monitor finishes a Fill.
- **MAS3 is read-only**: the spin rate comes from `/DeviceStatus.html`, the
  pressures from reading the Manual Rotation page with a login session. The
  program only submits the login and logout forms, never a Manual Rotation form.
  (If you open that page in a browser yourself: Bruker binds W/S/A/D keys there
  to pressure changes.)
- In manual spinning, Bruker's "Rotation state" reads Error or Pending even when
  everything is fine; the monitor ignores it and flags only real faults (e.g.
  spin-rate cable disconnected).
- **Dark mode**: checkbox at the top left (shared setting with the viewer,
  stored in `~/.dnp_monitor_theme`).

### The log viewer

Open it with the button at the top of the monitor, or on its own:

```bash
python3 /home/nmrsu/dnp_monitor/dnp_logviewer.py [--start "2026-11-01 08:00" --stop "2026-11-02 08:00"]
```

- One panel per instrument, with small stacked subplots per unit and one shared
  time axis. Every logged variable has a checkbox; each instrument has a master
  checkbox. Colours follow the monitor.
- Time range: From/To (local time), *Last* 1 h to 30 d, and *Now* (end follows
  the present, refreshes every 30 s). *< Previous range* goes back.
- Long ranges are drawn as a min/max envelope; zooming in with the toolbar
  re-reads that span at full resolution. A box shows progress and an estimate
  while loading; *Cancel* stops it.
- *Export CSV* (full resolution, ticked variables) and *Export PNG* both use the
  time span on screen; files go to `exports/` in the base folder.
- Read-only: it never changes the logs (including the gzipped ones).

### Logs and housekeeping

| Folder | Content | Rate |
|---|---|---|
| `mas_logs/<controller>/` | spin rate, signal, status, pressures | 1 s |
| `lakeshore336_logs/` | full readout (`*.csv`) and fast temperature file (`*_fast.csv`) | 5 s / 3 s |
| `ami1700_logs/` | level, fill levels, state, valve, alarms, events (mode changes) | `poll_seconds` |

A new file starts every 24 h. Files are gzipped 2 days after their last write
and deleted after 365 days (`COMPRESS_AFTER_DAYS`, `DELETE_AFTER_DAYS` in
`dnp_monitor.py`); about 1.4 GB per year with both controllers. Each action is
noted in `housekeeping.log`. Read a gzipped log with `zcat`, or
`pandas.read_csv` directly.

### Changing the code

The programs were written with Claude, and further changes can be made the same
way: open this repository in Claude Code (or a Claude session with the
repository attached), describe the change, and have it commit and push. Then
`git pull` on the Topspin PC and restart the monitor.

Points worth keeping when changing things:

- Python 3.6 compatibility (no `datetime.fromisoformat`, no walrus operator,
  etc.); the Topspin PC runs Python 3.6.9 with matplotlib 3.3.4 and numpy 1.19.5.
- Fixed widget sizes: readouts must not move or resize as values change.
- Every instrument write stays behind Control, is read back, and is not retried.
- MAS3 stays read-only.
