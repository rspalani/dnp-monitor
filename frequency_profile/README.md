# DNP frequency profiles and build-ups

Acquisition and live display of DNP frequency profiles and build-up curves on
the 800 MHz DNP spectrometer (TopSpin 3.6.2). For a profile, a TopSpin script
steps the mm-wave frequency through the AWG, acquires and processes one record
per frequency, and a viewer plots the enhancement against frequency while the
records come in. For a build-up, a second script acquires one record per
build-up time D1, at one frequency or with the microwaves off, and the viewer
plots and fits the intensity against D1. A third TopSpin script applies the
phase set in the viewer to the TopSpin data after a run.

The headers of `fs_core.py`, `fs_plot.py`, and `fs_rephase_core.py` describe in
detail what each program does; this page covers installation and use.

## Files

| In this folder | Installed as | What it is |
|---|---|---|
| `dnptools/fs_core.py` | `/opt/dnptools/fs_core.py` | Acquisition code (TopSpin/Jython), for profiles and build-ups: plan, checks, confirmation dialog, AWG commands, records, run folder, viewer |
| `dnptools/fs_plot.py` | `/opt/dnptools/fs_plot.py` | Viewer (Python 3): profile or build-up with fits, one record at a time, phase/baseline/window, exports |
| `dnptools/fs_rephase_core.py` | `/opt/dnptools/fs_rephase_core.py` | Post-run phasing of the TopSpin data with the viewer's phase |
| `dnptools/awg_cmd.py` | `/opt/dnptools/awg_cmd.py` | Sends one command to the AWG control server (set its address; see below) |
| `topspin/fs.py` | `/opt/topspin3.6.2/exp/stan/nmr/py/user/fs.py` | TopSpin command `fs <name>` (profile) |
| `topspin/bu.py` | `/opt/topspin3.6.2/exp/stan/nmr/py/user/bu.py` | TopSpin command `bu <name>` (build-up) |
| `topspin/fs_rephase.py` | `/opt/topspin3.6.2/exp/stan/nmr/py/user/fs_rephase.py` | TopSpin command `fs_rephase` |
| `settings/settings_template.py` | `/opt/nmrdata/fs_settings/` | Template for the settings files, one per kind of experiment |
| `settings/settings_p1.py`, `settings_bdpa.py`, `settings_nox.py` | `/opt/nmrdata/fs_settings/` | Settings for the P1 diamond, BDPA, and m-TinyPol profiles |
| `settings/buildup_template.py` | `/opt/nmrdata/fs_settings/` | Template for the build-up settings files |
| `settings/buildup_p1.py`, `buildup_bdpa.py`, `buildup_nox.py` | `/opt/nmrdata/fs_settings/` | Build-up settings for the same samples (set `FREQ` before the first run) |

The TopSpin scripts only start the code in `/opt/dnptools` (with `execfile`,
so that TopSpin always runs the current version without being restarted).

## Requirements

- TopSpin 3.6.2 (its Jython 2.7 runs `fs.py`, `bu.py`, and `fs_rephase.py`).
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
sudo cp topspin/fs.py topspin/bu.py topspin/fs_rephase.py /opt/topspin3.6.2/exp/stan/nmr/py/user/
sudo chmod a+r /opt/topspin3.6.2/exp/stan/nmr/py/user/fs.py /opt/topspin3.6.2/exp/stan/nmr/py/user/bu.py \
               /opt/topspin3.6.2/exp/stan/nmr/py/user/fs_rephase.py

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

## Running a build-up

A build-up acquires one record per build-up time D1. The template's pulse
program must saturate before D1, so that every scan starts from zero
polarization and D1 is the build-up time.

