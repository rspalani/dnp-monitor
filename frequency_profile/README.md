# DNP frequency profiles

Acquisition and live display of DNP frequency profiles on the 800 MHz DNP
spectrometer (TopSpin 3.6.2). A TopSpin script steps the mm-wave frequency
through the AWG, acquires and processes one record per frequency, and a viewer
plots the enhancement against frequency while the records come in. A second
TopSpin script applies the phase set in the viewer to the TopSpin data after the
run.

The headers of `fs_core.py`, `fs_plot.py`, and `fs_rephase_core.py` describe in
detail what each program does; this page covers installation and use.

## Files

| In this folder | Installed as | What it is |
|---|---|---|
| `dnptools/fs_core.py` | `/opt/dnptools/fs_core.py` | Acquisition code (TopSpin/Jython): plan, checks, confirmation dialog, AWG commands, records, run folder, viewer |
| `dnptools/fs_plot.py` | `/opt/dnptools/fs_plot.py` | Viewer (Python 3): profile, one record at a time, phase/baseline/window, exports |
| `dnptools/fs_rephase_core.py` | `/opt/dnptools/fs_rephase_core.py` | Post-run phasing of the TopSpin data with the viewer's phase |
| `dnptools/awg_cmd.py` | `/opt/dnptools/awg_cmd.py` | Sends one command to the AWG control server (set its address; see below) |
| `topspin/fs.py` | `/opt/topspin3.6.2/exp/stan/nmr/py/user/fs.py` | TopSpin command `fs <name>` |
| `topspin/fs_rephase.py` | `/opt/topspin3.6.2/exp/stan/nmr/py/user/fs_rephase.py` | TopSpin command `fs_rephase` |
| `settings/settings_template.py` | `/opt/nmrdata/fs_settings/` | Template for the settings files, one per kind of experiment |
| `settings/settings_p1.py`, `settings_bdpa.py`, `settings_nox.py` | `/opt/nmrdata/fs_settings/` | Settings for the P1 diamond, BDPA, and m-TinyPol profiles |

The two TopSpin scripts only start the code in `/opt/dnptools` (with `execfile`,
so that TopSpin always runs the current version without being restarted).

## Requirements

- TopSpin 3.6.2 (its Jython 2.7 runs `fs.py` and `fs_rephase.py`).
- `python` on the PATH, Python 2.7 or 3, for `awg_cmd.py`.
- For the viewer: `/usr/bin/python3` (3.6 or newer) with `numpy`, `matplotlib`
  (3.3 or newer), and `python3-tk`. Without a display the viewer writes its
  files only. Keep the code compatible with Python 3.6 and matplotlib 3.3, the
  versions on the spectrometer PC.

## Installation and updates

From the clone of this repository in `/home/nmrsu/src/dnp-tools` (see the main
README):

```bash
cd /home/nmrsu/src/dnp-tools && git pull
cd frequency_profile

# programs (-n: an existing awg_cmd.py, with the real address, is kept)
sudo mkdir -p /opt/dnptools
sudo cp dnptools/fs_core.py dnptools/fs_plot.py dnptools/fs_rephase_core.py /opt/dnptools/
sudo cp -n dnptools/awg_cmd.py /opt/dnptools/
sudo chmod a+r /opt/dnptools/*.py

# TopSpin commands
sudo cp topspin/fs.py topspin/fs_rephase.py /opt/topspin3.6.2/exp/stan/nmr/py/user/
sudo chmod a+r /opt/topspin3.6.2/exp/stan/nmr/py/user/fs.py /opt/topspin3.6.2/exp/stan/nmr/py/user/fs_rephase.py

# settings (-n: settings files already on the spectrometer are kept)
sudo mkdir -p /opt/nmrdata/fs_settings
sudo cp -n settings/*.py /opt/nmrdata/fs_settings/
sudo chown -R nmrsu /opt/nmrdata/fs_settings      # editable by the TopSpin user
```

On a new installation, set `HOST` (and `PORT`) in `/opt/dnptools/awg_cmd.py` to
the AWG control server's address: the repository keeps a placeholder, as it does
for the monitor's instrument addresses. The settings files are edited on the
spectrometer; to replace one with the repository's version, copy it without `-n`.

A viewer that is already open keeps running the old code; close it and reopen
it with the command shown in its window.

## Running a profile

1. Make a settings file for the kind of experiment, or use an existing one:

   ```bash
   cp /opt/nmrdata/fs_settings/settings_template.py /opt/nmrdata/fs_settings/settings_<name>.py
   ```

   It is Python with plain assignments: `SAMPLE`, `MAS_INFO`, the dataset
   (`DATA_DIR`, `DATA_NAME`, `TEMPLATE_EXPNO`; left empty, the dataset and
   expno open in TopSpin are used), `START_EXPNO`, `REPEATS`, `OFF_MODE`, the
   frequencies `FREQS` (with `frange(start, stop, step)`), `D1`, `PROFILE_NS`,
   `OFF_SCANS`, and the processing commands. An UPPERCASE name that is not a
   known setting stops the run before anything starts, so typos are caught.
2. In TopSpin, open the dataset and template expno if the settings file leaves
   them empty, and type `fs <name>` (`fs` alone lists the settings files).
3. The confirmation dialog shows the dataset, the new expnos, and the template.
   The script checks that all planned expnos are free, before the dialog and
   again after OK.
4. The viewer opens by itself. If its window is closed, it is opened again
   after the next record.

Each run gets a folder inside the dataset,
`<dataset>/fs_runs/<YYYYMMDD-HHMMSS>_<label>_e<start expno>/`, with `run.txt`
(one line per finished record), `log.txt`, `settings.txt` (every setting as
used), a copy of the settings file, and the viewer's files (`viewer.log`,
`plot.png`, `values.tsv`, `phase.txt`, and `records.csv` and `profile.eps` when
exported). The folder travels with the dataset when it is copied. One line per
run start and end is added to `/opt/nmrdata/fs_runs.tsv`.

## The viewer

It opens by itself during a run; to open it later, for any run:

```bash
python3 /opt/dnptools/fs_plot.py <dataset>/fs_runs/<run folder>/run.txt
```

(the exact command is shown in the window and in `viewer.log`). With `--once`,
or without a display, it writes `plot.png` and `values.tsv` and exits;
`--csv` also writes `records.csv`.

- The top bar has the "Reopen" command (to copy), "Also plot", "Export", and
  "Hide spectrum", which hides the whole spectrum side and leaves the profile
  across the window ("Show spectrum" brings it back).
- Above the profile, the run's status: a blinking red dot and "Experiment
  running" (with the record reached out of those planned, and the expected
  end), "Finished", "Stopped before the end" in red when the run was aborted
  or stopped from TopSpin, or an amber "No new record for N min". "Live"
  refreshes the window every 15 s; it turns itself off when the run ends and
  is off when an ended run is opened. "Refresh" updates the window once, for
  example after reprocessing in TopSpin. Below the status, one row each for
  the run, the intensity measure and processing, the OFF records, and any
  warnings.
- The profile is on the left and one record on the right, with a divider that
  can be dragged. The right side follows the latest record while
  "Follow latest" is ticked; a record chosen in the list, with "< Prev" and
  "Next >" (or Page Up and Page Down), or by clicking a point of the profile
  is shown instead.
- The controls along the bottom ("Hide controls" under the spectrum hides
  them) try settings on the record shown: zero- and first-order phase with a
  pivot, magnitude, polynomial baseline, the
  intensity window (typed, or dragged with the right mouse button), and the
  intensity measure. "Apply to all records" applies them to the whole profile.
  All of this is in the viewer only; the TopSpin data are unchanged until
  `fs_rephase` is run.
- Intensity measures: `extreme` (largest |value| in the window, sign kept),
  `max`, `sum`, and `FID(t0)`, a diagnostic that uses the start of the raw FID
  instead of the spectrum (independent of phase, window, and baseline), with
  the FID phase as an optional panel below the profile.
- "Also plot" adds the integral of the window, or the FID phase.
- "Export: Profile EPS" writes `profile.eps` for Adobe Illustrator (Helvetica
  text, one path per trace and per marker, no clipping masks), 7 in wide, the
  full page width of ACS journals (Elsevier's is 190 mm), and as high as the
  profile on screen is in proportion (2 to 5 in). "Export: CSV" writes
  `records.csv` (one row per record, with FID(t0), the FID phase, and the
  window integrals).
- The window's size and position, the divider, and whether the spectrum side
  is shown are saved in `~/.config/fs_plot/window.txt`, so the next viewer
  opens the same way.

## Phasing the TopSpin data after a run

Set the phase in the viewer and press "Apply to all records"; this writes
`phase.txt` in the run folder. Then, with no acquisition running, type
`fs_rephase` in TopSpin and choose the run's `run.txt`. The script measures
TopSpin's phase convention on the first record, checks that it reproduces the
viewer's phase, asks for confirmation, and reprocesses every record with the
new PHC0 and PHC1. Everything is logged in `rephase.log` in the run folder.