1. Make a build-up settings file, or use an existing one:

   ```bash
   cp /opt/nmrdata/fs_settings/buildup_template.py /opt/nmrdata/fs_settings/buildup_<name>.py
   ```

   It has the same dataset, template, timing, and live-plot settings as a
   profile, and instead of the frequencies:
   - `SERIES`: the records of each set: `"on"` (microwaves at `FREQ`), `"off"`,
     `"interleaved"` (ON and OFF at each D1, back to back; only where the OFF
     signal can be measured at every D1), `"on_then_off"`, or `"off_then_on"`.
   - `FREQ` (GHz) and `POWER`: the AWG's `cw` command, sent before each ON
     record (`stop` is sent before each OFF record). The example files have
     `FREQ = None`, so that a run cannot start before a frequency is chosen.
   - `D1_LIST`: the build-up times in s, acquired in the order written.
     `logspace(first, last, n)` gives `n` log-spaced values; about 0.05 to 5
     times the expected T_B covers the curve and its plateau.
   - `NS_LIST` (and `OFF_NS_LIST` for the OFF records): one number of scans
     for all, or one per D1. `ns_for_time(D1_LIST, seconds, ns_max=...,
     multiple=..., overhead=SCAN_OVERHEAD)` gives records of about `seconds`
     each, with more scans at short D1, rounded to a multiple of the phase
     cycle.

   The examples: `buildup_p1.py` (room temperature, T_B expected at 6–7 min:
   D1 15 to 2000 s, about 2 h; a comment gives values for 100 K),
   `buildup_bdpa.py` (100 K, T_B about 30 s: D1 1 to 150 s, about 40 min), and
   `buildup_nox.py` (100 K, T_B 6–7 s: D1 0.25 to 35 s, about 25 min), each
   with `SERIES = "on"`.
2. In TopSpin, type `bu <name>` (`bu` alone lists the build-up settings files).
   If `bu` runs something else on this TopSpin, the name is taken: rename
   `bu.py` (e.g. to `fsbu.py`) and type that name instead.
3. The confirmation dialog lists the plan, the mm-wave setting, every D1 with
   its NS, and the expected duration; the expno checks are as for a profile.

The run folder is in `fs_runs` as for a profile, labelled `bu_<name>`; `run.txt`
has `# type = buildup` and the D1 of each record, and `settings.txt` lists every
planned record with its expected duration (the viewer uses it for the expected
end). A profile settings file given to `bu`, or a build-up file given to `fs`,
is refused with a message that says which command to use.

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

### Build-up runs in the viewer

The viewer recognizes a build-up run by its `run.txt` and plots the intensity
per scan (or FID(t0)) against D1: ON as filled circles, OFF as open squares,
each series with its fitted curve. With both ON and OFF shown, OFF has its own
axis on the right.

- "Fit" chooses the model, fitted to each series by least squares weighted by
  NS (the noise of an intensity per scan goes as 1/√NS), with standard errors
  from the scatter about the fit:
  - mono-exponential (default), S∞·(1 − exp(−D1/T_B));
  - mono-exponential with a free start, S∞ − (S∞ − S₀)·exp(−D1/T_B), for a
    saturation that leaves a residual S₀;
  - stretched exponential, S∞·(1 − exp(−(D1/T_B)^β)), β between 0.1 and 3;
  - bi-exponential, S₁·(1 − exp(−D1/T₁)) + S₂·(1 − exp(−D1/T₂)).
- Each fitted series gets one row above the plot: the build-up time(s), S∞,
  the other parameters, and the largest signal per square root of time, S/√t,
  with the D1 where it occurs (1.26 T_B for the mono-exponential). With ON and
  OFF in the same set, an "ON/OFF" row gives the ratios of S∞ and of the
  largest S/√t. A fit whose build-up time lies beyond the range the D1 values
  can determine (for example while a run has only reached the rising part) is
  shown as "not determined", with a dashed curve and no ratios; a "Note" row
  says when S∞ is extrapolated beyond the longest D1.
- "log D1" makes the D1 axis logarithmic; "normalized" divides each series by
  its fitted S∞, on one axis, to compare the build-up times.
- The record pane, its settings, "Apply to all records", FID(t0), and the FID
  phase work as for a profile; the window integral is not plotted.
- "Export: Build-up EPS" writes `buildup.eps` (as shown, same format as the
  profile EPS). `values.tsv` has the D1 and the fitted value of each record and
  the fit results in its header; `records.csv` has a `d1_s` column.
- The expected end of a running build-up is the sum of the expected durations
  of the records still to come, and the amber "No new record" appears only when
  the next record is overdue, so a long record late in the run is not reported
  as a problem.

## Phasing the TopSpin data after a run

Set the phase in the viewer and press "Apply to all records"; this writes
`phase.txt` in the run folder. Then, with no acquisition running, type
`fs_rephase` in TopSpin and choose the run's `run.txt`. The script measures
TopSpin's phase convention on the first record, checks that it reproduces the
viewer's phase, asks for confirmation, and reprocesses every record with the
new PHC0 and PHC1. Everything is logged in `rephase.log` in the run folder.
This works for build-up runs as well.
