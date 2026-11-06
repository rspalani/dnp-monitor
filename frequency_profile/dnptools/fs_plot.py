#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fs_plot.py  -  plot a DNP frequency profile from a run file of fs_core.py
(system Python 3.6+, numpy, matplotlib; tkinter for the window)

    python3 fs_plot.py RUNFILE [--ppm 37] [--width 20] [--mode extreme|max|sum|FID(t0)]
                               [--interval 15] [--once] [--csv]

RUNFILE is <dataset>/fs_runs/<run id>/run.txt, written by the acquisition
scripts (fs_p1.py, fs_bdpa.py, fs_nox.py through /opt/dnptools/fs_core.py).
Run files of the earlier scripts, <dataset>/fs_<name>_live_run_<START_EXPNO>.txt,
are read as well. For every record listed in the run file, the script reads the
processed spectrum (pdata/1/1r, 1i and procs) and NS (acqus), and takes one
intensity per record from a window of --width ppm centred at --ppm (the whole
spectrum if the run file has peak_ppm = none):
    extreme : the point with the largest |value|, sign kept (default)
    max     : the largest value (for magnitude spectra, 'mc')
    sum     : the sum of the points in the window
    FID(t0) : the start of the raw FID instead of the spectrum (see below;
              on a shell command line write --mode 'FID(t0)' or --mode fid)
Intensities are divided by NS (FID(t0) by NS*RG). If the run has start OFF records, the profile
is plotted as I_on/I_off - 1, each set (REPEATS > 1) against the start OFF of
the same set; otherwise as intensity per scan. End OFFs are reported relative
to the start OFF of their set.

The expnos are looked for in the dataset that contains the fs_runs folder, so
a dataset copied or moved together with its fs_runs folder is read from its
new place; for an older run file, in dataset_dir from the run file.

The defaults for --ppm, --width and --mode come from the run file. The plot is
refreshed every --interval s, also after the run has ended, so that data
reprocessed in TopSpin show up; the window stays open until it is closed.
--once draws a single time and exits. Every update also writes plot.png and
values.tsv next to run.txt (<RUNFILE without .txt>_plot.png and _values.tsv
for an older run file). Without a display, only these files are written, and
the script exits once the run has ended.

Window: profile, spectrum side, and controls
    The window shows the profile on the left and one record on the spectrum
    side on the right, with a divider that can be dragged; the controls of
    the spectrum side are in a strip along the bottom ('Hide controls' under
    the spectrum hides them). 'Hide spectrum' (top bar) hides the whole
    spectrum side with its controls, leaving the profile across the window.

    Above the profile, the status of the run: a blinking red dot with
    'Experiment running' while the run goes on (with the record reached out of
    those planned, from settings.txt in the run folder, and the expected end),
    'Finished' when fs_core.py has written '# end: complete', 'Stopped before
    the end' in red when the run was aborted or stopped from TopSpin, and an
    amber 'No new record for N min' when the run file has no end line but has
    not grown for much longer than usual. 'Live' refreshes the window every
    --interval s; it is off from the start for a run that has ended, and turns
    itself off when the run ends ('Refresh' updates the window once, e.g. after
    reprocessing; ticking 'Live' again keeps it on). Below that, the run, the
    intensity measure and processing, the OFF records and any warnings, one row
    each.

    The spectrum side shows the latest record while 'Follow latest' is
    ticked. Choosing a record in its list ('Record'), clicking a point of the
    profile (or of the FID phase), or '< Prev' and 'Next >' (also Page Up and
    Page Down) show another record and untick it; so does touching a phase,
    baseline or window control, so that a new record does not replace the one
    being worked on. Ticking it again shows the latest record. Moving between
    records keeps the zoom. 'Spectrum' and 'FID start' switch between the
    spectrum and the start of the FID (FID start whenever the mode is switched
    to FID(t0)). The size and position of the window, the divider, and whether
    the spectrum side is shown are saved in ~/.config/fs_plot/window.txt when
    the window is closed, and the next viewer opens the same way.

    These settings can be tried on the record shown, with the record as
    processed by TopSpin drawn in grey for comparison:
      - a zero- and first-order phase correction (PH0 and PH1 in degrees; PH1
        is the change across the full spectral width, PH0 the correction at
        the pivot, which is set by a left click in the spectrum);
      - magnitude mode, |1r + i*1i|, instead of the phase correction;
      - a polynomial baseline correction;
      - the intensity window (centre and width, or the whole spectrum) and the
        intensity mode; dragging with the right mouse button in the spectrum
        sets the window, a right click moves it there.
    'Apply to all records' applies them to every record, including later ones,
    and redraws the main window; 'Changes not applied yet' next to it means the
    settings shown differ from the applied ones. The y axis is rescaled to the visible traces
    when the record, magnitude, baseline, or (with baseline) the window changes;
    while PH0, PH1, or the pivot are adjusted it is held, so that successive
    phase changes can be compared ('Fit y' rescales it at any time).

    'Also plot: window integral' (main window) adds the integral of
    the same window, with the same corrections, as a second series: the sum of
    the points times the point spacing in ppm, per scan. With start OFFs it is
    plotted as integral_on/integral_off - 1 on the same axis as the peak
    values; otherwise on a right-hand axis. It is not shown separately when the
    intensity mode is 'sum', which is already that integral up to the point
    spacing. The TSV always has the columns integral_per_scan and y_integral.

    Phase and magnitude are computed from 1r and 1i; TopSpin's data are not
    changed. The phase correction is a correction on top of TopSpin's
    processing (efp; absn) and is applied to the records processed with the
    same PHC0/PHC1 as the record it was set on; records processed with other
    values are shown as processed. The settings are kept in phase.txt next to
    run.txt, so that a reopened viewer uses them, and the TopSpin script
    fs_rephase.py can apply the phase to the data themselves. A window given
    with --ppm, --width or --mode takes precedence over the one in phase.txt
    until a window is applied in the spectrum pane.

    The baseline correction fits a polynomial of the chosen order to the
    points outside the intensity window, leaving out peaks: points more than
    3 robust standard deviations from the fit, and 0.25 % of the spectrum on
    either side of them, are excluded and the fit is repeated until the
    excluded points no longer change. It cannot remove a baseline that is
    distorted across the whole spectrum.

FID(t0) mode
    For each record the raw fid is read (acqus: DTYPA 0 = int32, multiplied by
    2**NC, or 2 = float64; BYTORDA 0 = little-endian, 1 = big-endian) as complex
    points c = f[0::2] + i*f[1::2]. With g = ceil(GRPDLY), the first point after the
    group delay of the digital filter, the value is mean(|c[g:g+N]|) or, with the
    linear fit, a straight line fitted to |c[g:g+N]| against the point index and
    evaluated at t = GRPDLY, the time origin (up to one dwell before g); either is
    divided by NS*RG. N (default 4) and the fit are set in the spectrum pane
    next to the mode and applied with it. The value depends on none of the phase,
    magnitude, baseline and window settings; these are disabled in the spectrum
    controls while the mode is FID(t0), and choosing another mode there enables them
    again (they still set the spectrum shown and the window integral). A record
    whose acqus has no GRPDLY, or a negative one, gets no value, with a warning
    in the plot, the TSV, the CSV and the viewer's output. In this mode the
    right-hand panel of plot.png shows the start of the latest FID, with GRPDLY, g
    and the N points marked, as does 'FID start' in the window for the record shown.

    The FID phase is arg(mean(c[g:g+N])) in degrees, relative to the median over
    all ON records (the median is taken about their circular mean, so the step at
    +/-180 deg does not matter) and wrapped to (-180, 180]. 'Show the FID phase'
    (main window) plots it against the mm-wave frequency in a panel below the
    profile, in any mode.

EPS export (for Adobe Illustrator)
    'Export: Profile EPS' writes profile.eps next to run.txt (<RUNFILE without
    .txt>_profile.eps for an older run file), overwriting the previous one: the
    profile as shown (with the window integral and the FID phase if these are
    shown), without the lines above the plot, the grid or the marker of the latest
    record, over the whole profile, 7 in wide (the full page width of ACS
    journals; Elsevier's is 190 mm) and as high as the window's profile is in
    proportion (2 to 5 in). The text is Helvetica text (editable in
    Illustrator), each trace is one path and each marker its own path, and nothing is
    clipped to the axes, so that Illustrator shows no clipping masks.

CSV export
    'Export: CSV' (main window), or --csv, writes records.csv next to run.txt
    (<RUNFILE without .txt>_records.csv for an older run file) with one row per
    record: expno, set, kind, label, mm-wave frequency, acquisition time (acqus
    DATE), NS, RG, GRPDLY, |FID(t0)| per NS*RG as the mean and as the linear fit,
    the FID phase (relative and absolute), and the real and magnitude integrals of
    the current window per scan, with the applied phase and baseline settings.
    Lines starting with # describe these settings (MATLAB: readtable(f,
    'CommentStyle', '#'); pandas: read_csv(f, comment='#')). With --csv the file is
    rewritten whenever the PNG and TSV are.

Build-up runs
    A run file with '# type = buildup' (written by bu.py through fs_core.py) has
    one record per build-up time D1 (eighth column), ON (microwaves on) or OFF.
    The window and plot.png then show the intensity per scan (or FID(t0) per
    NS*RG) of the ON and OFF records against D1, each series of each set with a
    fitted curve, chosen with 'Fit' (main window):
      mono-exponential               S_inf*(1 - exp(-D1/T_B))   (default)
      mono-exponential, free start   S_inf - (S_inf - S_0)*exp(-D1/T_B), for a
                                     saturation that leaves S_0
      stretched exponential          S_inf*(1 - exp(-(D1/T_B)^beta)), beta 0.1 to 3
      bi-exponential                 S_1*(1 - exp(-D1/T_1)) + S_2*(1 - exp(-D1/T_2))
    The fits are least squares weighted by NS (the noise of an intensity per scan
    goes as 1/sqrt(NS)), with standard errors from the scatter about the fit. For
    each fit the largest signal per square root of the build-up time, S/sqrt(D1),
    is given with the D1 where it occurs (1.26 T_B for the mono-exponential; for
    the free start, from the rise above S_0); with ON and OFF in the same set,
    also the ratios S_inf(ON)/S_inf(OFF) and of these maxima. With ON and OFF
    shown, OFF is on a right-hand axis; 'normalized' divides each series by its
    fitted S_inf instead, on one axis, to compare the build-up times. 'log D1'
    makes the D1 axis logarithmic. The record pane, its phase, baseline and
    window settings, FID(t0), the FID phase and the exports work as for a
    profile; the window integral is not plotted. values.tsv then has the D1 and
    the fitted value of each record and the fit results in its header,
    records.csv a d1_s column, and 'Export: Build-up EPS' writes buildup.eps.
    The expected end of a running build-up is the sum of the expected durations
    of the records still to come (from settings.txt), and the run counts as
    quiet only when the next record is overdue.

Error bars ('Error bars' in the main window; error_bars in phase.txt)
    noise floor  +/-1 sigma of each record from the noise of its own spectrum: the
                 points outside the intensity window (the whole spectrum if there is
                 none) less a cubic, with peaks excluded as in the baseline fit, or the
                 ppm range given in the row below the top bar, less a straight line;
                 the spectrum is taken with the applied phase, magnitude and baseline
                 settings. 'sum' and the window integral: the sigma of a sum of the m
                 points of the window, from sigma and the autocorrelation of the noise
                 (zero filling and apodization correlate neighbouring points);
                 'extreme' and 'max': sigma of one point, an upper bound (when the peak
                 top spans several points the maximum scatters less, by up to a factor
                 of about 1.5 for white noise); FID(t0): from the noise of the last
                 quarter of the fid (sigma/sqrt(N) for the mean, the extrapolation error
                 of the line for the fit). Divided by NS (FID(t0): NS*RG); for
                 I_on/I_off - 1 combined with the sigma of the start OFF of the set.
    repeats      the mean of the records at the same frequency (profile) or D1
                 (build-up, ON and OFF separately) over the sets (and a D1 repeated in
                 D1_LIST), +/- its standard error, std/sqrt(n); one series instead of one
                 per set. A point from one record has no bar.
    For build-ups, 'weight the fits by 1/sigma^2' (fit_sigma) fits with these sigmas
    instead of NS and takes the standard errors from them; chi2/dof then compares the
    scatter with the error bars (about 1 if the noise explains it). With repeats, this
    needs at least 3 records at every D1; otherwise the fit stays weighted by NS. With
    error bars on, values.tsv and records.csv get the sigma (or mean, standard error,
    and number of records) of each record; with them off, the files are as before.

The terminal command that reopens this plot for this run file (including any
--ppm, --width, --mode and --csv given) is shown in the window title, in the
'Reopen' field of the top bar (to copy), along the bottom of plot.png, and in the
viewer's output (viewer.log when the acquisition script started the viewer).
plot.png keeps its layout: the profile and the latest spectrum (or FID start).
"""
import argparse
import csv
import math
import os
import re
import shlex
import shutil
import sys
import time
import warnings
from collections import OrderedDict

import numpy as np
import matplotlib
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.backends.backend_agg import FigureCanvasAgg

try:
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk
except ImportError:          # no python3-tk: files only
    tk = ttk = tkfont = None


# --------------------------------------------------------------------------
# Run file
# --------------------------------------------------------------------------
def read_run(path):
    """Returns (meta, rows, ended). ended is None while the run is going."""
    meta, rows, ended = {}, [], None
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if line.startswith("#"):
                body = line[1:].strip()
                if body.startswith("end:"):
                    ended = body[4:].strip()
                else:
                    m = re.match(r"(\w+)\s*=\s*(.*)$", body)
                    if m:
                        meta[m.group(1)] = m.group(2).strip()
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            try:
                row = {
                    "expno": int(parts[0]),
                    "kind": parts[1],
                    "label": parts[2],
                    "freq": None if parts[3] in ("", "-") else float(parts[3]),
                    "ns_run": int(parts[4]),
                    "finished": parts[5] if len(parts) > 5 else "",
                    "set": 1,
                    "d1": None,
                }
            except ValueError:
                continue
            if len(parts) > 6:
                try:
                    row["set"] = int(parts[6])
                except ValueError:
                    pass
            if len(parts) > 7:                  # build-up runs: D1 in s
                try:
                    row["d1"] = float(parts[7])
                except ValueError:
                    pass
            rows.append(row)
    return meta, rows, ended


def parse_center(text):
    """peak_ppm from the run file; None (whole spectrum) for 'none'."""
    if text is None or text.strip().lower() in ("", "none"):
        return None
    return float(text)


# --------------------------------------------------------------------------
# TopSpin data
# --------------------------------------------------------------------------
PROCS_KEYS = ["SI", "OFFSET", "SW_p", "SF", "BYTORDP", "NC_proc", "DTYPP", "PHC0", "PHC1"]


def jcamp_params(path, keys):
    with open(path, errors="replace") as fh:
        txt = fh.read()
    out = {}
    for k in keys:
        m = re.search(r"^##\$%s=\s*(\S+)" % re.escape(k), txt, re.M)
        if m:
            out[k] = m.group(1)
    return out


def read_binary(path, p, si):
    endian = ">" if int(p.get("BYTORDP", "0")) == 1 else "<"
    if int(p.get("DTYPP", "0")) == 0:
        data = np.fromfile(path, dtype=endian + "i4").astype(float)
        data *= 2.0 ** int(p.get("NC_proc", "0"))
    else:
        data = np.fromfile(path, dtype=endian + "f8")
    return data[:si]


def file_key(expdir):
    """(mtime of 1r, mtime of 1i or None). Raises IOError without 1r."""
    pdir = os.path.join(expdir, "pdata", "1")
    f1r = os.path.join(pdir, "1r")
    if not os.path.exists(f1r):
        raise IOError("no processed spectrum (pdata/1/1r)")
    f1i = os.path.join(pdir, "1i")
    return (os.path.getmtime(f1r), os.path.getmtime(f1i) if os.path.exists(f1i) else None)


def read_spectrum(expdir):
    """Returns a dict: ppm, re, im (None if 1i is missing or stale, reason in
    im_note), ns, phc0, phc1, si, offset, sw_p, sf. Raises an exception with a
    reason if 1r cannot be used."""
    pdir = os.path.join(expdir, "pdata", "1")
    f1r = os.path.join(pdir, "1r")
    f1i = os.path.join(pdir, "1i")
    if not os.path.exists(f1r):
        raise IOError("no processed spectrum (pdata/1/1r)")
    p = jcamp_params(os.path.join(pdir, "procs"), PROCS_KEYS)
    for k in ("SI", "OFFSET", "SW_p", "SF"):
        if k not in p:
            raise ValueError("procs has no %s" % k)
    si = int(p["SI"])
    re_ = read_binary(f1r, p, si)
    if re_.size == 0:
        raise ValueError("1r is empty")
    acq = jcamp_params(os.path.join(expdir, "acqus"), ["NS"])
    if "NS" not in acq:
        raise ValueError("acqus has no NS")
    ns = int(acq["NS"])
    # 1r must have been written after the acquisition, not copied from the template
    audita = os.path.join(expdir, "audita.txt")
    t_acq = os.path.getmtime(audita) if os.path.exists(audita) else None
    if t_acq is not None and os.path.getmtime(f1r) < t_acq - 2:
        raise ValueError("1r is older than the acquisition (not processed?)")
    im, im_note = None, ""
    if not os.path.exists(f1i):
        im_note = "1i is missing"
    elif t_acq is not None and os.path.getmtime(f1i) < t_acq - 2:
        im_note = "1i is older than the acquisition"
    else:
        im = read_binary(f1i, p, si)
        if im.size != re_.size:
            im, im_note = None, "1i and 1r differ in size"
    offset, sw_p, sf = float(p["OFFSET"]), float(p["SW_p"]), float(p["SF"])
    ppm = offset - np.arange(re_.size) * sw_p / sf / si
    return {"ppm": ppm, "re": re_, "im": im, "im_note": im_note, "ns": ns,
            "phc0": float(p.get("PHC0", "0")), "phc1": float(p.get("PHC1", "0")),
            "si": si, "offset": offset, "sw_p": sw_p, "sf": sf}


FID_HEAD = 256       # complex points kept after g (the largest N)
ACQUS_KEYS = ["NS", "RG", "TD", "DTYPA", "BYTORDA", "GRPDLY", "NC", "DATE"]


def fid_file_key(expdir):
    """(mtime of fid, mtime of acqus). Raises IOError without a fid."""
    f = os.path.join(expdir, "fid")
    if not os.path.exists(f):
        raise IOError("no fid")
    a = os.path.join(expdir, "acqus")
    return (os.path.getmtime(f), os.path.getmtime(a) if os.path.exists(a) else None)


def read_fid(expdir):
    """The start of the raw FID and the acqus values FID(t0) needs. Returns a dict:
    c (complex points 0 .. g+FID_HEAD), grpdly (None if missing), g (None if GRPDLY is
    missing or negative, the reason in warn), ns, rg, date (acqus DATE, s since 1970,
    or None). Raises an exception with a reason if the fid cannot be read."""
    acq = jcamp_params(os.path.join(expdir, "acqus"), ACQUS_KEYS)
    for k in ("NS", "RG", "TD", "DTYPA", "BYTORDA"):
        if k not in acq:
            raise ValueError("acqus has no %s" % k)
    dtypa = int(float(acq["DTYPA"]))
    endian = ">" if int(float(acq["BYTORDA"])) == 1 else "<"
    if dtypa == 0:
        dtype, scale = endian + "i4", 2.0 ** int(float(acq.get("NC", "0")))
    elif dtypa == 2:
        dtype, scale = endian + "f8", 1.0
    else:
        raise ValueError("DTYPA = %d in acqus: only 0 (int32) and 2 (float64) are read" % dtypa)
    ns, rg = int(float(acq["NS"])), float(acq["RG"])
    if not (ns > 0 and rg > 0):
        raise ValueError("NS = %s, RG = %s in acqus: cannot divide by NS*RG" % (acq["NS"], acq["RG"]))
    grpdly, warn, g = None, "", None
    if "GRPDLY" not in acq:
        warn = "acqus has no GRPDLY"
    else:
        grpdly = float(acq["GRPDLY"])
        if grpdly < 0:
            warn = "GRPDLY = %g in acqus (no group delay given)" % grpdly
        else:
            g = int(math.ceil(grpdly))
    td = int(float(acq["TD"]))
    count = min(td, 2 * ((g if g is not None else 0) + FID_HEAD))
    f = np.fromfile(os.path.join(expdir, "fid"), dtype=dtype, count=count).astype(float) * scale
    f = f[:f.size // 2 * 2]
    date = float(acq["DATE"]) if "DATE" in acq else None
    return {"c": f[0::2] + 1j * f[1::2], "grpdly": grpdly, "g": g, "warn": warn,
            "ns": ns, "rg": rg, "date": date}


def fid_t0(fid, n):
    """|FID(t0)| per NS*RG from the N points c[g:g+N]: 'mean' = mean |c|, 'fit' = a line
    fitted to |c| against the point index, evaluated at t = GRPDLY (None for N < 2),
    'line' = (slope, intercept) of that line per NS*RG; 'phase' = arg(mean c) in deg.
    Raises ValueError with the reason if it cannot be computed."""
    if fid["g"] is None:
        raise ValueError("%s: FID(t0) not computed" % fid["warn"])
    g, c, n = fid["g"], fid["c"], int(n)
    if c.size < g + n:
        raise ValueError("the fid has %d complex points; FID(t0) needs g + N = %d" % (c.size, g + n))
    seg = c[g:g + n]
    mag = np.abs(seg)
    norm = float(fid["ns"]) * fid["rg"]
    out = {"mean": float(np.mean(mag)) / norm, "fit": None, "line": None,
           "phase": float(np.angle(np.mean(seg), deg=True))}
    if n >= 2:
        slope, icpt = np.polyfit(np.arange(g, g + n, dtype=float), mag, 1)
        out["fit"] = float(icpt + slope * fid["grpdly"]) / norm
        out["line"] = (float(slope) / norm, float(icpt) / norm)
    return out


def wrap_pm180(x):
    """Angle(s) in degrees wrapped to (-180, 180]."""
    return 180.0 - (180.0 - x) % 360.0


def phase_reference(deg):
    """Median of angles in degrees, taken about their circular mean so that the
    step at +/-180 does not matter."""
    a = np.asarray(deg, dtype=float)
    m = float(np.angle(np.mean(np.exp(1j * np.deg2rad(a))), deg=True))
    return m + float(np.median(wrap_pm180(a - m)))


def integrate(ppm, data, center, width):
    """Integral over the window (whole spectrum if center is None): the sum of the
    points times the point spacing in ppm."""
    if center is None:
        sel = np.ones(ppm.size, dtype=bool)
    else:
        sel = np.abs(ppm - center) <= width / 2.0
        if not np.any(sel):
            raise ValueError("window %.1f +/- %.1f ppm is outside the spectrum" % (center, width / 2.0))
    step = abs(float(ppm[0] - ppm[1])) if ppm.size > 1 else 1.0
    return float(np.sum(data[sel])) * step


def measure(ppm, data, center, width, mode):
    """Returns (value, ppm_of_point or None). center None = whole spectrum."""
    if center is None:
        sel = np.ones(ppm.size, dtype=bool)
    else:
        sel = np.abs(ppm - center) <= width / 2.0
        if not np.any(sel):
            raise ValueError("window %.1f +/- %.1f ppm is outside the spectrum (%.1f..%.1f ppm)"
                             % (center, width / 2.0, ppm.min(), ppm.max()))
    seg, segppm = data[sel], ppm[sel]
    if mode == "extreme":
        i = int(np.argmax(np.abs(seg)))
        return float(seg[i]), float(segppm[i])
    if mode == "max":
        i = int(np.argmax(seg))
        return float(seg[i]), float(segppm[i])
    return float(np.sum(seg)), None


# --------------------------------------------------------------------------
# Error bars: noise floor of a record, and repeated records
# --------------------------------------------------------------------------
ERROR_MODES = OrderedDict([("none", "none"), ("noise", "noise floor"), ("repeats", "repeats")])
NOISE_MIN_POINTS = 50       # noise points needed for an estimate
NOISE_LAGS = 64             # largest lag of the noise autocorrelation used for sums


def spectrum_noise(y, ppm, center, width, region=None):
    """The noise of a spectrum: (sigma of one point, autocorrelation rho[k-1] of the noise
    at lags k = 1.., mask of the noise points). region (lo, hi) ppm: those points, less a
    straight line; None: the points outside the intensity window (the whole spectrum if
    there is none) less a cubic, with peaks excluded as in the baseline fit (points more
    than 3 robust standard deviations from the fit, and their neighbours). sigma is the
    standard deviation of the remaining points about the fit. Raises ValueError if fewer
    than NOISE_MIN_POINTS points are left."""
    n = y.size
    x = np.linspace(-1.0, 1.0, n)
    if region is not None:
        lo, hi = min(region), max(region)
        mask0 = (ppm >= lo) & (ppm <= hi)
        order = 1
    else:
        mask0 = np.ones(n, dtype=bool) if center is None else np.abs(ppm - center) > width / 2.0
        order = 3
    if mask0.sum() < NOISE_MIN_POINTS:
        raise ValueError("noise region has %d points (at least %d needed)" % (mask0.sum(), NOISE_MIN_POINTS))
    pad = max(2, n // 400)
    idx_all = np.arange(n)
    lo_i = np.clip(idx_all - pad, 0, n)
    hi_i = np.clip(idx_all + pad + 1, 0, n)
    mask = mask0.copy()
    r = None
    for _ in range(20):
        idx = np.nonzero(mask)[0]
        coef = np.polynomial.polynomial.polyfit(x[idx], y[idx], order)
        r = y - np.polynomial.polynomial.polyval(x, coef)
        rk = r[idx]
        s = 1.4826 * np.median(np.abs(rk - np.median(rk)))
        if not s > 0:
            break
        c = np.concatenate(([0], np.cumsum(np.abs(r) > 3.0 * s)))
        new = mask0 & ((c[hi_i] - c[lo_i]) == 0)
        if np.array_equal(new, mask) or new.sum() < NOISE_MIN_POINTS:
            break
        mask = new
    m = mask.astype(float)
    z = r * m
    cnt = float(m.sum())
    sd = math.sqrt(float(np.dot(z, z)) / cnt)
    rho = np.zeros(NOISE_LAGS)
    if sd > 0:
        for k in range(1, NOISE_LAGS + 1):
            both = float(np.dot(m[:-k], m[k:]))
            if both < 20:
                break
            rho[k - 1] = float(np.dot(z[:-k], z[k:])) / (both * sd * sd)
        # keep the lags up to the first one that is no longer clearly correlated
        small = np.nonzero(rho < max(0.05, 2.0 / math.sqrt(cnt)))[0]
        if small.size:
            rho[small[0]:] = 0.0
    return sd, rho, mask


def sum_noise_factor(m, rho):
    """sqrt of the variance of a sum of m consecutive noise points in units of the
    variance of one point: sqrt(m + 2*sum_k (m - k)*rho_k)."""
    m = int(m)
    k = np.arange(1, min(m - 1, rho.size) + 1)
    v = m + 2.0 * float(np.sum((m - k) * rho[:k.size]))
    return math.sqrt(max(v, 1.0))


def window_points(ppm, center, width):
    if center is None:
        return ppm.size
    return int(np.count_nonzero(np.abs(ppm - center) <= width / 2.0))


def measure_noise(ppm, y, center, width, mode, region=None):
    """sigma of measure(ppm, y, center, width, mode) and of integrate(...) from the noise of
    y: (sigma value, sigma integral, sigma of one point). extreme and max: one point;
    sum: m points of the window, with their correlation (zero filling, apodization)."""
    sd, rho, _ = spectrum_noise(y, ppm, center, width, region)
    f = sum_noise_factor(window_points(ppm, center, width), rho)
    step = abs(float(ppm[0] - ppm[1])) if ppm.size > 1 else 1.0
    return (sd * f if mode == "sum" else sd), sd * f * step, sd


def read_fid_tail(expdir):
    """The last quarter of the raw fid (at least 256 complex points), complex."""
    acq = jcamp_params(os.path.join(expdir, "acqus"), ACQUS_KEYS)
    dtypa = int(float(acq["DTYPA"]))
    endian = ">" if int(float(acq["BYTORDA"])) == 1 else "<"
    if dtypa == 0:
        dtype, scale, size = endian + "i4", 2.0 ** int(float(acq.get("NC", "0"))), 4
    elif dtypa == 2:
        dtype, scale, size = endian + "f8", 1.0, 8
    else:
        raise ValueError("DTYPA = %d in acqus" % dtypa)
    td = int(float(acq["TD"])) // 2 * 2
    have = os.path.getsize(os.path.join(expdir, "fid")) // size
    td = min(td, have // 2 * 2)
    n = max(256, td // 8) * 2                # real numbers in the tail
    n = min(n, td)
    f = np.fromfile(os.path.join(expdir, "fid"), dtype=dtype, count=n,
                    offset=(td - n) * size).astype(float) * scale
    return f[0::2] + 1j * f[1::2]


def fid_noise_sigma(tail):
    """Noise of one complex fid point (per component), from the tail less a straight line
    (robust standard deviation of the real and imaginary residuals)."""
    if tail.size < 32:
        raise ValueError("fid tail too short for a noise estimate")
    k = np.arange(tail.size, dtype=float)
    res = []
    for part in (tail.real, tail.imag):
        c = np.polyfit(k, part, 1)
        res.append(part - np.polyval(c, k))
    r = np.concatenate(res)
    return 1.4826 * float(np.median(np.abs(r - np.median(r))))


def fid_t0_sigma(fid, n, fit, sigma_c):
    """sigma of FID(t0) per NS*RG for noise sigma_c per point and component: the mean of N
    magnitudes, sigma_c/sqrt(N); the line at t = GRPDLY, the usual extrapolation error of a
    straight line (consecutive points taken as independent)."""
    norm = float(fid["ns"]) * fid["rg"]
    n = int(n)
    if not fit or n < 2:
        return sigma_c / math.sqrt(n) / norm
    k = np.arange(fid["g"], fid["g"] + n, dtype=float)
    d = float(np.sum((k - k.mean()) ** 2))
    return sigma_c * math.sqrt(1.0 / n + (fid["grpdly"] - k.mean()) ** 2 / d) / norm


def ratio_sigma(v, ev, ref, eref):
    """sigma of v/ref - 1 (or v/ref) from the sigmas of v and ref."""
    if ev is None or eref is None or not ref:
        return None
    return math.sqrt(ev ** 2 + (v * eref / ref) ** 2) / abs(ref)


def repeat_means(recs, xkey, ykey, nd=6):
    """Records grouped by x (rounded to nd decimals): [{"x", "y" mean, "e" standard error of
    the mean (None for one record), "n", "ns" (total scans), "recs"}], sorted by x."""
    groups = OrderedDict()
    for r in recs:
        if r.get(ykey) is None or r.get(xkey) is None:
            continue
        groups.setdefault(round(r[xkey], nd), []).append(r)
    out = []
    for x in sorted(groups):
        g = groups[x]
        ys = np.array([r[ykey] for r in g], dtype=float)
        e = float(np.std(ys, ddof=1) / math.sqrt(ys.size)) if ys.size > 1 else None
        out.append({"x": float(np.mean([r[xkey] for r in g])), "y": float(np.mean(ys)), "e": e,
                    "n": ys.size, "ns": sum((r["ns"] or r["ns_run"]) for r in g), "recs": g})
    return out


def error_text(a, ascii_only=False):
    """What the error bars show, for the info rows, the PNG and the TSV ('' without)."""
    em = a.get("error_bars", "none")
    pm = "+/-" if ascii_only else "±"
    if em == "noise":
        reg = a.get("noise_region")
        where = ("%.4g to %.4g ppm" % (min(reg), max(reg))) if reg else "outside the window, peaks excluded"
        if a["fid_mode"]:
            where = "the last quarter of each fid"
        return "error bars %s1%s from the noise floor (%s)" % (pm, " sigma" if ascii_only else "σ", where)
    if em == "repeats":
        return "mean %s standard error over repeated records" % pm
    return ""


# --------------------------------------------------------------------------
# Phase and baseline correction
# --------------------------------------------------------------------------
PH0_RANGE = 180.0
PH1_RANGE = 720.0


def wrap180(x):
    return (x + 180.0) % 360.0 - 180.0


FID_MODE = "FID(t0)"
MODES = ("extreme", "max", "sum", FID_MODE)


def canon_mode(text):
    """The mode name for text (case ignored; 'fid' also means FID(t0)), or None."""
    m = str(text).strip().lower()
    if m in ("extreme", "max", "sum"):
        return m
    if m in ("fid(t0)", "fid", "fid_t0", "fidt0", "fid0"):
        return FID_MODE
    return None


def mode_label(mode, ph):
    """The mode as shown in titles: FID(t0) with N and the method."""
    if mode != FID_MODE:
        return mode
    return "FID(t0), N %d, %s" % (int(ph["fid_n"]), "fit to t = GRPDLY" if ph["fid_fit"] else "mean")


def default_phase():
    """Viewer settings. win_set False: the intensity window and mode come from the run
    file (or --ppm/--width/--mode); True: center (None = whole spectrum), width and
    mode below are used."""
    return {"ph0": 0.0, "ph1": 0.0, "pivot": None, "base0": None, "base1": None,
            "baseline": False, "order": 3, "magnitude": False,
            "win_set": False, "center": None, "width": 20.0, "mode": "extreme",
            "show_integral": False, "fid_n": 4, "fid_fit": False, "show_fid_phase": False,
            "fit_model": "mono", "log_d1": False, "normalize": False,
            "error_bars": "none", "noise_from": None, "noise_to": None, "fit_sigma": False}


def phase_active(ph):
    return ph["ph0"] != 0.0 or ph["ph1"] != 0.0


def phase_key(ph):
    """Changes whenever any viewer setting changes."""
    return proc_key(ph) + (bool(ph.get("show_integral")), bool(ph.get("show_fid_phase")),
                           ph.get("fit_model", "mono"), bool(ph.get("log_d1")), bool(ph.get("normalize")),
                           ph.get("error_bars", "none"), ph.get("noise_from"), ph.get("noise_to"),
                           bool(ph.get("fit_sigma")))


def proc_key(ph):
    """Changes whenever a setting that changes the computed values changes."""
    def r(x):
        return None if x is None else round(float(x), 6)
    win = (r(ph["center"]), r(ph["width"]), ph["mode"]) if ph["win_set"] else None
    return (r(ph["ph0"]), r(ph["ph1"]), r(ph["pivot"]), r(ph["base0"]), r(ph["base1"]),
            bool(ph["baseline"]), int(ph["order"]), bool(ph["magnitude"]), win,
            int(ph.get("fid_n", 4)), bool(ph.get("fid_fit")))


def base_matches(spec, ph):
    """True if the record was processed with the PHC0/PHC1 the correction is for."""
    if ph["base0"] is None or ph["base1"] is None:
        return True
    return (abs(wrap180(spec["phc0"] - ph["base0"])) < 5e-4
            and abs(spec["phc1"] - ph["base1"]) < 5e-4)


def u_of_ppm(spec, ppm):
    """Position as a fraction of the spectral width, 0 at the first point (OFFSET)."""
    return (spec["offset"] - ppm) * spec["sf"] / spec["sw_p"]


def default_pivot(spec, center):
    if center is not None:
        return float(center)
    mag = np.abs(spec["re"]) if spec["im"] is None else np.hypot(spec["re"], spec["im"])
    return float(spec["ppm"][int(np.argmax(mag))])


def rephase(spec, ph0, ph1, pivot):
    """Real part of (1r + i*1i) * exp(i*phi), phi = ph0 + ph1*(u - u_pivot) in degrees."""
    u = np.arange(spec["re"].size) / float(spec["si"])
    phi = np.deg2rad(ph0 + ph1 * (u - u_of_ppm(spec, pivot)))
    return spec["re"] * np.cos(phi) - spec["im"] * np.sin(phi)


def baseline_correct(y, ppm, center, width, order):
    """Returns (corrected y, note). See the header for the method."""
    n = y.size
    order = max(0, int(order))
    x = np.linspace(-1.0, 1.0, n)
    if center is None:
        outside = np.ones(n, dtype=bool)
    else:
        outside = np.abs(ppm - center) > width / 2.0
    mask = outside.copy()
    pad = max(2, n // 400)
    step = max(1, n // 8192)
    idx_all = np.arange(n)
    lo = np.clip(idx_all - pad, 0, n)
    hi = np.clip(idx_all + pad + 1, 0, n)
    base = None
    for _ in range(20):
        idx = np.nonzero(mask)[0][::step]
        if idx.size < 10 * (order + 1):
            return y, "baseline: too few baseline points, not corrected"
        coef = np.polynomial.polynomial.polyfit(x[idx], y[idx], order)
        base = np.polynomial.polynomial.polyval(x, coef)
        r = y - base
        rk = r[idx]
        sigma = 1.4826 * np.median(np.abs(rk - np.median(rk)))
        if not sigma > 0:
            break
        c = np.concatenate(([0], np.cumsum(np.abs(r) > 3.0 * sigma)))
        new = outside & ((c[hi] - c[lo]) == 0)
        if np.array_equal(new, mask):
            break
        mask = new
    return y - base, ""


def corrected(spec, ph, center, width, force=False):
    """The spectrum with the settings of ph: magnitude |1r + i*1i| if ph['magnitude'],
    otherwise the real part with the phase correction; then the baseline correction.
    force=True applies the phase whatever PHC0/PHC1 the record was processed with.
    Returns (y, notes, ok); ok is False if the magnitude or the phase correction asked
    for could not be applied to this record."""
    y, notes, applied = spec["re"], [], True
    if ph.get("magnitude"):
        if spec["im"] is None:
            notes.append("%s: magnitude not possible, shown as processed" % spec["im_note"])
            applied = False
        else:
            y = np.hypot(spec["re"], spec["im"])
    elif phase_active(ph):
        applied = False
        if spec["im"] is None:
            notes.append("%s: phase correction not applied" % spec["im_note"])
        elif not force and not base_matches(spec, ph):
            notes.append("processed with PHC0 %.3f, PHC1 %.3f: shown as processed"
                         % (spec["phc0"], spec["phc1"]))
        else:
            pivot = ph["pivot"] if ph["pivot"] is not None else default_pivot(spec, center)
            y = rephase(spec, ph["ph0"], ph["ph1"], pivot)
            applied = True
    if ph["baseline"]:
        y, note = baseline_correct(y, spec["ppm"], center, width, ph["order"])
        if note:
            notes.append(note)
    return y, notes, applied


def describe_phase(ph, with_base=True, window=True):
    if ph.get("magnitude"):
        s = "magnitude (no phase)"
    elif phase_active(ph):
        s = "PH0 %+.1f, PH1 %+.1f deg, pivot %.2f ppm" % (
            ph["ph0"], ph["ph1"], ph["pivot"] if ph["pivot"] is not None else float("nan"))
        if with_base and ph["base0"] is not None:
            s += " (for PHC0 %.2f, PHC1 %.2f)" % (ph["base0"], ph["base1"])
    else:
        s = "none (as processed by TopSpin)"
    if ph["baseline"]:
        s += "; baseline polynomial order %d" % ph["order"]
    if window and ph["win_set"]:
        s += "; %s, %s" % (window_desc(ph["center"], ph["width"]), ph["mode"])
    return s


def window_desc(center, width):
    if center is None:
        return "whole spectrum"
    return "window %.1f +/- %.1f ppm" % (center, width / 2.0)


# Phase file ---------------------------------------------------------------
RUN_FILE_NAME = "run.txt"     # run file inside a run folder <dataset>/fs_runs/<run id>/


def is_run_folder_layout(runpath):
    return os.path.basename(runpath) == RUN_FILE_NAME


def output_paths(runpath):
    """(png, tsv, phase file): plot.png, values.tsv and phase.txt next to run.txt,
    or <run file without .txt>_plot.png etc. for an older run file."""
    if is_run_folder_layout(runpath):
        d = os.path.dirname(runpath)
        return (os.path.join(d, "plot.png"), os.path.join(d, "values.tsv"),
                os.path.join(d, "phase.txt"))
    base = runpath[:-4] if runpath.endswith(".txt") else runpath
    return base + "_plot.png", base + "_values.tsv", base + "_phase.txt"


def phase_file_path(runpath):
    return output_paths(runpath)[2]


def eps_path(runpath, buildup=False):
    """profile.eps (buildup.eps) next to run.txt, or <run file without .txt>_profile.eps."""
    name = "buildup.eps" if buildup else "profile.eps"
    if is_run_folder_layout(runpath):
        return os.path.join(os.path.dirname(runpath), name)
    return (runpath[:-4] if runpath.endswith(".txt") else runpath) + "_" + name


def csv_path(runpath):
    """records.csv next to run.txt, or <run file without .txt>_records.csv."""
    if is_run_folder_layout(runpath):
        return os.path.join(os.path.dirname(runpath), "records.csv")
    return (runpath[:-4] if runpath.endswith(".txt") else runpath) + "_records.csv"


def run_label(runpath):
    """The run id (name of the run folder), or the file name of an older run file."""
    if is_run_folder_layout(runpath):
        return os.path.basename(os.path.dirname(runpath))
    return os.path.basename(runpath)


def dataset_dir(runpath, meta):
    """The dataset holding the run's expnos. For run.txt in <dataset>/fs_runs/<run id>/
    this is the folder two levels up, so a dataset that was moved or copied (with its
    fs_runs folder) is still found; otherwise dataset_dir from the run file, or the
    run file's own folder."""
    if is_run_folder_layout(runpath):
        up = os.path.dirname(os.path.dirname(os.path.dirname(runpath)))
        if os.path.isdir(up):
            return up
    d = meta.get("dataset_dir", "")
    if os.path.isdir(d):
        return d
    return os.path.dirname(runpath)


def read_phase_file(path):
    vals = {}
    with open(path) as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            m = re.match(r"(\w+)\s*=\s*(\S+)$", line)
            if m:
                vals[m.group(1)] = m.group(2)

    def num(key, default):
        v = vals.get(key)
        if v is None or v.lower() == "none":
            return default
        return float(v)
    ph = default_phase()
    ph["ph0"] = num("ph0", 0.0)
    ph["ph1"] = num("ph1", 0.0)
    ph["pivot"] = num("pivot_ppm", None)
    ph["base0"] = num("base_phc0", None)
    ph["base1"] = num("base_phc1", None)
    ph["baseline"] = bool(int(num("baseline", 0)))
    ph["order"] = int(num("baseline_order", 3))
    ph["magnitude"] = bool(int(num("magnitude", 0)))
    ph["show_integral"] = bool(int(num("show_integral", 0)))
    ph["fid_n"] = max(1, min(FID_HEAD, int(num("fid_points", 4))))
    ph["fid_fit"] = bool(int(num("fid_fit", 0)))
    ph["show_fid_phase"] = bool(int(num("show_fid_phase", 0)))
    if vals.get("fit_model") in FIT_MODELS:
        ph["fit_model"] = vals["fit_model"]
    ph["log_d1"] = bool(int(num("log_d1", 0)))
    ph["normalize"] = bool(int(num("normalize", 0)))
    if vals.get("error_bars") in ERROR_MODES:
        ph["error_bars"] = vals["error_bars"]
    ph["noise_from"] = num("noise_from", None)
    ph["noise_to"] = num("noise_to", None)
    ph["fit_sigma"] = bool(int(num("fit_sigma", 0)))
    if "window_width" in vals:
        ph["win_set"] = True
        ph["center"] = num("window_center", None)
        ph["width"] = num("window_width", 20.0)
        ph["mode"] = canon_mode(vals.get("mode", "extreme")) or "extreme"
    return ph


def write_phase_file(path, ph, runpath):
    def v(x):
        return "none" if x is None else repr(float(x))
    window = ""
    if ph["win_set"]:
        window = ("window_center = %s\nwindow_width = %s\nmode = %s\n"
                  % (v(ph["center"]), v(ph["width"]), ph["mode"]))
    text = (
        "# viewer settings for run %s, written by fs_plot.py at %s\n"
        "# fs_plot.py multiplies 1r + i*1i of every record processed with PHC0 = base_phc0\n"
        "# and PHC1 = base_phc1 by exp(i*phi), phi = ph0 + ph1*(k/SI - u_pivot) (deg),\n"
        "# k = 0 at OFFSET, u_pivot = (OFFSET - pivot_ppm)*SF/SW_p; with magnitude = 1 it\n"
        "# uses |1r + i*1i| instead; with baseline = 1 it subtracts a polynomial of order\n"
        "# baseline_order. window_center (none = whole spectrum), window_width and mode, if\n"
        "# present, replace the intensity window of the run file. show_integral = 1 also\n"
        "# plots the integral of the window. fid_points (N) and fid_fit (1 = linear fit\n"
        "# to t = GRPDLY) set mode FID(t0); show_fid_phase = 1 shows the FID phase panel.\n"
        "# Build-up runs: fit_model (mono, offset, stretched, biexp), log_d1 = 1 for a\n"
        "# logarithmic D1 axis, normalize = 1 to divide each series by its fitted S_inf.\n"
        "# error_bars: none, noise (noise floor; noise_from/noise_to in ppm, none =\n"
        "# outside the window) or repeats; fit_sigma = 1 weights build-up fits by 1/sigma^2.\n"
        "# fs_rephase.py (TopSpin)\n"
        "# applies the phase to the TopSpin data; everything else stays in the viewer.\n"
        "ph0 = %s\nph1 = %s\npivot_ppm = %s\nbase_phc0 = %s\nbase_phc1 = %s\n"
        "baseline = %d\nbaseline_order = %d\nmagnitude = %d\nshow_integral = %d\n"
        "fid_points = %d\nfid_fit = %d\nshow_fid_phase = %d\n"
        "fit_model = %s\nlog_d1 = %d\nnormalize = %d\n"
        "error_bars = %s\nnoise_from = %s\nnoise_to = %s\nfit_sigma = %d\n%s"
        % (run_label(runpath), time.strftime("%Y-%m-%d %H:%M:%S"),
           v(ph["ph0"]), v(ph["ph1"]), v(ph["pivot"]), v(ph["base0"]), v(ph["base1"]),
           1 if ph["baseline"] else 0, int(ph["order"]), 1 if ph["magnitude"] else 0,
           1 if ph.get("show_integral") else 0, int(ph.get("fid_n", 4)),
           1 if ph.get("fid_fit") else 0, 1 if ph.get("show_fid_phase") else 0,
           ph.get("fit_model", "mono"), 1 if ph.get("log_d1") else 0, 1 if ph.get("normalize") else 0,
           ph.get("error_bars", "none"), v(ph.get("noise_from")), v(ph.get("noise_to")),
           1 if ph.get("fit_sigma") else 0, window))
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Build-up fits
# --------------------------------------------------------------------------
FIT_MODELS = OrderedDict([
    ("mono", "mono-exponential"),
    ("offset", "mono-exponential, free start"),
    ("stretched", "stretched exponential"),
    ("biexp", "bi-exponential"),
])
FIT_SHORT = {"mono": "mono-exp.", "offset": "mono + S₀", "stretched": "stretched",
             "biexp": "bi-exp."}           # in the window's list
FIT_FORMULAS = {                          # ASCII, for the TSV, the CSV and the PNG
    "mono": "S_inf*(1 - exp(-D1/T_B))",
    "offset": "S_inf - (S_inf - S_0)*exp(-D1/T_B)",
    "stretched": "S_inf*(1 - exp(-(D1/T_B)^beta))",
    "biexp": "S_1*(1 - exp(-D1/T_1)) + S_2*(1 - exp(-D1/T_2)), S_inf = S_1 + S_2",
}
FIT_FORMULAS_UI = {                       # for the window
    "mono": "S∞·(1 − exp(−D1/T_B))",
    "offset": "S∞ − (S∞ − S₀)·exp(−D1/T_B)",
    "stretched": "S∞·(1 − exp(−(D1/T_B)^β))",
    "biexp": "S₁·(1 − exp(−D1/T₁)) + S₂·(1 − exp(−D1/T₂))",
}
FIT_NPAR = {"mono": 2, "offset": 3, "stretched": 3, "biexp": 4}
# x = t/T_B where (1 - exp(-x))/sqrt(x) is largest: exp(-x)*(2x + 1) = 1
SENS_X = 1.2564312086261697


def fit_model_value(model, p, t):
    """The fitted curve at the build-up times t (array)."""
    t = np.asarray(t, dtype=float)
    if model == "mono":
        return p[0] * -np.expm1(-t / p[1])
    if model == "offset":
        return p[0] - (p[0] - p[1]) * np.exp(-t / p[2])
    if model == "stretched":
        return p[0] * -np.expm1(-(t / p[1]) ** p[2])
    return p[0] * -np.expm1(-t / p[1]) + p[2] * -np.expm1(-t / p[3])


def _fit_basis(model, q, t):
    """Columns of the linear amplitudes for the nonlinear parameters q (times, beta)."""
    if model == "mono":
        return [-np.expm1(-t / q[0])]
    if model == "offset":
        e = np.exp(-t / q[0])
        return [1.0 - e, e]
    if model == "stretched":
        return [-np.expm1(-(t / q[0]) ** q[1])]
    return [-np.expm1(-t / q[0]), -np.expm1(-t / q[1])]


def _amplitudes(cols, y, sw):
    """Weighted least squares amplitudes for the columns, and the weighted sum of squares."""
    A = np.column_stack(cols) * sw[:, None]
    coef = np.linalg.lstsq(A, y * sw, rcond=None)[0]
    r = y * sw - A.dot(coef)
    return coef, float(r.dot(r))


def _nelder_mead(f, x0, step, iters=800):
    """Minimises f from x0 (simplex with edges step); returns (x, f(x))."""
    n = len(x0)
    pts = [np.array(x0, dtype=float)]
    for i in range(n):
        x = np.array(x0, dtype=float)
        x[i] += step[i]
        pts.append(x)
    vals = [f(x) for x in pts]
    for _ in range(iters):
        order = np.argsort(vals)
        pts = [pts[i] for i in order]
        vals = [vals[i] for i in order]
        if abs(vals[-1] - vals[0]) <= 1e-12 * (abs(vals[0]) + 1e-300) and \
                max(np.max(np.abs(p - pts[0])) for p in pts[1:]) < 1e-9:
            break
        c = np.mean(pts[:-1], axis=0)
        xr = c + (c - pts[-1])
        fr = f(xr)
        if fr < vals[0]:
            xe = c + 2.0 * (c - pts[-1])
            fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = c + 0.5 * (pts[-1] - c) if fr >= vals[-1] else c + 0.5 * (xr - c)
            fc = f(xc)
            if fc < min(fr, vals[-1]):
                pts[-1], vals[-1] = xc, fc
            else:
                pts = [pts[0]] + [pts[0] + 0.5 * (p - pts[0]) for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
    i = int(np.argmin(vals))
    return pts[i], vals[i]


def fit_buildup(t, y, w, model, absolute=False):
    """Weighted least squares fit of the build-up y(t) (weights w: NS, as the noise of an
    intensity per scan goes as 1/sqrt(NS)). The amplitudes are linear; the times (and beta)
    are searched on a grid over 1/30 of the shortest to 30 times the longest D1, then
    refined. absolute=True: w = 1/sigma^2 of each point, and the standard errors come from
    these sigmas (not from the scatter); chi2_red then compares the scatter with them.
    Returns a dict (see the end); raises ValueError if there are too few points."""
    t, y, w = (np.asarray(v, dtype=float) for v in (t, y, w))
    k = FIT_NPAR[model]
    if t.size < k:
        raise ValueError("%d point%s; the %s fit needs at least %d"
                         % (t.size, "" if t.size == 1 else "s", FIT_MODELS[model], k))
    sw = np.sqrt(w) if absolute else np.sqrt(w / np.mean(w))
    tmin, tmax = float(t.min()), float(t.max())
    lo, hi = math.log(tmin / 30.0), math.log(tmax * 30.0)
    big = 1e300

    def cost(u):                          # u: log of the times; for stretched also log(beta)
        if model == "stretched":
            if not (lo - 1 < u[0] < hi + 1 and math.log(0.1) <= u[1] <= math.log(3.0)):
                return big
            q = [math.exp(u[0]), math.exp(u[1])]
        else:
            if any(not (lo - 1 < x < hi + 1) for x in u):
                return big
            q = sorted(math.exp(x) for x in u)
        return _amplitudes(_fit_basis(model, q, t), y, sw)[1]

    grid = np.linspace(lo, hi, 121)
    if model == "biexp":
        g = grid[::4]
        u0 = min(([a, b] for i, a in enumerate(g) for b in g[i + 1:]), key=cost)
        starts = [u0]
    elif model == "stretched":
        u0 = min(grid, key=lambda x: cost([x, 0.0]))
        starts = [[u0, 0.0], [u0, math.log(0.5)], [u0, math.log(1.5)]]
    else:
        starts = [[min(grid, key=lambda x: cost([x]))]]
    best = None
    for s in starts:
        u, c = _nelder_mead(cost, s, [0.3] * len(s))
        if best is None or c < best[1]:
            best = (u, c)
    u, chi2 = best
    if model == "stretched":
        q = [math.exp(u[0]), math.exp(u[1])]
    else:
        q = sorted(math.exp(x) for x in u)
    amp = _amplitudes(_fit_basis(model, q, t), y, sw)[0]
    if model == "mono":
        p = np.array([amp[0], q[0]])
    elif model == "offset":
        p = np.array([amp[0], amp[1], q[0]])
    elif model == "stretched":
        p = np.array([amp[0], q[0], q[1]])
    else:
        p = np.array([amp[0], q[0], amp[1], q[1]])

    # Standard errors from the Jacobian of the curve, scaled by the scatter about the fit
    n = t.size
    cov = None
    if n > k:
        J = np.empty((n, k))
        for j in range(k):
            h = 1e-6 * max(abs(p[j]), 1e-12)
            pp, pm = p.copy(), p.copy()
            pp[j] += h
            pm[j] -= h
            J[:, j] = (fit_model_value(model, pp, t) - fit_model_value(model, pm, t)) / (2 * h)
        Jw = J * sw[:, None]
        try:
            cov = np.linalg.inv(Jw.T.dot(Jw)) * (1.0 if absolute else chi2 / (n - k))
        except np.linalg.LinAlgError:
            cov = None
    elif absolute:
        try:
            Jw = np.empty((n, k))
            for j in range(k):
                h = 1e-6 * max(abs(p[j]), 1e-12)
                pp, pm = p.copy(), p.copy()
                pp[j] += h
                pm[j] -= h
                Jw[:, j] = sw * (fit_model_value(model, pp, t) - fit_model_value(model, pm, t)) / (2 * h)
            cov = np.linalg.inv(Jw.T.dot(Jw))
        except np.linalg.LinAlgError:
            cov = None

    def err(grad):
        if cov is None:
            return None
        v = float(np.dot(grad, cov.dot(grad)))
        return math.sqrt(v) if v >= 0 and np.isfinite(v) else None

    def unit(j):
        e = np.zeros(k)
        e[j] = 1.0
        return e
    par = OrderedDict()
    notes = []
    if model == "biexp":
        s_inf = p[0] + p[2]
        par["S_inf"] = (s_inf, err(np.array([1.0, 0.0, 1.0, 0.0])))
        par["T_1"] = (p[1], err(unit(1)))
        par["T_2"] = (p[3], err(unit(3)))
        if s_inf != 0:
            g1 = np.array([p[2] / s_inf ** 2, 0.0, -p[0] / s_inf ** 2, 0.0])
            par["f_1"] = (p[0] / s_inf, err(g1))
        if p[0] * p[2] < 0:
            notes.append("components of opposite sign")
        times = [p[1], p[3]]
    else:
        par["S_inf"] = (p[0], err(unit(0)))
        if model == "offset":
            par["S_0"] = (p[1], err(unit(1)))
        it = 2 if model == "offset" else 1
        par["T_B"] = (p[it], err(unit(it)))
        if model == "stretched":
            par["beta"] = (p[2], err(unit(2)))
            if p[2] <= 0.101 or p[2] >= 2.99:
                notes.append("beta at the limit of the search (0.1 to 3)")
        times = [p[it]]
    # A time at the edge of the search is not determined by the data (e.g. a series that
    # still rises linearly, or one already at its plateau)
    why = None
    if max(times) >= tmax * 29.0:
        why = "T_B beyond 30 times the longest D1 (the curve has not bent yet)"
    elif min(times) <= tmin / 29.0:
        why = "T_B below 1/30 of the shortest D1 (no rise sampled)"
    t_long, t_short = ("T_2", "T_1") if model == "biexp" else ("T_B", "T_B")
    if why is None and tmax < 3.0 * max(times):
        notes.append("longest D1 = %.2g %s: S_inf extrapolated" % (tmax / max(times), t_long))
    if why is None and tmin > 0.5 * min(times):
        notes.append("shortest D1 = %.2g %s: rise hardly sampled" % (tmin / min(times), t_short))

    # Largest signal per square root of time, from the build-up part of the curve
    if model == "mono":
        t_opt = SENS_X * p[1]
        s_opt = abs(p[0]) * -math.expm1(-SENS_X) / math.sqrt(t_opt)
    else:
        tt = np.exp(np.linspace(math.log(min(times) / 1000.0), math.log(max(times) * 100.0), 4001))
        g = np.abs(fit_model_value(model, p, tt) - fit_model_value(model, p, [0.0])[0]) / np.sqrt(tt)
        i = int(np.argmax(g))
        lo_t, hi_t = tt[max(0, i - 1)], tt[min(tt.size - 1, i + 1)]
        tt = np.linspace(lo_t, hi_t, 2001)
        g = np.abs(fit_model_value(model, p, tt) - fit_model_value(model, p, [0.0])[0]) / np.sqrt(tt)
        i = int(np.argmax(g))
        t_opt, s_opt = float(tt[i]), float(g[i])
    return {"model": model, "p": p, "params": par, "n": n, "chi2_red": chi2 / (n - k) if n > k else None,
            "s_inf": par["S_inf"][0], "times": times, "t_opt": t_opt, "s_opt": s_opt,
            "notes": notes, "tmin": tmin, "tmax": tmax, "determined": why is None, "why": why,
            "absolute": bool(absolute)}


def fmt_pm(v, e):
    """v ± e with e to two significant digits (v alone without e)."""
    if e is None or not np.isfinite(e) or e <= 0:
        return "%.3g" % v
    if v != 0 and e < 1e-5 * abs(v):                 # e.g. data without noise
        return "%.5g ± %.1g" % (v, e)
    if abs(v) >= 1e5 or abs(v) < 1e-3 or e >= 1e5:
        return "%.3g ± %.2g" % (v, e)
    d = max(0, 1 - int(math.floor(math.log10(e))))
    return "%.*f ± %.*f" % (d, v, d, e)


def fmt_time(v, e=None):
    """A time in s, ± e, with minutes added from 2 min."""
    s = fmt_pm(v, e) + " s"
    if v >= 120:
        s += " (%.3g min)" % (v / 60.0)
    return s


def fit_summary(f, ascii_only=False):
    """One line: the fitted parameters and the largest S/sqrt(t)."""
    pm = (lambda v, e: fmt_pm(v, e).replace("±", "+/-")) if ascii_only else fmt_pm
    tm = (lambda v, e=None: fmt_time(v, e).replace("±", "+/-")) if ascii_only else fmt_time
    names = {"S_inf": "S_inf" if ascii_only else "S∞", "S_0": "S_0" if ascii_only else "S₀",
             "T_B": "T_B", "T_1": "T_1" if ascii_only else "T₁", "T_2": "T_2" if ascii_only else "T₂",
             "beta": "beta" if ascii_only else "β", "f_1": "f_1" if ascii_only else "f₁"}
    parts = []
    for k, (v, e) in f["params"].items():
        parts.append("%s %s" % (names[k], tm(v, e) if k.startswith("T_") else pm(v, e)))
    if f["model"] == "mono":
        parts.append("max S/%s %.4g at D1 = 1.26 T_B = %s"
                     % ("sqrt(t)" if ascii_only else "√t", f["s_opt"], tm(f["t_opt"])))
    else:
        parts.append("max S/%s %.4g at D1 = %s" % ("sqrt(t)" if ascii_only else "√t", f["s_opt"], tm(f["t_opt"])))
    if f.get("absolute") and f["chi2_red"] is not None:
        parts.append("%s %.3g" % ("chi2/dof" if ascii_only else "χ²/dof", f["chi2_red"]))
    return ("; " if ascii_only else " · ").join(parts)


def fit_weight_text(a, ascii_only=False):
    if a.get("fit_sigma"):
        return "weighted by 1/sigma^2" if ascii_only else "weighted by 1/σ²"
    return "weighted by NS"


def ui_text(text):
    """Notes and parameter names for the window (S_inf -> S∞ etc.)."""
    for a, b in (("S_inf", "S∞"), ("T_1", "T₁"), ("T_2", "T₂"), ("beta", "β"), ("sqrt(t)", "√t"),
                 ("chi2/dof", "χ²/dof")):
        text = text.replace(a, b)
    return text


def fit_summary_ui(f):
    """Short form for the window: the build-up time(s) first, then S∞, the other parameters
    and the largest S/√t; or why the fit is not determined."""
    if not f["determined"]:
        return ui_text("not determined: " + f["why"])
    P = f["params"]
    first = [k for k in ("T_B", "T_1", "T_2") if k in P]
    parts = ["%s %s" % (ui_text(k), fmt_time(*P[k])) for k in first]
    parts += ["%s %s" % (ui_text(k).replace("S_0", "S₀").replace("f_1", "f₁"), fmt_pm(*P[k]))
              for k in P if k not in first]
    at = fmt_time(f["t_opt"]) + (" (1.26 T_B)" if f["model"] == "mono" else "")
    parts.append("max S/√t %.4g at %s" % (f["s_opt"], at))
    if f.get("absolute") and f["chi2_red"] is not None:
        parts.append("χ²/dof %.3g" % f["chi2_red"])
    return " · ".join(parts)



def buildup_series(results):
    """{(kind, set): records with a value and a D1, sorted by D1}, ON before OFF."""
    out = OrderedDict()
    for kind in ("ON", "OFF"):
        for s in sorted(set(r["set"] for r in results)):
            pts = sorted([r for r in results if r["kind"] == kind and r["set"] == s
                          and r["y"] is not None and r["d1"] is not None], key=lambda r: r["d1"])
            if pts:
                out[(kind, s)] = pts
    return out


def buildup_view(results, errm):
    """The points of each build-up series: {(kind, set): {"x", "y", "e" (sigma or None per
    point), "ns" (scans per point), "n" (records per point), "recs" (the records of each
    point)}}. With errm 'repeats', one series per kind (set 0): the mean over the records
    with the same D1 (in any set), with its standard error."""
    out = OrderedDict()
    if errm == "repeats":
        for kind in ("ON", "OFF"):
            g = repeat_means([r for r in results if r["kind"] == kind and r["y"] is not None
                              and r["d1"] is not None], "d1", "y")
            if g:
                out[(kind, 0)] = {"x": [q["x"] for q in g], "y": [q["y"] for q in g],
                                  "e": [q["e"] for q in g], "ns": [q["ns"] for q in g],
                                  "n": [q["n"] for q in g], "recs": [q["recs"] for q in g]}
        return out
    for key, pts in buildup_series(results).items():
        out[key] = {"x": [r["d1"] for r in pts], "y": [r["y"] for r in pts],
                    "e": [r.get("ey") for r in pts], "ns": [r["ns"] if r["ns"] else r["ns_run"] for r in pts],
                    "n": [1] * len(pts), "recs": [[r] for r in pts]}
    return out


def buildup_fits(view, model, fit_sigma=False):
    """{(kind, set): fit_buildup result, or {"error": text}} for each series of the view;
    weighted by 1/sigma^2 if fit_sigma and every point has an error bar, else by NS."""
    fits = OrderedDict()
    for key, v in view.items():
        e = v["e"]
        use_sigma = fit_sigma and all(x is not None and x > 0 for x in e)
        rough = key[1] == 0 and min(v["n"]) < 3       # standard errors of 2 records: too rough
        try:
            if use_sigma and not rough:
                f = fit_buildup(v["x"], v["y"], [1.0 / x ** 2 for x in e], model, absolute=True)
                if f["chi2_red"] is not None and f["chi2_red"] > 3:
                    f["notes"].append("scatter about %.2g times the error bars (chi2/dof %.3g)%s"
                                      % (math.sqrt(f["chi2_red"]), f["chi2_red"],
                                         "" if key[1] == 0 else "; for a weak signal the extreme or max "
                                         "of the window follows the noise, 'sum' does not"))
            else:
                f = fit_buildup(v["x"], v["y"], v["ns"], model)
                if fit_sigma:
                    f["notes"].append("weighted by NS: %s" % (
                        "fewer than 3 records at some D1, too few for weights from their spread" if rough
                        else "not every point has an error bar"))
            fits[key] = f
        except (ValueError, np.linalg.LinAlgError, FloatingPointError, OverflowError) as ex:
            fits[key] = {"error": str(ex)}
    return fits


def planned_records(runpath):
    """[(expno, expected s)] of a build-up from settings.txt in the run folder, or None."""
    if not is_run_folder_layout(runpath):
        return None
    out = []
    try:
        with open(os.path.join(os.path.dirname(runpath), "settings.txt")) as fh:
            for line in fh:
                m = re.match(r"#\s*record:\s*(\d+)\s+\d+\s+\w+\s+\S+\s+\d+\s+(\d+)", line)
                if m:
                    out.append((int(m.group(1)), int(m.group(2))))
    except Exception:
        return None
    return out or None


# --------------------------------------------------------------------------
# Analysis of the whole run
# --------------------------------------------------------------------------
class Analyzer:
    """Reads the run, the spectra and the phase file; keeps the caches."""
    RAW_CACHE = 6

    def __init__(self, runpath, args):
        self.runpath = runpath
        self.args = args
        self.phase_path = phase_file_path(runpath)
        self.phase = default_phase()
        self.phase_mtime = None
        self.values = {}
        self.raw = OrderedDict()
        self.fids = {}               # expdir -> (fid_file_key, read_fid result)
        self.fid_warned = set()
        self.csv_cache, self.csv_tag = {}, None
        self.sigmas = {}             # noise-floor sigmas per record and settings
        self.fid_sigmas = {}         # expdir -> (fid_file_key, noise of one fid point)
        # --ppm/--width/--mode take precedence over a window in the settings file
        # until a window is applied from the spectrum pane
        self.cli_window = (args.ppm is not None or args.width is not None
                           or args.mode is not None)

    def load_phase(self):
        """Reads the phase file if it has changed. Returns True if the settings changed."""
        try:
            m = os.path.getmtime(self.phase_path)
        except OSError:
            m = None
        if m == self.phase_mtime:
            return False
        if m is None:
            new = default_phase()
        else:
            try:
                new = read_phase_file(self.phase_path)
            except Exception as ex:      # e.g. read while being written: retry next time
                print("[%s] could not read %s: %s" % (time.strftime("%H:%M:%S"), self.phase_path, ex))
                sys.stdout.flush()
                return False
        self.phase_mtime = m
        if phase_key(new) != phase_key(self.phase):
            proc_changed = proc_key(new) != proc_key(self.phase)
            self.phase = new
            if proc_changed:
                self.values.clear()
                return "proc"
            return "display"
        return False

    def set_display(self, **flags):
        """Sets display-only settings (show_integral, show_fid_phase; for build-ups fit_model,
        log_d1, normalize) and saves them. Returns an error text or ''."""
        bools = ("show_integral", "show_fid_phase", "log_d1", "normalize", "fit_sigma")
        self.phase = dict(self.phase, **dict((k, bool(v) if k in bools else v) for k, v in flags.items()))
        try:
            write_phase_file(self.phase_path, self.phase, self.runpath)
            self.phase_mtime = os.path.getmtime(self.phase_path)
            return ""
        except Exception as ex:
            return "could not write %s (%s); the setting applies to this window only" % (
                self.phase_path, ex)

    def set_phase(self, ph):
        """Applies ph to all records and writes the phase file. Returns an error text or ''."""
        self.phase = dict(ph)
        self.values.clear()
        if ph["win_set"]:
            self.cli_window = False
        try:
            write_phase_file(self.phase_path, ph, self.runpath)
            self.phase_mtime = os.path.getmtime(self.phase_path)
            return ""
        except Exception as ex:
            return "could not write %s (%s); the settings apply to this window only" % (
                self.phase_path, ex)

    def spectrum(self, ds_dir, expno, files):
        key = (ds_dir, expno, files)
        if key in self.raw:
            self.raw.move_to_end(key)
            return self.raw[key]
        spec = read_spectrum(os.path.join(ds_dir, str(expno)))
        self.raw[key] = spec
        while len(self.raw) > self.RAW_CACHE:
            self.raw.popitem(last=False)
        return spec

    def fid(self, ds_dir, expno):
        """read_fid of the expno, read again only when the fid or acqus changes."""
        expdir = os.path.join(ds_dir, str(expno))
        key = fid_file_key(expdir)
        hit = self.fids.get(expdir)
        if hit is not None and hit[0] == key:
            return hit[1]
        fid = read_fid(expdir)
        self.fids[expdir] = (key, fid)
        return fid

    def _fid_info(self, ds_dir, expno, n):
        info = {"mean": None, "fit": None, "line": None, "phase": None, "phase_rel": None,
                "grpdly": None, "g": None, "ns": None, "rg": None, "date": None, "note": "",
                "read": False}
        try:
            fid = self.fid(ds_dir, expno)
        except Exception as ex:
            info["note"] = "fid: %s" % ex
            return info
        info.update(grpdly=fid["grpdly"], g=fid["g"], ns=fid["ns"], rg=fid["rg"],
                    date=fid["date"], read=True)
        try:
            info.update(fid_t0(fid, n))
        except Exception as ex:
            info["note"] = str(ex)
            if fid["g"] is None and (ds_dir, expno) not in self.fid_warned:
                self.fid_warned.add((ds_dir, expno))
                print("[%s] WARNING expno %d: %s" % (time.strftime("%H:%M:%S"), expno, ex))
                sys.stdout.flush()
        return info

    def _add_fid(self, res, ds_dir, ph, fid_mode):
        """Adds res['fid']; in FID(t0) mode the value is FID(t0) instead of the spectrum's."""
        info = self._fid_info(ds_dir, res["expno"], int(ph["fid_n"]))
        res["fid"] = info
        if res["ns"] is None:
            res["ns"] = info["ns"]
        if fid_mode:
            v = info["fit"] if ph["fid_fit"] else info["mean"]
            note = info["note"]
            if v is None and not note:
                note = "the linear fit needs N >= 2"
            spec_note = ("spectrum: " + res["note"]) if res["note"] else ""
            res["value"], res["at"] = v, None
            res["note"] = "; ".join([x for x in (note, spec_note) if x])

    def _value(self, ds_dir, expno, files, ph, center, width, mode):
        out = {"value": None, "at": None, "ns": None, "note": "", "readable": False,
               "phase_skipped": False, "integral": None}
        try:
            spec = self.spectrum(ds_dir, expno, files)
        except Exception as ex:
            out["note"] = str(ex)
            return out
        out["readable"] = True
        out["ns"] = spec["ns"]
        try:
            y, notes, ok = corrected(spec, ph, center, width)
            if mode == FID_MODE:         # the value comes from the fid; the spectrum gives the integral
                val, at = None, None
            else:
                val, at = measure(spec["ppm"], y, center, width, mode)
            out.update(value=None if val is None else val / spec["ns"], at=at, note="; ".join(notes),
                       phase_skipped=not ok,
                       integral=integrate(spec["ppm"], y, center, width) / spec["ns"])
        except Exception as ex:          # one bad record must not stop the viewer
            out["note"] = str(ex)
        return out

    def _noise(self, ds_dir, r, ph, center, width, mode, region):
        """{"err": sigma of the value, "err_int": of the integral, "noise": of one point (all
        per scan, FID(t0) per NS*RG), "note"} from the noise floor of the record."""
        key = (r["expno"], r["files"], proc_key(ph), center, width, mode, region,
               int(ph["fid_n"]), bool(ph["fid_fit"]))
        hit = self.sigmas.get(key)
        if hit is not None:
            return hit
        out = {"err": None, "err_int": None, "noise": None, "note": ""}
        try:
            spec = self.spectrum(ds_dir, r["expno"], r["files"])
            y, _, _ = corrected(spec, ph, center, width)
            ns = float(spec["ns"])
            ev, ei, sd = measure_noise(spec["ppm"], y, center, width,
                                       "sum" if mode == FID_MODE else mode, region)
            out.update(err=None if mode == FID_MODE else ev / ns, err_int=ei / ns, noise=sd / ns)
        except Exception as ex:
            out["note"] = "noise: %s" % ex
        if mode == FID_MODE:
            try:
                expdir = os.path.join(ds_dir, str(r["expno"]))
                fkey = fid_file_key(expdir)
                hit = self.fid_sigmas.get(expdir)
                if hit is None or hit[0] != fkey:
                    hit = (fkey, fid_noise_sigma(read_fid_tail(expdir)))
                    self.fid_sigmas[expdir] = hit
                fid = self.fid(ds_dir, r["expno"])
                if fid["g"] is not None:
                    out["err"] = fid_t0_sigma(fid, ph["fid_n"], ph["fid_fit"], hit[1])
            except Exception as ex:
                out["note"] = "; ".join([x for x in (out["note"], "fid noise: %s" % ex) if x])
        if len(self.sigmas) > 20000:
            self.sigmas.clear()
        self.sigmas[key] = out
        return out

    def run(self, force_fid=False):
        """force_fid: also read the fids when neither the mode nor the phase panel needs them
        (CSV export)."""
        meta, rows, ended = read_run(self.runpath)
        ds_dir = dataset_dir(self.runpath, meta)
        args = self.args
        ph = self.phase
        center = parse_center(meta.get("peak_ppm", "0"))
        width = float(meta.get("window_ppm", "20"))
        mode = meta.get("mode", "extreme")
        if self.cli_window:
            if args.ppm is not None:
                center = args.ppm
            if args.width is not None:
                width = args.width
            if args.mode is not None:
                mode = args.mode
        elif ph["win_set"]:
            center, width, mode = ph["center"], ph["width"], ph["mode"]
        skey = proc_key(ph)
        buildup = meta.get("type") == "buildup"
        errm = ph.get("error_bars", "none")
        region = None
        if ph.get("noise_from") is not None and ph.get("noise_to") is not None \
                and ph["noise_from"] != ph["noise_to"]:
            region = (float(ph["noise_from"]), float(ph["noise_to"]))
        fid_mode = mode == FID_MODE
        need_fid = force_fid or fid_mode or bool(ph.get("show_fid_phase"))

        results = []
        for r in rows:
            res = dict(r)
            res.update(value=None, at=None, ns=None, note="", readable=False,
                       phase_skipped=False, files=None, integral=None, fid=None)
            try:
                files = file_key(os.path.join(ds_dir, str(r["expno"])))
            except Exception as ex:
                files = None
                res["note"] = str(ex)
            if files is not None:
                key = (r["expno"], files, skey, center, width, mode)
                v = self.values.get(key)
                if v is None:
                    v = self._value(ds_dir, r["expno"], files, ph, center, width, mode)
                    self.values[key] = v
                res.update(v)
                res["files"] = files
            if need_fid:
                self._add_fid(res, ds_dir, ph, fid_mode)
            results.append(res)

        # FID phase relative to the median over the ON records
        fid_ref, latest_fid = None, None
        if need_fid:
            on_ph = [r["fid"]["phase"] for r in results
                     if r["kind"] == "ON" and r["fid"]["phase"] is not None]
            if buildup and not on_ph:            # a build-up of OFF records only
                on_ph = [r["fid"]["phase"] for r in results if r["fid"]["phase"] is not None]
            if on_ph:
                fid_ref = phase_reference(on_ph)
                for r in results:
                    if r["fid"]["phase"] is not None:
                        r["fid"]["phase_rel"] = float(wrap_pm180(r["fid"]["phase"] - fid_ref))
            have = [r for r in results if r["fid"]["read"]]
            if have:
                r = max(have, key=lambda q: q["expno"])
                try:
                    latest_fid = {"row": r, "fid": self.fid(ds_dir, r["expno"])}
                except Exception:
                    latest_fid = None

        for r in results:
            r.update(err=None, err_int=None, noise=None, err_note="")
            if errm == "noise" and r["files"] is not None:
                n = self._noise(ds_dir, r, ph, center, width, mode, region)
                r.update(err=n["err"], err_int=n["err_int"], noise=n["noise"], err_note=n["note"])
                for k, v in (("err", r["value"]), ("err_int", r["integral"])):
                    if r[k] is not None and v is not None and not r[k] > 1e-9 * abs(v):
                        r[k] = None                  # no measurable noise (e.g. simulated data)
                        r["err_note"] = r["err_note"] or "noise: none measurable"

        off_mode = meta.get("off_mode", "none")
        starts = {}
        for r in results:
            if r["kind"] == "OFF" and r["label"] == "start" and r["set"] not in starts:
                starts[r["set"]] = r
        valid = dict((s, o) for s, o in starts.items() if o["value"] not in (None, 0.0))
        use_enh = off_mode in ("start", "both") and len(valid) > 0
        valid_i = dict((s, o) for s, o in starts.items() if o["integral"] not in (None, 0.0))
        for r in results:
            r["yi"] = None
            if r["kind"] != "ON" or r["integral"] is None:
                continue
            if not use_enh:
                r["yi"] = r["integral"]
            elif r["set"] in valid_i:
                r["yi"] = r["integral"] / valid_i[r["set"]]["integral"] - 1.0
        for r in results:
            r["y"] = None
            if r["kind"] != "ON" or r["value"] is None:
                continue
            if not use_enh:
                r["y"] = r["value"]
            elif r["set"] in valid:
                r["y"] = r["value"] / valid[r["set"]]["value"] - 1.0
            else:
                r["note"] = (r["note"] + "; " if r["note"] else "") + \
                    "no usable start OFF in set %d" % r["set"]

        if buildup:                              # ON and OFF are both series, against D1
            for r in results:
                r["y"] = r["value"] if r["d1"] is not None else None
                r["yi"] = None
        # sigma of y and yi from the noise floor (ratio to the start OFF of the set)
        for r in results:
            r["ey"] = r["eyi"] = None
            if errm != "noise":
                continue
            if r["y"] is not None:
                if buildup or not use_enh:
                    r["ey"] = r["err"]
                elif r["set"] in valid:
                    o = valid[r["set"]]
                    r["ey"] = ratio_sigma(r["value"], r["err"], o["value"], o["err"])
            if r.get("yi") is not None:
                if not use_enh:
                    r["eyi"] = r["err_int"]
                elif r["set"] in valid_i:
                    o = valid_i[r["set"]]
                    r["eyi"] = ratio_sigma(r["integral"], r["err_int"], o["integral"], o["err_int"])
        fits = OrderedDict()
        if buildup:
            fits = buildup_fits(buildup_view(results, errm), ph.get("fit_model", "mono"),
                                bool(ph.get("fit_sigma")) and errm != "none")

        latest = None
        readable = [r for r in results if r["readable"]]
        if readable:
            r = max(readable, key=lambda q: q["expno"])
            try:
                spec = self.spectrum(ds_dir, r["expno"], r["files"])
                y, _, _ = corrected(spec, ph, center, width)
                latest = {"row": r, "ppm": spec["ppm"], "y": y / spec["ns"]}
            except Exception:
                latest = None
        return {"meta": meta, "results": results, "ended": ended, "center": center,
                "width": width, "mode": mode, "off_mode": off_mode, "use_enh": use_enh,
                "starts": valid, "latest": latest, "phase": dict(ph), "ds_dir": ds_dir,
                "multi_set": len(set(r["set"] for r in results)) > 1,
                "show_integral": bool(ph.get("show_integral")) and mode != "sum" and not buildup,
                "n_phase_skipped": len([q for q in results if q["phase_skipped"]]),
                "fid_mode": fid_mode, "fid_n": int(ph["fid_n"]), "fid_fit": bool(ph["fid_fit"]),
                "show_fid_phase": bool(ph.get("show_fid_phase")), "need_fid": need_fid,
                "fid_ref": fid_ref, "latest_fid": latest_fid, "plan": run_plan(self.runpath),
                "buildup": buildup, "fits": fits, "fit_model": ph.get("fit_model", "mono"),
                "error_bars": errm, "noise_region": region,
                "fit_sigma": bool(ph.get("fit_sigma")) and errm != "none",
                "log_d1": bool(ph.get("log_d1")), "normalize": bool(ph.get("normalize")),
                "planned": planned_records(self.runpath) if buildup else None}

    # -- CSV ----------------------------------------------------------------------
    def window_integrals(self, ds_dir, r, ph, center, width):
        """(real integral, magnitude integral, note) per scan over the window, with the
        phase and baseline settings of ph."""
        tag = (proc_key(dict(ph, magnitude=False)), center, width)
        if tag != self.csv_tag:
            self.csv_cache, self.csv_tag = {}, tag
        key = (r["expno"], r["files"])
        hit = self.csv_cache.get(key)
        if hit is not None:
            return hit
        notes, re_i, mag_i = [], None, None
        try:
            spec = self.spectrum(ds_dir, r["expno"], r["files"])
            y, n1, _ = corrected(spec, dict(ph, magnitude=False), center, width)
            re_i = integrate(spec["ppm"], y, center, width) / spec["ns"]
            notes.extend(n1)
            if spec["im"] is None:
                notes.append("magnitude integral: %s" % spec["im_note"])
            else:
                y, n2, _ = corrected(spec, dict(ph, magnitude=True), center, width)
                mag_i = integrate(spec["ppm"], y, center, width) / spec["ns"]
                notes.extend("magnitude integral: " + x for x in n2)
        except Exception as ex:
            notes.append(str(ex))
        out = (re_i, mag_i, "; ".join(notes))
        self.csv_cache[key] = out
        return out

    def write_csv(self, path, a):
        """One row per record; a must come from run(force_fid=True)."""
        ph = a["phase"]

        def g6(x):
            return "" if x is None else "%.6g" % x
        rows = []
        for r in a["results"]:
            f = r["fid"] or {}
            if r["files"] is not None:
                re_i, mag_i, inote = self.window_integrals(a["ds_dir"], r, ph, a["center"], a["width"])
            else:
                re_i, mag_i, inote = None, None, r["note"]
            date = f.get("date")
            rows.append([
                r["expno"], r["set"], r["kind"], r["label"],
                "" if r["freq"] is None else "%.4f" % r["freq"],
                "" if date is None else time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(date)),
                "" if date is None else "%d" % date,
                f.get("ns") if f.get("ns") is not None else (r["ns"] if r["ns"] is not None else ""),
                g6(f.get("rg")), g6(f.get("grpdly")),
                g6(f.get("mean")), g6(f.get("fit")),
                "" if f.get("phase_rel") is None else "%.2f" % f["phase_rel"],
                "" if f.get("phase") is None else "%.2f" % f["phase"],
                g6(re_i), g6(mag_i),
                "; ".join([x for x in (f.get("note", ""), inote) if x])])
        n = a["fid_n"]
        head = [
            "fs_plot.py records of run %s, written %s" % (run_label(self.runpath),
                                                         time.strftime("%Y-%m-%d %H:%M:%S")),
            "fid_t0_*: |fid| at t0 divided by NS*RG, from the N = %d complex points c[g:g+N], "
            "g = ceil(GRPDLY); mean = mean |c|, fit = straight line fitted to |c| against the point "
            "index, evaluated at t = GRPDLY; the viewer uses %s" % (n, "fit" if a["fid_fit"] else "mean"),
            "fid_phase_deg: arg(mean c[g:g+N]) minus the median over the ON records (%s), wrapped to "
            "(-180, 180]; fid_phase_abs_deg: without that reference"
            % ("none" if a["fid_ref"] is None else "%.2f deg" % a["fid_ref"]),
            "*_integral_per_scan: integral over the %s (sum of the points times the ppm step) / NS; "
            "real: %s; magnitude: |1r + i*1i|%s"
            % (window_text(a), describe_phase(dict(ph, magnitude=False, baseline=False), window=False),
               "; baseline polynomial order %d on both" % ph["order"] if ph["baseline"] else "; no baseline"),
            "acq_time: acqus DATE in the local time of the computer that wrote this file"]
        cols = ["expno", "set", "kind", "label", "freq_GHz", "acq_time", "acq_epoch_s", "ns", "rg",
                "grpdly", "fid_t0_mean_per_ns_rg", "fid_t0_fit_per_ns_rg", "fid_phase_deg",
                "fid_phase_abs_deg", "real_integral_per_scan", "magnitude_integral_per_scan", "note"]
        if a.get("buildup"):                     # D1 after the frequency
            cols.insert(5, "d1_s")
            for row, r in zip(rows, a["results"]):
                row.insert(5, "" if r["d1"] is None else "%g" % r["d1"])
        if a.get("error_bars") == "noise":       # noise-floor sigmas at the end
            cols += ["noise_sigma_point_per_scan", "sigma_value", "sigma_integral"]
            head.append("noise_sigma_point_per_scan: noise of one spectrum point; sigma_value: of the "
                        "intensity measure (FID(t0): per NS*RG, from the fid tail); sigma_integral: of the "
                        "window integral with the viewer's settings (%s)" % error_text(a, ascii_only=True))
            for row, r in zip(rows, a["results"]):
                row += [g6(r.get("noise")), g6(r.get("err")), g6(r.get("err_int"))]
        tmp = path + ".tmp"
        with open(tmp, "w", newline="") as fh:
            for h in head:
                fh.write("# %s\n" % h)
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows(rows)
        os.replace(tmp, path)


def window_text(a):
    if a["center"] is None:
        return "whole spectrum"
    return "window %.1f +/- %.1f ppm" % (a["center"], a["width"] / 2.0)


def grpdly_text(res):
    grp = sorted(set(r["fid"]["grpdly"] for r in res if r["fid"] and r["fid"]["g"] is not None))
    if len(grp) == 1:
        return "GRPDLY %.4g, g = %d" % (grp[0], int(math.ceil(grp[0])))
    if grp:
        return "GRPDLY %.4g to %.4g (differs between records)" % (grp[0], grp[-1])
    return "no usable GRPDLY"


def fid_status(a):
    """Lines describing FID(t0) / the FID phase, with the records it could not be computed for."""
    lines = []
    if not (a["fid_mode"] or a["show_fid_phase"]):
        return lines
    res = a["results"]
    gtxt = grpdly_text(res)
    n = a["fid_n"]
    if a["fid_mode"]:
        how = ("line fitted to |fid[g..g+%d]|, at t = GRPDLY" % (n - 1) if a["fid_fit"]
               else "mean |fid[g..g+%d]|" % (n - 1))
        lines.append("FID(t0): %s / (NS*RG); %s" % (how, gtxt))
    if a["show_fid_phase"]:
        ref = "the ON records"
        if a.get("buildup") and not any(r["kind"] == "ON" for r in res):
            ref = "the records"
        lines.append("FID phase (lower panel): arg(mean fid[g..g+%d]) relative to the median of %s%s"
                     % (n - 1, ref, "" if a["fid_mode"] else "; " + gtxt))
    bad = OrderedDict()                  # reason -> expnos without a usable GRPDLY
    for r in res:
        if r["fid"] and r["fid"]["read"] and r["fid"]["g"] is None:
            bad.setdefault(r["fid"]["note"].replace(": FID(t0) not computed", ""), []).append(r["expno"])
    for why, ex in bad.items():
        lines.append("WARNING: FID(t0) not computed for %d record(s), %s: expno %s"
                     % (len(ex), why, ", ".join(str(e) for e in ex[:6]) + (", ..." if len(ex) > 6 else "")))
    return lines


def phase_status(a):
    """Lines describing the correction for the figure and the TSV; [] if nothing is corrected.
    In FID(t0) mode the spectrum settings are listed only when the window integral is shown."""
    lines = spectrum_status(a)
    if a["fid_mode"]:
        lines = ["window integral: " + x for x in lines] if a["show_integral"] else []
    return fid_status(a) + lines


def spectrum_status(a):
    ph = a["phase"]
    lines = []
    if ph.get("magnitude"):
        lines.append("magnitude spectra |1r + i*1i| (phase not used)")
        if a["n_phase_skipped"]:
            lines.append("magnitude not possible for %d record(s) without 1i (see the TSV)"
                         % a["n_phase_skipped"])
    elif phase_active(ph):
        lines.append("phase correction: " + describe_phase(dict(ph, baseline=False), window=False))
        if a["n_phase_skipped"]:
            lines.append("phase correction not applied to %d record(s) (see the TSV)"
                         % a["n_phase_skipped"])
    if ph["baseline"]:
        lines.append("baseline correction: polynomial order %d" % ph["order"])
    if ph.get("show_integral") and a["mode"] == "sum":
        lines.append("integral not plotted separately: the intensity mode is already 'sum'")
    return lines


def run_plan(runpath):
    """(first, last) planned expno from settings.txt in the run folder (written by fs_core.py),
    or None (older run files have none)."""
    if not is_run_folder_layout(runpath):
        return None
    try:
        with open(os.path.join(os.path.dirname(runpath), "settings.txt")) as fh:
            for line in fh:
                m = re.match(r"#\s*expnos:\s*(\d+)\.\.(\d+)", line)
                if m:
                    return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None


def clock(t, now):
    """HH:MM, with the date if t is not today."""
    if time.strftime("%Y%m%d", time.localtime(t)) == time.strftime("%Y%m%d", time.localtime(now)):
        return time.strftime("%H:%M", time.localtime(t))
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def run_state(a, now=None):
    """State of the run for the window: kind ('running', 'stale', 'complete', 'stopped'),
    title and detail. 'stale': no end line, but no new record for much longer than usual."""
    now = time.time() if now is None else now
    rows = a["results"]
    times = []
    for r in rows:
        try:
            times.append(time.mktime(time.strptime(r["finished"], "%Y-%m-%d %H:%M:%S")))
        except Exception:
            pass
    plan = a.get("plan")
    last = max([r["expno"] for r in rows]) if rows else None
    if plan is not None:
        done = 0 if last is None else last - plan[0] + 1
        total = plan[1] - plan[0] + 1
        parts = ["record %d of %d" % (done, total)]
    else:
        done, total = len(rows), None
        parts = ["%d record%s" % (done, "" if done == 1 else "s")]
    gaps = np.diff(times[-11:]) if len(times) >= 2 else np.array([])
    step = float(np.median(gaps)) if gaps.size else None
    ended = a["ended"]
    if ended is not None:
        if times:
            parts.append("last record %s" % clock(times[-1], now))
        if ended == "complete":
            return {"kind": "complete", "title": "Finished", "detail": " · ".join(parts)}
        return {"kind": "stopped", "title": "Stopped before the end",
                "detail": " · ".join([ended[len("stopped: "):] if ended.startswith("stopped: ") else ended]
                                     + parts)}
    planned = a.get("planned")                 # build-up: expected duration of each record
    if planned and last is not None:
        todo = [e for x, e in planned if x > last]
    else:
        todo = None
    if times:
        quiet = now - times[-1]
        limit = max(4 * step, 600) if step else 3600      # s without a new record
        if todo:                               # records differ in length: the next one is overdue
            limit = max(2 * todo[0], todo[0] + 600)
        if quiet > limit:
            return {"kind": "stale", "title": "No new record for %d min" % (quiet // 60),
                    "detail": " · ".join(parts + ["last record %s" % clock(times[-1], now),
                                                  "the run file has no end line: check TopSpin"])}
        if todo:
            parts.append("ends ≈ %s" % clock(times[-1] + sum(todo), now))
        elif step and total is not None and done < total and todo is None:
            parts.append("ends ≈ %s" % clock(times[-1] + (total - done) * step, now))
        parts.append("last record %s" % clock(times[-1], now))
    return {"kind": "running", "title": "Experiment running", "detail": " · ".join(parts)}


def profile_info(a, runpath):
    """Rows (key, text, warn) describing the run and the profile, for the window."""
    meta, res, fidm = a["meta"], a["results"], a["fid_mode"]
    rows = []
    started = meta.get("started", "")
    run = [x for x in (meta.get("sample", ""), meta.get("conditions", "")) if x]
    run.append("run %s" % run_label(runpath))
    run.append("dataset %s" % (os.path.basename(meta.get("dataset_dir", "")) or "?"))
    if started:
        run.append("started %s" % started[:16])
    rows.append(("Run", " · ".join(run), False))
    win = window_text(a).replace("+/-", "±")
    if fidm:
        meas = [mode_label(a["mode"], a), grpdly_text(res), "divided by NS·RG"]
    else:
        meas = [win, "%s (%s)" % (a["mode"], MODE_HELP.get(a["mode"], ""))]
    proc = spectrum_status(a)
    proc_txt = " · ".join(proc) if proc else "spectra as processed by TopSpin"
    if fidm:
        if a["show_integral"]:
            meas.append("window integral: %s, %s" % (win, proc_txt))
    else:
        meas.append(proc_txt)
        if a["show_integral"] and a["mode"] != "sum":
            meas.append("window integral also plotted")
    if a.get("error_bars", "none") != "none":
        meas.append(error_text(a))
    rows.append(("Measure", " · ".join(meas), False))
    unit = "per NS·RG" if fidm else "per scan"
    offs = [r for r in res if r["kind"] == "OFF"]
    set_ids = sorted(set(r["set"] for r in offs))
    for s in set_ids[-3:]:
        txt = []
        so = None
        for r in [q for q in offs if q["set"] == s]:
            if r["value"] is None:
                txt.append("%s (expno %d): %s" % (r["label"], r["expno"], r["note"]))
            else:
                txt.append("%s (expno %d) %.4g %s" % (r["label"], r["expno"], r["value"], unit))
            if r["label"] == "start" and so is None:
                so = r
        eo = [q for q in offs if q["set"] == s and q["label"] == "end"]
        if so is not None and so["value"] and eo and eo[0]["value"] is not None:
            txt.append("end/start %.3f" % (eo[0]["value"] / so["value"]))
        rows.append(("OFF" if len(set_ids) == 1 else "OFF set %d" % s, " · ".join(txt), False))
    if len(set_ids) > 3:
        rows.append(("", "(OFF records of the last 3 of %d sets)" % len(set_ids), False))
    if a["off_mode"] in ("start", "both") and not a["use_enh"]:
        rows.append(("Warning", "no usable start OFF: the profile shows the intensity per scan", True))
    for line in fid_status(a):
        if line.startswith("WARNING: "):
            rows.append(("Warning", line[len("WARNING: "):], True))
    bad = [r for r in res if r["kind"] == "ON" and r["value"] is None
           and not (fidm and r["fid"]["read"] and r["fid"]["g"] is None)]
    for r in bad[-3:]:
        rows.append(("Warning", "expno %d: %s" % (r["expno"], r["note"]), True))
    return rows


def series_name(key, multi):
    kind, s = key
    if s == 0:                                   # mean over repeated records
        return "%s mean" % kind
    return ("%s set %d" % (kind, s)) if multi else kind


def fit_ratios(a):
    """[(set, S_inf ratio, max S/sqrt(t) ratio)] for the sets with both ON and OFF fitted."""
    out = []
    fits = a["fits"]
    for (kind, s), f in fits.items():
        g = fits.get(("OFF", s))
        if kind != "ON" or g is None or "error" in f or "error" in g \
                or not (f["determined"] and g["determined"]):
            continue
        r1 = f["s_inf"] / g["s_inf"] if g["s_inf"] else None
        r2 = f["s_opt"] / g["s_opt"] if g["s_opt"] else None
        out.append((s, r1, r2))
    return out


def buildup_info(a, runpath):
    """Rows (key, text, warn) for a build-up run, for the window: run, measure and fit model,
    one row per fitted series, the ON/OFF ratios, and notes and warnings."""
    rows = profile_info(a, runpath)[:1]          # Run
    model = a["fit_model"]
    if a["fid_mode"]:
        meas = [mode_label(a["mode"], a), grpdly_text(a["results"]), "per NS·RG"]
    else:
        proc = spectrum_status(a)
        meas = [window_text(a).replace("+/-", "±"), a["mode"],
                "; ".join(proc) if proc else "spectra as processed by TopSpin"]
    meas.append("fit: %s %s, %s, ± 1 standard error" % (FIT_MODELS[model], FIT_FORMULAS_UI[model],
                                                         fit_weight_text(a)))
    if a["error_bars"] != "none":
        meas.append(error_text(a))
    rows.append(("Measure", " · ".join(meas), False))
    multi = a["multi_set"]
    notes = []
    for key, f in a["fits"].items():
        name = series_name(key, multi)
        if "error" in f:
            rows.append((name, "no fit: %s" % f["error"], True))
            continue
        rows.append((name, fit_summary_ui(f), not f["determined"]))
        notes += ["%s %s" % (name, ui_text(n)) for n in f["notes"]]
    for s, r1, r2 in fit_ratios(a):
        txt = []
        if r1 is not None:
            txt.append("S∞ %.4g" % r1)
        if r2 is not None:
            txt.append("max S/√t %.4g" % r2)
        rows.append(("ON/OFF" if (not multi or s == 0) else "ON/OFF %d" % s, " · ".join(txt), False))
    if not a["fits"]:
        rows.append(("", "waiting for the first record", False))
    if notes:
        rows.append(("Note", "; ".join(notes), True))
    for line in fid_status(a):
        if line.startswith("WARNING: "):
            rows.append(("Warning", line[len("WARNING: "):], True))
    bad = [r for r in a["results"] if r["value"] is None
           and not (a["fid_mode"] and r["fid"]["read"] and r["fid"]["g"] is None)]
    for r in bad[-3:]:
        rows.append(("Warning", "expno %d: %s" % (r["expno"], r["note"]), True))
    return rows


def write_buildup_tsv(path, a):
    """values.tsv of a build-up: one row per record, with D1 and the fitted value; the fits in
    the header."""
    if a["fid_mode"]:
        what = "mode %s (intensity_per_scan = FID(t0) / (NS*RG))" % mode_label(a["mode"], a)
    else:
        what = "%s, mode %s" % (window_text(a), a["mode"])
    fits = a["fits"]
    with open(path, "w") as fh:
        fh.write("# build-up; %s; y = %s against D1\n"
                 % (what, "FID(t0) per NS*RG" if a["fid_mode"] else "intensity per scan"))
        st = phase_status(a)
        fh.write("# %s\n" % ("; ".join(st) if st else "phase: as processed by TopSpin"))
        fh.write("# fit: %s, %s; least squares %s; +/- one standard error\n"
                 % (FIT_MODELS[a["fit_model"]], FIT_FORMULAS[a["fit_model"]], fit_weight_text(a, True)))
        em = a["error_bars"]
        if em != "none":
            fh.write("# %s\n" % error_text(a, ascii_only=True))
        for key, f in fits.items():
            name = series_name(key, a["multi_set"])
            if "error" in f:
                fh.write("# %s: no fit: %s\n" % (name, f["error"]))
            else:
                notes = f["notes"] + ([] if f["determined"] else ["not determined: " + f["why"]])
                fh.write("# %s: %s%s\n" % (name, fit_summary(f, ascii_only=True),
                                          "".join("; NOTE: " + n for n in notes)))
        for s, r1, r2 in fit_ratios(a):
            fh.write("# ON/OFF%s: S_inf ratio %s; max S/sqrt(t) ratio %s\n"
                     % (" set %d" % s if (a["multi_set"] and s) else "",
                        "-" if r1 is None else "%.4g" % r1, "-" if r2 is None else "%.4g" % r2))
        view = buildup_view(a["results"], em)
        extra = {"none": "", "noise": "\tsigma_per_scan", "repeats": "\tmean_per_scan\tsem_per_scan\tn_repeats"}[em]
        fh.write("expno\tkind\tlabel\tset\td1_s\tns\tintensity_per_scan\tppm_of_point\tfit_per_scan\tnote%s\n"
                 % extra)
        for r in a["results"]:
            f = fits.get((r["kind"], 0 if em == "repeats" else r["set"]))
            fv = ""
            if f is not None and "error" not in f and r["d1"] is not None:
                fv = "%.6g" % fit_model_value(f["model"], f["p"], [r["d1"]])[0]
            cols = ""
            if em == "noise":
                cols = "\t" + ("" if r["ey"] is None else "%.4g" % r["ey"])
            elif em == "repeats":
                vp = view_point(view, r)
                if vp is None:
                    cols = "\t\t\t"
                else:
                    v, i = view[vp[0]], vp[1]
                    cols = "\t%.6g\t%s\t%d" % (v["y"][i], "" if v["e"][i] is None else "%.4g" % v["e"][i], v["n"][i])
            fh.write("%d\t%s\t%s\t%d\t%s\t%s\t%s\t%s\t%s\t%s%s\n" % (
                r["expno"], r["kind"], r["label"], r["set"],
                "" if r["d1"] is None else "%g" % r["d1"],
                r["ns"] if r["ns"] is not None else r["ns_run"],
                "" if r["value"] is None else "%.6g" % r["value"],
                "" if r["at"] is None else "%.2f" % r["at"], fv, r["note"], cols))


def write_tsv(path, a):
    if a.get("buildup"):
        return write_buildup_tsv(path, a)
    if a["fid_mode"]:
        what = "mode %s (intensity_per_scan = FID(t0) / (NS*RG)); integral columns: %s" % (
            mode_label(a["mode"], a), window_text(a))
    else:
        what = "%s, mode %s" % (window_text(a), a["mode"])
    with open(path, "w") as fh:
        fh.write("# %s; y = %s\n"
                 % (what,
                    "I_on/I_off - 1 (start OFF of the set)" if a["use_enh"] else "intensity per scan"))
        st = phase_status(a)
        fh.write("# %s\n" % ("; ".join(st) if st else "phase: as processed by TopSpin"))
        em = a.get("error_bars", "none")
        if em != "none":
            fh.write("# %s\n" % error_text(a, ascii_only=True))
        extra = {"none": "", "noise": "\tsigma_per_scan\ty_sigma\tintegral_sigma\ty_integral_sigma",
                 "repeats": "\ty_mean\ty_sem\tn_repeats"}[em]
        fh.write("expno\tkind\tlabel\tfreq_GHz\tns\tintensity_per_scan\tppm_of_point\ty\tnote\tset"
                 "\tintegral_per_scan\ty_integral%s\n" % extra)
        groups = profile_means(dict(a, show_integral=False))[0] if em == "repeats" else []
        for r in a["results"]:
            extra = ""
            if em == "noise":
                vals = [r.get("err"), r.get("ey"), r.get("err_int"), r.get("eyi")]
                extra = "".join("\t" + ("" if v is None else "%.4g" % v) for v in vals)
            elif em == "repeats":
                m = [q for q in groups if r in q["recs"]]
                extra = ("\t%.6g\t%s\t%d" % (m[0]["y"], "" if m[0]["e"] is None else "%.4g" % m[0]["e"],
                                              m[0]["n"])) if m else "\t\t\t"
            fh.write("%d\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%d\t%s\t%s%s\n" % (
                r["expno"], r["kind"], r["label"],
                "-" if r["freq"] is None else "%.4f" % r["freq"],
                r["ns"] if r["ns"] is not None else r["ns_run"],
                "" if r["value"] is None else "%.6g" % r["value"],
                "" if r["at"] is None else "%.2f" % r["at"],
                "" if r["y"] is None else "%.6g" % r["y"],
                r["note"], r["set"],
                "" if r["integral"] is None else "%.6g" % r["integral"],
                "" if r.get("yi") is None else "%.6g" % r["yi"], extra))


# --------------------------------------------------------------------------
# Plot
# --------------------------------------------------------------------------
SET_COLORS = ["#1f5fa8", "#2a9d5c", "#8e44ad", "#d68910", "#17a2b8", "#7f8c8d"]


class Panels:
    """The main figure: the profile (ax1, with the right-hand axis ax1b for the integral),
    the latest spectrum or FID (ax2), and the FID phase below the profile (ax3, same x
    axis; None while the phase panel is not shown). with_right=False: the profile only
    (ax2 None), as shown in the window next to the spectrum pane; reopen None: no
    reopen command along the bottom; compact: shorter labels (the window)."""

    def __init__(self, reopen, with_right=True, figsize=(12, 5), compact=False):
        self.fig = Figure(figsize=figsize)
        self.with_right = with_right
        self.compact = compact
        self.ax1 = self.ax2 = self.ax1b = self.ax3 = None
        self.show_phase = None
        self.layout(False)
        self.with_text = reopen is not None
        if self.with_text:
            self.fig.text(0.008, 0.012, "To reopen this plot from a terminal:  " + reopen,
                          ha="left", va="bottom", fontsize=8, family="monospace", color="0.3")

    def layout(self, show_phase):
        """Makes the axes for the phase panel shown or not. Returns True if they changed."""
        show_phase = bool(show_phase)
        if show_phase == self.show_phase:
            return False
        for ax in (self.ax1, self.ax1b, self.ax2, self.ax3):
            if ax is not None:
                self.fig.delaxes(ax)
        if not self.with_right:
            self.ax2 = None
            if show_phase:
                gs = self.fig.add_gridspec(2, 1, height_ratios=[2.6, 1])
                self.ax1 = self.fig.add_subplot(gs[0, 0])
                self.ax3 = self.fig.add_subplot(gs[1, 0], sharex=self.ax1)
            else:
                self.ax1 = self.fig.add_subplot(111)
                self.ax3 = None
        elif show_phase:
            gs = self.fig.add_gridspec(2, 2, width_ratios=[2, 1], height_ratios=[2.6, 1])
            self.ax1 = self.fig.add_subplot(gs[0, 0])
            self.ax2 = self.fig.add_subplot(gs[:, 1])
            self.ax3 = self.fig.add_subplot(gs[1, 0], sharex=self.ax1)
        else:
            self.ax1, self.ax2 = self.fig.subplots(1, 2, gridspec_kw={"width_ratios": [2, 1]})
            self.ax3 = None
        self.ax1b = self.ax1.twinx()
        self.ax1b.set_visible(False)
        self.show_phase = show_phase
        return True

    def fit_layout(self):
        """The window's figure (no title): the axes fill the canvas."""
        relayout(self.fig, 0.0, 1.0)


def record_what(r, multi):
    """'ON 526.050 GHz' or 'OFF start' (build-ups: 'ON, D1 30 s'), with the set if there are
    several."""
    if r.get("d1") is not None:
        what = "%s, D1 %g s" % (r["kind"], r["d1"])
    else:
        what = ("ON %.3f GHz" % r["freq"]) if r["kind"] == "ON" else ("OFF %s" % r["label"])
    return ("set %d, %s" % (r["set"], what)) if multi else what


def draw_fid_start(ax, a):
    """Right-hand panel in FID(t0) mode: the start of the latest FID."""
    lf = a["latest_fid"]
    if lf is None:
        ax.text(0.5, 0.5, "no fid yet", transform=ax.transAxes, ha="center", va="center", color="0.4")
        return
    r = lf["row"]
    draw_fid_record(ax, lf["fid"], a["fid_n"], a["fid_fit"],
                    "latest: expno %d, %s, start of the FID" % (r["expno"], record_what(r, a["multi_set"])))


def draw_fid_record(ax, fid, n, fit, title):
    """|fid| / (NS*RG) against the point index, from a little before GRPDLY, with GRPDLY,
    the N points used, and FID(t0) (mean, or the fitted line at t = GRPDLY if fit)."""
    g, c = fid["g"], fid["c"]
    norm = float(fid["ns"]) * fid["rg"]
    start = max(0, (g if g is not None else 0) - 24)      # some points before GRPDLY, to see the onset
    stop = min(c.size, (g if g is not None else 0) + max(48, 3 * n))
    k = np.arange(start, stop)
    ax.plot(k, np.abs(c[start:stop]) / norm, ".-", color="0.15", lw=0.8, ms=4)
    if g is not None:
        ax.axvline(fid["grpdly"], color="#e67e22", ls="--", lw=1.0, label="GRPDLY %.3f" % fid["grpdly"])
        ax.axvspan(g - 0.5, g + n - 0.5, color="#1f5fa8", alpha=0.15, label="N = %d points from g = %d" % (n, g))
        try:
            m = fid_t0(fid, n)
            if fit and m["line"] is not None:
                kk = np.array([fid["grpdly"], g + n - 1.0])
                ax.plot(kk, m["line"][1] + m["line"][0] * kk, "-", color="#c0392b", lw=1.2)
                ax.plot([fid["grpdly"]], [m["fit"]], "o", color="#c0392b", ms=6, label="FID(t0) %.4g" % m["fit"])
            else:
                ax.plot([g, g + n - 1], [m["mean"], m["mean"]], "-", color="#c0392b", lw=2.0,
                        label="FID(t0) %.4g" % m["mean"])
        except ValueError as ex:
            ax.text(0.02, 0.95, str(ex), transform=ax.transAxes, va="top", fontsize=8, color="#8a1c1c")
        ax.legend(fontsize=7, loc="best")
    else:
        ax.text(0.02, 0.95, "%s: FID(t0) not computed" % fid["warn"], transform=ax.transAxes,
                va="top", fontsize=8, color="#8a1c1c")
    ax.set_xlim(start - 0.5, stop - 0.5)
    if title:
        ax.set_title(title, fontsize=9)
    ax.set_xlabel("fid point (complex)")
    ax.set_ylabel("|fid| / (NS*RG)")


def draw_fid_phase(ax3, a, compact=False):
    """Phase panel: FID phase of the ON records relative to their median, against frequency."""
    on = [r for r in a["results"] if r["kind"] == "ON" and r["freq"] is not None
          and r["fid"] and r["fid"]["phase_rel"] is not None]
    if on:
        sets = sorted(set(r["set"] for r in on))
        for i, s in enumerate(sets):
            pts = sorted([r for r in on if r["set"] == s], key=lambda r: r["freq"])
            ax3.plot([r["freq"] for r in pts], [r["fid"]["phase_rel"] for r in pts], "-o",
                     color=SET_COLORS[i % len(SET_COLORS)], ms=4 if len(pts) < 150 else 2.5, lw=1.0)
        latest = max(on, key=lambda r: r["expno"])
        ax3.plot([latest["freq"]], [latest["fid"]["phase_rel"]], "o", color="#c0392b", ms=7, zorder=3)
    else:
        ax3.text(0.5, 0.5, "no FID phase (see the lines above the profile)", transform=ax3.transAxes,
                 ha="center", va="center", color="0.4")
    ax3.axhline(0.0, color="0.6", lw=0.8)
    if compact:
        ax3.set_title("FID phase (deg), relative to the median of the ON records", loc="left", fontsize=8)
    else:
        ax3.set_ylabel("FID phase (deg)", fontsize=9)
    ax3.set_xlabel("mm-wave frequency (GHz)")
    ax3.grid(True, color="0.9")


def error_bars(ax, recs, xkey, ykey, ekey, color, lw=0.9, scale=1.0):
    """Error bars (no markers) at the records that have a sigma; returns the artists."""
    pts = [r for r in recs if r.get(ekey) is not None and r.get(ykey) is not None]
    if not pts:
        return []
    c = ax.errorbar([r[xkey] for r in pts], [r[ykey] * scale for r in pts],
                    yerr=[r[ekey] * scale for r in pts], fmt="none", ecolor=color, elinewidth=lw,
                    capsize=2.5, zorder=2.5)
    return [x for x in [c.lines[0]] + list(c.lines[1]) + list(c.lines[2]) if x is not None]


def profile_means(a):
    """Means over the sets at each frequency: (peak or FID(t0) groups, integral groups)."""
    on = [r for r in a["results"] if r["kind"] == "ON" and r["y"] is not None and r["freq"] is not None]
    g = repeat_means(on, "freq", "y", nd=4)
    gi = repeat_means([r for r in on if r.get("yi") is not None], "freq", "yi", nd=4) \
        if a["show_integral"] else []
    return g, gi


def draw_profile_repeats(ax1, ax_int, a, ms=5, lw=1.2, latest=True):
    """The profile as the mean over the sets at each frequency with its standard error
    (and the window integral on ax_int). Returns the artists."""
    g, gi = profile_means(a)
    if not g:
        return []
    col = SET_COLORS[0]
    nsets = max(q["n"] for q in g)
    what = ("FID(t0)" if a["fid_mode"] else "peak") if a["show_integral"] else ""
    label = "mean of %d sets%s" % (nsets, (", " + what) if what else "")
    arts = error_bars(ax1, [{"x": q["x"], "y": q["y"], "e": q["e"]} for q in g], "x", "y", "e", col)
    arts += ax1.plot([q["x"] for q in g], [q["y"] for q in g], "-o", color=col,
                     ms=ms if len(g) < 150 else 3, lw=lw, label=label)
    on = [r for q in g for r in q["recs"]]
    if latest and on:
        r = max(on, key=lambda q: q["expno"])
        m = [q for q in g if r in q["recs"]][0]
        ax1.plot([m["x"]], [m["y"]], "o", color="#c0392b", ms=8, zorder=3)
    if gi:
        if ax_int is not ax1:
            ax_int.set_visible(True)
            ax_int.set_ylabel("integral per scan (a.u. x ppm)")
        arts += error_bars(ax_int, [{"x": q["x"], "y": q["y"], "e": q["e"]} for q in gi], "x", "y", "e", col)
        arts += ax_int.plot([q["x"] for q in gi], [q["y"] for q in gi], "--s", color=col, mfc="none",
                            ms=4, lw=1.0, label="mean of %d sets, integral" % nsets)
    h, l = ax1.get_legend_handles_labels()
    if ax_int is not ax1 and ax_int.get_visible():
        h2, l2 = ax_int.get_legend_handles_labels()
        h, l = h + h2, l + l2
    ax1.legend(h, l, fontsize=8, loc="best")
    return arts


def draw_latest(ax2, a):
    """Right-hand panel of plot.png: the latest spectrum with the window, or the start of
    the latest FID (ax2 None: nothing)."""
    fidm, multi = a["fid_mode"], a["multi_set"]
    lt = a["latest"]
    if ax2 is None:
        return
    elif fidm:
        draw_fid_start(ax2, a)
    elif lt is not None:
        r, ppm, d = lt["row"], lt["ppm"], lt["y"]
        if a["center"] is None:
            lo, hi = float(ppm.min()), float(ppm.max())
            ax2.plot(ppm, d, color="0.15", lw=0.8)
        else:
            half = a["width"] / 2.0
            lo, hi = a["center"] - 4 * half, a["center"] + 4 * half
            sel = (ppm >= lo) & (ppm <= hi)
            if np.any(sel):
                ax2.plot(ppm[sel], d[sel], color="0.15", lw=0.8)
            ax2.axvspan(a["center"] - half, a["center"] + half, color="#1f5fa8", alpha=0.12)
        if r["at"] is not None and r["value"] is not None:
            ax2.plot([r["at"]], [r["value"]], "o", color="#c0392b", ms=6)
        ax2.set_xlim(hi, lo)
        ax2.set_title("latest: expno %d, %s" % (r["expno"], record_what(r, multi)), fontsize=9)
    else:
        ax2.text(0.5, 0.5, "no spectrum yet", transform=ax2.transAxes,
                 ha="center", va="center", color="0.4")
    if not fidm:
        ax2.set_xlabel("ppm")
        ax2.set_ylabel("intensity per scan")
    ax2.axhline(0.0, color="0.8", lw=0.6)


def draw(p, a, runpath):
    """p: Panels. ax1b, the twin of ax1 (right-hand axis), takes the integral when
    intensities are plotted."""
    if a.get("buildup"):
        return draw_buildup(p, a, runpath)
    p.layout(a["show_fid_phase"])
    ax1, ax2, ax1b, ax3 = p.ax1, p.ax2, p.ax1b, p.ax3
    fig = p.fig
    ax1.clear()
    if ax2 is not None:
        ax2.clear()
    ax1b.clear()
    ax1b.set_visible(False)
    if ax3 is not None:
        ax3.clear()
    res = a["results"]
    multi = a["multi_set"]
    show_i = a["show_integral"]
    fidm = a["fid_mode"]
    on = [r for r in res if r["kind"] == "ON" and r["y"] is not None]

    # Profile, one series per set; with show_i also the integral of the window
    errm = a.get("error_bars", "none")
    if on and errm == "repeats":                 # the mean over the sets, with its standard error
        draw_profile_repeats(ax1, ax1 if a["use_enh"] else ax1b, a)
    elif on:
        sets = sorted(set(r["set"] for r in on))
        for i, s in enumerate(sets):
            pts = sorted([r for r in on if r["set"] == s], key=lambda r: r["freq"])
            if multi:
                label = ("set %d, %s" % (s, "FID(t0)" if fidm else "peak")) if show_i else ("set %d" % s)
            elif fidm:
                label = "FID(t0)" if show_i else None
            else:
                label = ("peak (%s)" % a["mode"]) if show_i else None
            ax1.plot([r["freq"] for r in pts], [r["y"] for r in pts], "-o",
                     color=SET_COLORS[i % len(SET_COLORS)], ms=5 if len(pts) < 150 else 3, lw=1.2,
                     label=label)
            if errm == "noise":
                error_bars(ax1, pts, "freq", "y", "ey", SET_COLORS[i % len(SET_COLORS)])
        latest = max(on, key=lambda r: r["expno"])
        ax1.plot([latest["freq"]], [latest["y"]], "o", color="#c0392b", ms=8, zorder=3)
        if show_i:
            target = ax1 if a["use_enh"] else ax1b
            if target is ax1b:
                ax1b.set_visible(True)
                ax1b.set_ylabel("integral per scan (a.u. x ppm)")
            ion = [r for r in on if r.get("yi") is not None]
            for i, s in enumerate(sets):
                pts = sorted([r for r in ion if r["set"] == s], key=lambda r: r["freq"])
                if pts:
                    target.plot([r["freq"] for r in pts], [r["yi"] for r in pts], "--s",
                                color=SET_COLORS[i % len(SET_COLORS)], mfc="none", ms=4, lw=1.0,
                                label=("set %d, integral" % s) if multi else "integral")
                    if errm == "noise":
                        error_bars(target, pts, "freq", "yi", "eyi", SET_COLORS[i % len(SET_COLORS)])
            if ion:
                li = max(ion, key=lambda r: r["expno"])
                target.plot([li["freq"]], [li["yi"]], "s", color="#c0392b", mfc="none", ms=8, zorder=3)
        xs = set(r["freq"] for r in on)
        if len(xs) == 1:
            x0 = xs.pop()
            ax1.set_xlim(x0 - 0.005, x0 + 0.005)
        if multi or show_i:
            h, l = ax1.get_legend_handles_labels()
            if ax1b.get_visible():
                h2, l2 = ax1b.get_legend_handles_labels()
                h, l = h + h2, l + l2
            ax1.legend(h, l, fontsize=8, loc="best")
    else:
        ax1.text(0.5, 0.5, "waiting for the first ON record", transform=ax1.transAxes,
                 ha="center", va="center", color="0.4")
    if a["use_enh"]:
        ax1.axhline(0.0, color="0.6", lw=0.8)
        if len(a["starts"]) == 1 and not multi:
            off_expno = list(a["starts"].values())[0]["expno"]
            if fidm:
                ax1.set_ylabel("FID(t0)_on / FID(t0)_off - 1\n(per NS*RG; OFF = expno %d)" % off_expno)
            else:
                ax1.set_ylabel("I_on / I_off - 1   (per scan; OFF = expno %d)" % off_expno)
        elif fidm:
            ax1.set_ylabel("FID(t0)_on / FID(t0)_off - 1\n(per NS*RG; start OFF of each set)")
        else:
            ax1.set_ylabel("I_on / I_off - 1   (per scan; start OFF of each set)")
    elif fidm:
        ax1.set_ylabel("FID(t0) / (NS*RG) (a.u.)")
    else:
        ax1.set_ylabel(("peak " if show_i else "") + "intensity per scan (a.u.)")
    if p.compact:                            # the window: short labels (the OFF expno is above the plot)
        if a["use_enh"]:
            ax1.set_ylabel("FID(t0) on/off - 1" if fidm else "I_on / I_off - 1")
        else:
            ax1.set_ylabel("FID(t0) / (NS*RG)" if fidm else "intensity per scan")
    if ax3 is not None:
        if not p.compact:                    # shorter profile axes: label on two lines
            lab = ax1.get_ylabel().replace("   (", "\n(")
            ax1.set_ylabel(lab, fontsize=9)
        draw_fid_phase(ax3, a, p.compact)
        ax1.tick_params(labelbottom=False)
        fig.align_ylabels([ax1, ax3])
    else:
        ax1.set_xlabel("mm-wave frequency (GHz)")
    ax1.ticklabel_format(axis="x", useOffset=False)
    ax1.grid(True, color="0.9")

    # OFF records, phase and problems, shown above the profile
    lines = []
    offs = [r for r in res if r["kind"] == "OFF"]
    set_ids = sorted(set(r["set"] for r in offs))
    if len(set_ids) > 3:
        lines.append("(OFF records of the last 3 of %d sets)" % len(set_ids))
        set_ids = set_ids[-3:]
    show_ph = fidm or a["show_fid_phase"]
    for s in set_ids:
        pre = ("set %d  " % s) if multi else ""
        so = None
        for r in [q for q in offs if q["set"] == s]:
            if r["value"] is None:
                lines.append("%sOFF %s (expno %d): %s" % (pre, r["label"], r["expno"], r["note"]))
            else:
                extra = (", integral %.4g" % r["integral"]) if show_i and r["integral"] is not None else ""
                if show_ph and r["fid"] and r["fid"]["phase_rel"] is not None:
                    extra += ", FID phase %+.1f deg" % r["fid"]["phase_rel"]
                lines.append("%sOFF %s (expno %d): %.4g per %s%s"
                             % (pre, r["label"], r["expno"], r["value"], "NS*RG" if fidm else "scan", extra))
            if r["label"] == "start" and so is None:
                so = r
        eo = [q for q in offs if q["set"] == s and q["label"] == "end"]
        if so is not None and so["value"] and eo and eo[0]["value"] is not None:
            extra = ""
            if show_i and so["integral"] and eo[0]["integral"] is not None:
                extra = " (integral %.3f)" % (eo[0]["integral"] / so["integral"])
            lines.append("%send OFF / start OFF = %.3f%s" % (pre, eo[0]["value"] / so["value"], extra))
    if a["off_mode"] in ("start", "both") and not a["use_enh"]:
        lines.append("start OFF not available: plotting intensity per scan")
    if errm != "none":
        lines.append(error_text(a, ascii_only=True))
    lines.extend(phase_status(a))
    bad = [r for r in res if r["kind"] == "ON" and r["value"] is None
           and not (fidm and r["fid"]["read"] and r["fid"]["g"] is None)]   # listed by fid_status
    for r in bad[-3:]:
        lines.append("expno %d: %s" % (r["expno"], r["note"]))
    if lines and not p.compact:              # the window shows them above the plot instead
        ax1.set_title("\n".join(lines), loc="left", fontsize=8, color="0.25", family="monospace")

    draw_latest(ax2, a)

    if p.compact:                            # the window: no title either
        p.fit_layout()
        return
    meta = a["meta"]
    status = "running" if a["ended"] is None else a["ended"]
    if fidm:
        what = mode_label(a["mode"], a) + (("; integral: " + window_text(a)) if show_i else "")
    else:
        what = "%s, %s" % (window_text(a), a["mode"])
    fig.suptitle("%s  |  %s  |  %s\n%s  |  %s  |  %d ON, %d OFF  |  %s"
                           % (meta.get("sample", ""), meta.get("conditions", ""),
                              os.path.basename(meta.get("dataset_dir", "")) or os.path.dirname(runpath),
                              run_label(runpath), what,
                              len([q for q in res if q["kind"] == "ON"]), len(offs), status),
                           fontsize=9)
    relayout(fig, 0.05 if p.with_text else 0.0, 0.92)    # bottom 5 %: the reopen command


OFF_COLORS = ["#d68910", "#8e44ad", "#7f8c8d", "#17a2b8", "#2a9d5c", "#1f5fa8"]
D1_LABEL = "D1, build-up time (s)"


def buildup_style(kind, index):
    """(color, marker, marker face) of a build-up series: ON filled circles, OFF open squares."""
    if kind == "ON":
        c = SET_COLORS[index % len(SET_COLORS)]
        return c, "o", c
    return OFF_COLORS[index % len(OFF_COLORS)], "s", "none"


def fit_label(f, name, ascii_only=False):
    """Legend entry of a fitted curve, e.g. 'ON fit, T_B 29.6 s'."""
    P = f["params"]
    if f["model"] == "biexp":
        t = ("T1 %.3g s, T2 %.3g s" if ascii_only else "T₁ %.3g s, T₂ %.3g s") % (P["T_1"][0], P["T_2"][0])
    else:
        t = "T_B %.3g s" % P["T_B"][0]
        if f["model"] == "stretched":
            t += (", beta %.2f" if ascii_only else ", β %.2f") % P["beta"][0]
    return ("%s fit, %s" % (name, t)) if name else ("fit, %s" % t)


def plot_buildup(ax1, ax1b, a, ascii_only=False, ms=5):
    """The build-up series of a with their error bars (if any) and fitted curves, on ax1;
    OFF on ax1b when ON and OFF are both shown and not normalized. Returns (artists, sep,
    view, scales)."""
    view = buildup_view(a["results"], a["error_bars"])
    fits, norm, multi = a["fits"], a["normalize"], a["multi_set"]
    kinds = set(k for k, s in view)
    sep = len(kinds) == 2 and not norm
    xs = [x for v in view.values() for x in v["x"]]
    tt = None
    if xs:
        if a["log_d1"]:
            tt = np.exp(np.linspace(math.log(min(xs) / 2.0), math.log(max(xs) * 1.5), 300))
        else:
            tt = np.linspace(0.0, max(xs) * 1.05, 300)
    arts, scales, count = [], {}, {"ON": 0, "OFF": 0}
    named = multi or len(kinds) > 1 or a["error_bars"] == "repeats"
    for key, v in view.items():
        kind = key[0]
        col, mk, mfc = buildup_style(kind, count[kind])
        count[kind] += 1
        ax = ax1b if (sep and kind == "OFF") else ax1
        f = fits.get(key)
        ok = f is not None and "error" not in f
        scale = 1.0
        if norm:
            if not ok or not f["determined"] or not f["s_inf"]:
                continue                       # nothing to normalize to
            scale = 1.0 / f["s_inf"]
        scales[key] = scale
        name = series_name(key, multi)
        withe = [(x, y, e) for x, y, e in zip(v["x"], v["y"], v["e"]) if e is not None]
        if withe:
            c = ax.errorbar([q[0] for q in withe], [q[1] * scale for q in withe],
                            yerr=[q[2] * scale for q in withe], fmt="none", ecolor=col,
                            elinewidth=0.9, capsize=2.5, zorder=2.5)
            arts += [c.lines[0]] if c.lines[0] is not None else []
            arts += list(c.lines[1]) + list(c.lines[2])
        arts += ax.plot(v["x"], [y * scale for y in v["y"]], ls="none", marker=mk,
                        color=col, mfc=mfc, ms=ms, label=name, zorder=3)
        if ok:
            lab = fit_label(f, name if named else None, ascii_only)
            if not f["determined"]:
                lab = ("%s fit: not determined" % name) if named else "fit: not determined"
            arts += ax.plot(tt, fit_model_value(f["model"], f["p"], tt) * scale,
                            "-" if f["determined"] else "--", color=col, lw=1.1, label=lab, zorder=2)
    return arts, sep, view, scales


def view_point(view, rec):
    """(key, index) of the point of the view that holds the record, or None."""
    for key, v in view.items():
        for i, rs in enumerate(v["recs"]):
            if any(r["expno"] == rec["expno"] for r in rs):
                return key, i
    return None


def buildup_xlim(ax1, a, view):
    """Linear D1 axis from 0, or a log axis around the D1 values."""
    d1 = [x for v in view.values() for x in v["x"]]
    if a["log_d1"] and d1:
        ax1.set_xscale("log")
        ax1.set_xlim(min(d1) / 2.2, max(d1) * 1.6)
        # 0.1, 1, 10 rather than powers of ten (mathtext, which is not text in the EPS)
        ax1.xaxis.set_major_formatter(FuncFormatter(lambda v, pos: "%g" % v))
    elif d1:
        ax1.set_xlim(0.0, max(d1) * 1.07)


def buildup_ylabels(ax1, ax1b, a, view, sep, ascii_only=False):
    unit = "FID(t0) / (NS*RG)" if a["fid_mode"] else "intensity per scan"
    if a["normalize"]:
        ax1.set_ylabel("S / S_inf (fitted)" if ascii_only else "S / S∞ (fitted)")
    elif sep:
        ax1.set_ylabel("ON: " + unit, color=SET_COLORS[0])
        ax1b.set_ylabel("OFF: " + unit, color=OFF_COLORS[0])
    else:
        kinds = sorted(set(k for k, s in view))
        ax1.set_ylabel(unit + (" (%s)" % kinds[0] if len(kinds) == 1 else ""))


def draw_buildup(p, a, runpath):
    """The build-up: intensity against D1 with the fits (ax1, OFF on ax1b if separate), the
    FID phase below it if shown (ax3), and for plot.png the latest spectrum (ax2)."""
    p.layout(a["show_fid_phase"])
    ax1, ax2, ax1b, ax3 = p.ax1, p.ax2, p.ax1b, p.ax3
    fig = p.fig
    if ax1.get_xscale() != "linear":          # a log axis would warn about the limits of clear()
        ax1.set_xscale("linear")
    ax1.clear()
    if ax2 is not None:
        ax2.clear()
    ax1b.clear()
    ax1b.yaxis.tick_right()                    # clear() puts the twin's ticks and label on the left
    ax1b.yaxis.set_label_position("right")
    ax1b.set_visible(False)
    if ax3 is not None:
        ax3.clear()
    res, multi = a["results"], a["multi_set"]
    lines, sep, view, scales = plot_buildup(ax1, ax1b, a)
    allpts = [r for key, v in view.items() if key in scales for rs in v["recs"] for r in rs]
    if allpts:
        if sep:
            ax1b.set_visible(True)
        r = max(allpts, key=lambda q: q["expno"])
        key, i = view_point(view, r)
        ax = ax1b if (sep and key[0] == "OFF") else ax1
        ax.plot([view[key]["x"][i]], [view[key]["y"][i] * scales[key]], "o", color="#c0392b", ms=8,
                mfc="none", mew=1.8, zorder=4)
        h, l = ax1.get_legend_handles_labels()
        if sep:
            h2, l2 = ax1b.get_legend_handles_labels()
            h, l = h + h2, l + l2
        ax1.legend(h, l, fontsize=8, loc="best")
    else:
        ax1.text(0.5, 0.5, "waiting for the first record" if not view else
                 "no fit to normalize to (see the lines above)", transform=ax1.transAxes,
                 ha="center", va="center", color="0.4")
    buildup_ylabels(ax1, ax1b, a, view, sep)
    ax1.axhline(0.0, color="0.6", lw=0.8)
    buildup_xlim(ax1, a, view)
    if ax3 is not None:
        on = [r for r in res if r["d1"] is not None and r["fid"] and r["fid"]["phase_rel"] is not None]
        count = {"ON": 0, "OFF": 0}
        for key in [k for k in buildup_series(res)] or []:
            pts = sorted([r for r in on if (r["kind"], r["set"]) == key], key=lambda q: q["d1"])
            col, mk, mfc = buildup_style(key[0], count[key[0]])
            count[key[0]] += 1
            if pts:
                ax3.plot([r["d1"] for r in pts], [r["fid"]["phase_rel"] for r in pts], ls="none",
                         marker=mk, color=col, mfc=mfc, ms=4)
        if on:
            r = max(on, key=lambda q: q["expno"])
            ax3.plot([r["d1"]], [r["fid"]["phase_rel"]], "o", color="#c0392b", ms=7, mfc="none", mew=1.5)
        else:
            ax3.text(0.5, 0.5, "no FID phase (see the lines above the plot)", transform=ax3.transAxes,
                     ha="center", va="center", color="0.4")
        ax3.axhline(0.0, color="0.6", lw=0.8)
        if p.compact:
            ax3.set_title("FID phase (deg), relative to the median of the ON records", loc="left", fontsize=8)
        else:
            ax3.set_ylabel("FID phase (deg)", fontsize=9)
        ax3.set_xlabel(D1_LABEL)
        ax3.grid(True, color="0.9")
        ax1.tick_params(labelbottom=False)
        fig.align_ylabels([ax1, ax3])
    else:
        ax1.set_xlabel(D1_LABEL)
    ax1.grid(True, color="0.9")

    if p.compact:                            # the window: fit results above the plot, no title
        p.fit_layout()
        return
    lines = ["fit: %s, %s (%s; +/- one standard error)"
             % (FIT_MODELS[a["fit_model"]], FIT_FORMULAS[a["fit_model"]], fit_weight_text(a, True))]
    if a["error_bars"] != "none":
        lines.append(error_text(a, ascii_only=True))
    for key, f in a["fits"].items():
        name = series_name(key, multi)
        lines.append("%s: %s" % (name, ("no fit: " + f["error"]) if "error" in f
                                 else fit_summary(f, ascii_only=True)))
        if "error" not in f:
            lines += ["%s: NOTE: %s" % (name, n) for n in
                      f["notes"] + ([] if f["determined"] else ["not determined: " + f["why"]])]
    for s, r1, r2 in fit_ratios(a):
        lines.append("ON/OFF%s: S_inf ratio %s; max S/sqrt(t) ratio %s"
                     % (" set %d" % s if (multi and s) else "", "-" if r1 is None else "%.4g" % r1,
                        "-" if r2 is None else "%.4g" % r2))
    lines.extend(phase_status(a))
    bad = [r for r in res if r["value"] is None
           and not (a["fid_mode"] and r["fid"]["read"] and r["fid"]["g"] is None)]
    for r in bad[-3:]:
        lines.append("expno %d: %s" % (r["expno"], r["note"]))
    ax1.set_title("\n".join(lines), loc="left", fontsize=8, color="0.25", family="monospace")
    draw_latest(ax2, a)
    meta = a["meta"]
    status = "running" if a["ended"] is None else a["ended"]
    if a["fid_mode"]:
        what = mode_label(a["mode"], a)
    else:
        what = "%s, %s" % (window_text(a), a["mode"])
    fig.suptitle("%s  |  %s  |  %s\n%s  |  build-up, %s  |  %d ON, %d OFF  |  %s"
                 % (meta.get("sample", ""), meta.get("conditions", ""),
                    os.path.basename(meta.get("dataset_dir", "")) or os.path.dirname(runpath),
                    run_label(runpath), what, len([q for q in res if q["kind"] == "ON"]),
                    len([q for q in res if q["kind"] == "OFF"]), status), fontsize=9)
    relayout(fig, 0.05 if p.with_text else 0.0, 0.92)


EPS_RC = {
    "ps.useafm": True,                 # text as text in the standard PostScript fonts (Helvetica),
    "font.family": "sans-serif",       # editable in Illustrator; nothing embedded
    "font.sans-serif": ["Helvetica"],
    "font.size": 9,
    "axes.unicode_minus": False,       # '-' (Helvetica has no Unicode minus in matplotlib's metrics)
    "axes.linewidth": 0.8,
}


# PostScript glyph names of printable ASCII in Helvetica's standard encoding (' and ` are
# excluded: the standard encoding has curly quotes there)
PS_CHARS = dict(zip(
    "space exclam quotedbl numbersign dollar percent ampersand parenleft parenright asterisk plus "
    "comma hyphen period slash zero one two three four five six seven eight nine colon semicolon "
    "less equal greater question at bracketleft backslash bracketright asciicircum underscore "
    "braceleft bar braceright asciitilde".split(),
    " !\"#$%&()*+,-./0123456789:;<=>?@[\\]^_{|}~"))
PS_CHARS.update((c, c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def eps_for_illustrator(ps):
    """matplotlib writes text one glyph at a time (x y m /name glyphshow), which Illustrator
    turns into one text object per character; this writes each label as one string
    instead (x y m (text) show; labels with other characters stay as they are), and
    leaves out the clip around the whole page (matplotlib 3.3)."""
    glyph = re.compile(r"^\s*(-?[\d.]+) (-?[\d.]+) m /(\w+) glyphshow\s*$")
    out, run = [], []                         # run: (line, x, y, glyph name)

    def flush():
        if run:
            chars = [PS_CHARS.get(g[3]) for g in run]
            if None in chars or len(set(g[2] for g in run)) > 1:
                out.extend(g[0] for g in run)
            else:
                s = "".join(chars).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                out.append("%s %s m (%s) show" % (run[0][1], run[0][2], s))
            del run[:]
    for line in ps.split("\n"):
        m = glyph.match(line)
        if m:
            run.append((line, m.group(1), m.group(2), m.group(3)))
            continue
        flush()
        if re.match(r"^[\d.]+ [\d.]+ 0 0 clipbox$", line.strip()):
            continue
        out.append(line)
    flush()
    return "\n".join(out)


EPS_WIDTH = 7.0     # in: full page width (two columns) of ACS journals; Elsevier's is 190 mm


def write_profile_eps(path, a, aspect=None):
    """The frequency profile as EPS for editing in Adobe Illustrator: the profile (and the
    window integral and the FID phase when they are shown), without the lines above the
    plot, the grid or the marker of the latest record. Each trace is one path and each
    marker its own path; the data are not clipped to the axes (no clipping masks); the
    text is Helvetica text. The axes span the whole profile. Width EPS_WIDTH; height
    EPS_WIDTH * aspect (height/width of the profile in the window), 2 to 5 in."""
    if a.get("buildup"):
        return write_buildup_eps(path, a, aspect)
    from matplotlib.backends.backend_ps import FigureCanvasPS
    on = [r for r in a["results"] if r["kind"] == "ON" and r["y"] is not None and r["freq"] is not None]
    if not on:
        raise ValueError("no ON record with a value yet")
    multi, show_i, fidm = a["multi_set"], a["show_integral"], a["fid_mode"]
    with_ph = a["show_fid_phase"] and any(r["fid"] and r["fid"]["phase_rel"] is not None for r in on)
    with matplotlib.rc_context(EPS_RC):
        h = min(5.0, max(2.0, EPS_WIDTH * aspect)) if aspect else (4.4 if with_ph else 3.2)
        fig = Figure(figsize=(EPS_WIDTH, h))
        FigureCanvasPS(fig)
        if with_ph:
            gs = fig.add_gridspec(2, 1, height_ratios=[2.6, 1])
            ax1 = fig.add_subplot(gs[0, 0])
            ax3 = fig.add_subplot(gs[1, 0], sharex=ax1)
        else:
            ax1, ax3 = fig.add_subplot(111), None
        ax_i = ax1.twinx() if show_i and not a["use_enh"] else ax1
        lines = []
        errm = a.get("error_bars", "none")
        if errm == "repeats":
            lines += draw_profile_repeats(ax1, ax_i, a, ms=4, lw=1.0, latest=False)
            ax1.get_legend().remove()
        for i, s in enumerate(sorted(set(r["set"] for r in on)) if errm != "repeats" else []):
            col = SET_COLORS[i % len(SET_COLORS)]
            pts = sorted([r for r in on if r["set"] == s], key=lambda r: r["freq"])
            name = ("FID(t0)" if fidm else "peak") if show_i else None
            label = (("set %d, %s" % (s, name)) if name else ("set %d" % s)) if multi else name
            lines += ax1.plot([r["freq"] for r in pts], [r["y"] for r in pts], "-o", color=col,
                              ms=4, lw=1.0, label=label)
            if errm == "noise":
                lines += error_bars(ax1, pts, "freq", "y", "ey", col, lw=0.8)
            if show_i:
                ip = [r for r in pts if r.get("yi") is not None]
                lines += ax_i.plot([r["freq"] for r in ip], [r["yi"] for r in ip], "--s", color=col, mfc="none",
                                   ms=4, lw=0.8, label=("set %d, integral" % s) if multi else "integral")
                if errm == "noise":
                    lines += error_bars(ax_i, ip, "freq", "yi", "eyi", col, lw=0.8)
            if ax3 is not None:
                pp = [r for r in pts if r["fid"] and r["fid"]["phase_rel"] is not None]
                lines += ax3.plot([r["freq"] for r in pp], [r["fid"]["phase_rel"] for r in pp], "-o",
                                  color=col, ms=3, lw=0.8)
        if a["use_enh"]:
            lines.append(ax1.axhline(0.0, color="0.6", lw=0.6, zorder=0))
            ax1.set_ylabel("FID(t0)_on / FID(t0)_off - 1" if fidm else "I_on / I_off - 1")
        else:
            ax1.set_ylabel("FID(t0) / (NS*RG) (a.u.)" if fidm else "intensity per scan (a.u.)")
        if ax_i is not ax1:
            ax_i.set_ylabel("integral per scan (a.u. x ppm)")
        if multi or show_i or errm == "repeats":
            h, l = ax1.get_legend_handles_labels()
            if ax_i is not ax1:
                h2, l2 = ax_i.get_legend_handles_labels()
                h, l = h + h2, l + l2
            ax1.legend(h, l, fontsize=8, frameon=False, loc="best")
        ax1.ticklabel_format(axis="x", useOffset=False)
        ax1.xaxis.set_major_locator(MaxNLocator(nbins=8))     # frequencies have 6-7 characters
        if ax3 is not None:
            lines.append(ax3.axhline(0.0, color="0.6", lw=0.6, zorder=0))
            ax3.set_ylabel("FID phase (deg)")
            ax3.set_xlabel("mm-wave frequency (GHz)")
            ax1.tick_params(labelbottom=False)
        else:
            ax1.set_xlabel("mm-wave frequency (GHz)")
        for ln in lines:
            ln.set_clip_on(False)
        fig.tight_layout()
        tmp = path + ".tmp"
        fig.savefig(tmp, format="eps")
    with open(tmp, encoding="latin-1") as fh:
        ps = fh.read()
    with open(tmp, "w", encoding="latin-1") as fh:
        fh.write(eps_for_illustrator(ps))
    os.replace(tmp, path)


def save_eps_for_illustrator(fig, path):
    tmp = path + ".tmp"
    fig.savefig(tmp, format="eps")
    with open(tmp, encoding="latin-1") as fh:
        ps = fh.read()
    with open(tmp, "w", encoding="latin-1") as fh:
        fh.write(eps_for_illustrator(ps))
    os.replace(tmp, path)


def write_buildup_eps(path, a, aspect=None):
    """The build-up as shown (data, fitted curves, the FID phase if shown, OFF on its own axis
    or normalized, linear or log D1), for Adobe Illustrator as write_profile_eps: Helvetica
    text, one path per curve and per marker, nothing clipped; EPS_WIDTH wide."""
    from matplotlib.backends.backend_ps import FigureCanvasPS
    if not buildup_series(a["results"]):
        raise ValueError("no record with a value yet")
    pts = [r for r in a["results"] if r["d1"] is not None and r["fid"] and r["fid"]["phase_rel"] is not None]
    with_ph = a["show_fid_phase"] and bool(pts)
    with matplotlib.rc_context(EPS_RC):
        h = min(5.0, max(2.0, EPS_WIDTH * aspect)) if aspect else (4.4 if with_ph else 3.2)
        fig = Figure(figsize=(EPS_WIDTH, h))
        FigureCanvasPS(fig)
        if with_ph:
            gs = fig.add_gridspec(2, 1, height_ratios=[2.6, 1])
            ax1 = fig.add_subplot(gs[0, 0])
            ax3 = fig.add_subplot(gs[1, 0], sharex=ax1)
        else:
            ax1, ax3 = fig.add_subplot(111), None
        ax1b = ax1.twinx()
        lines, sep, view, scales = plot_buildup(ax1, ax1b, a, ascii_only=True, ms=4)
        if not sep:
            fig.delaxes(ax1b)
        buildup_ylabels(ax1, ax1b, a, view, sep, ascii_only=True)
        lines.append(ax1.axhline(0.0, color="0.6", lw=0.6, zorder=0))
        h_, l_ = ax1.get_legend_handles_labels()
        if sep:
            h2, l2 = ax1b.get_legend_handles_labels()
            h_, l_ = h_ + h2, l_ + l2
        ax1.legend(h_, l_, fontsize=8, frameon=False, loc="best")
        buildup_xlim(ax1, a, view)
        if ax3 is not None:
            count = {"ON": 0, "OFF": 0}
            for key in buildup_series(a["results"]):
                col, mk, mfc = buildup_style(key[0], count[key[0]])
                count[key[0]] += 1
                pp = sorted([r for r in pts if (r["kind"], r["set"]) == key], key=lambda q: q["d1"])
                if pp:
                    lines += ax3.plot([r["d1"] for r in pp], [r["fid"]["phase_rel"] for r in pp], ls="none",
                                      marker=mk, color=col, mfc=mfc, ms=3)
            lines.append(ax3.axhline(0.0, color="0.6", lw=0.6, zorder=0))
            ax3.set_ylabel("FID phase (deg)")
            ax3.set_xlabel(D1_LABEL)
            ax1.tick_params(labelbottom=False)
        else:
            ax1.set_xlabel(D1_LABEL)
        for ln in lines:
            ln.set_clip_on(False)
        fig.tight_layout()
        save_eps_for_illustrator(fig, path)


def relayout(fig, bottom=0.0, top=1.0):
    """tight_layout from the default margins, so that a redraw (or a resized window) is laid
    out exactly as a new figure is."""
    fig.subplots_adjust(**dict((k, matplotlib.rcParams["figure.subplot." + k])
                               for k in ("left", "right", "bottom", "top", "wspace", "hspace")))
    with warnings.catch_warnings():          # axes too small for the labels: keep what fits
        warnings.simplefilter("ignore")
        fig.tight_layout(rect=(0, bottom, 1, top))


def reopen_command(runpath, args):
    """Terminal command that opens this viewer on this run file again."""
    exe = sys.executable or "python3"
    short = os.path.basename(exe)
    found = shutil.which(short)
    if found and os.path.realpath(found) == os.path.realpath(exe):
        exe = short             # e.g. 'python3' instead of '/usr/bin/python3'
    words = [exe, os.path.abspath(__file__), runpath]
    if args.ppm is not None:
        words += ["--ppm", "%g" % args.ppm]
    if args.width is not None:
        words += ["--width", "%g" % args.width]
    if args.mode is not None:
        words += ["--mode", args.mode]
    if getattr(args, "csv", False):
        words.append("--csv")
    return " ".join(shlex.quote(w) for w in words)


def signature(runpath, a):
    """Changes whenever the run file, the phase settings or any spectrum changes."""
    sig = [os.path.getmtime(runpath), phase_key(a["phase"])]
    for r in a["results"]:
        sig.append((r["expno"], r["value"], r["integral"], r["note"], r["files"],
                    None if r["fid"] is None else (r["fid"]["phase_rel"], r["fid"]["mean"])))
    return tuple(sig)


def update_outputs(p, a, runpath, png, tsv, analyzer=None, args=None):
    """Draws, writes the PNG and the TSV, and with --csv the CSV."""
    draw(p, a, runpath)
    p.fig.savefig(png, dpi=110)
    write_tsv(tsv, a)
    if analyzer is not None and getattr(args, "csv", False):
        analyzer.write_csv(csv_path(runpath), a)


# --------------------------------------------------------------------------
# Without a window
# --------------------------------------------------------------------------
def run_files_only(runpath, args, analyzer, reopen, png, tsv):
    p = Panels(reopen)
    FigureCanvasAgg(p.fig)
    last = None
    while True:
        a = None
        try:
            analyzer.load_phase()
            a = analyzer.run(force_fid=getattr(args, "csv", False))
            sig = signature(runpath, a)
            if sig != last:
                update_outputs(p, a, runpath, png, tsv, analyzer, args)
                last = sig
        except Exception as ex:  # keep going through a transient read error
            print("[%s] update failed: %s" % (time.strftime("%H:%M:%S"), ex))
            sys.stdout.flush()
        if args.once or (a is not None and a["ended"] is not None):
            break
        time.sleep(args.interval)


# --------------------------------------------------------------------------
# Window
# --------------------------------------------------------------------------
def record_label(r, multi):
    s = "%d   " % r["expno"]
    if multi:
        s += "set %d   " % r["set"]
    if r.get("d1") is not None:
        s += "%s  D1 %g s" % (r["kind"], r["d1"])
    elif r["kind"] == "ON" and r["freq"] is not None:
        s += "ON %.3f GHz" % r["freq"]
    else:
        s += "%s %s" % (r["kind"], r["label"])
    return s


HINT_FG = "#666666"       # hints next to controls
ERROR_FG = "#8a1c1c"
OK_FG = "#1e6b33"
PENDING_FG = "#b9770e"
MODE_HELP = {
    "extreme": "largest |value| in the window, sign kept",
    "max": "largest value in the window",
    "sum": "sum of the points in the window",
    FID_MODE: "start of the raw FID (no window)",
}
# Size and position of the last window closed, and the share of the width for the profile
WINDOW_FILE = os.path.join(os.path.expanduser("~"), ".config", "fs_plot", "window.txt")
DEFAULT_SIZE = "1270x740"
PROFILE_FRACTION = 0.55
STATE_COLORS = {"running": "#d0021b", "stale": "#d68910", "complete": "#7f8c8d", "stopped": "#c0392b"}


def load_window_state():
    """Saved by the last viewer window that was closed: geometry (or None), the share of
    the width for the profile, and whether the spectrum side was shown."""
    st = {"geometry": None, "profile_fraction": PROFILE_FRACTION, "spectrum": True}
    try:
        with open(WINDOW_FILE) as fh:
            for line in fh:
                m = re.match(r"(\w+)\s*=\s*(\S+)$", line.strip())
                if not m:
                    continue
                k, v = m.groups()
                if k == "geometry" and re.match(r"^\d+x\d+\+-?\d+\+-?\d+$", v):
                    st["geometry"] = v
                elif k == "profile_fraction":
                    st["profile_fraction"] = min(0.85, max(0.15, float(v)))
                elif k == "spectrum":
                    st["spectrum"] = v != "0"
    except Exception:
        pass
    return st


def save_window_state(geometry, frac, spectrum):
    try:
        d = os.path.dirname(WINDOW_FILE)
        if not os.path.isdir(d):
            os.makedirs(d)
        tmp = WINDOW_FILE + ".tmp"
        with open(tmp, "w") as fh:
            fh.write("# size and position of the last fs_plot.py window that was closed\n"
                     "geometry = %s\nprofile_fraction = %.3f\nspectrum = %d\n"
                     % (geometry, frac, 1 if spectrum else 0))
        os.replace(tmp, WINDOW_FILE)
    except Exception as ex:
        print("[%s] could not save the window position in %s: %s" % (time.strftime("%H:%M:%S"), WINDOW_FILE, ex))
        sys.stdout.flush()


class InfoPanel:
    """Rows 'key   value', the values wrapped to the width of the panel; warnings in red."""

    def __init__(self, parent, key_width=9):
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(1, weight=1)
        self.key_width = key_width
        self.rows = []
        self.wrap = 300
        self.frame.bind("<Configure>", self.on_resize)

    def set(self, items):
        """items: [(key, text, warn)]."""
        while len(self.rows) < len(items):
            k = ttk.Label(self.frame, width=self.key_width, foreground=HINT_FG, anchor="nw")
            v = ttk.Label(self.frame, justify=tk.LEFT, anchor="nw", wraplength=self.wrap)
            self.rows.append((k, v))
        for i, (k, v) in enumerate(self.rows):
            if i < len(items):
                key, text, warn = items[i]
                k.configure(text=key, foreground=ERROR_FG if warn else HINT_FG)
                v.configure(text=text, foreground=ERROR_FG if warn else "#222222")
                k.grid(row=i, column=0, sticky="nw")
                v.grid(row=i, column=1, sticky="nw")
            else:
                k.grid_remove()
                v.grid_remove()

    def on_resize(self, event):
        wrap = max(150, event.width - self.key_width * 8 - 12)
        if abs(wrap - self.wrap) > 4:
            self.wrap = wrap
            for _, v in self.rows:
                v.configure(wraplength=wrap)


class MainWindow:
    """The profile on the left and the spectrum side on the right, with a draggable divider;
    the controls of the spectrum side in a strip along the bottom. 'Hide spectrum' leaves
    the profile alone across the window."""

    def __init__(self, runpath, args, analyzer, reopen, png, tsv):
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        self.FigureCanvas, self.Toolbar = FigureCanvasTkAgg, NavigationToolbar2Tk
        self.runpath, self.args, self.analyzer = runpath, args, analyzer
        self.png, self.tsv = png, tsv
        self.last_sig = None
        self.last_a = None
        self.labels, self.expnos = [], []
        self.user_expno = None          # record chosen by the user; None: the latest
        self.after_id = None
        self.blink_id = None
        self.controls_shown = True
        self.spectrum_shown = True
        self.first_refresh = True
        self.seen_running = False       # the run was seen without its end line
        self.state = {"kind": "running", "title": "", "detail": ""}
        self.updated = None             # time of the last refresh
        self.blink_on = True

        try:
            self.buildup = read_run(runpath)[0].get("type") == "buildup"
        except Exception:
            self.buildup = False
        self.root = tk.Tk()
        self.root.title("fs_plot - %s  |  %s" % (run_label(runpath), reopen))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        saved = load_window_state()
        self.profile_frac = saved["profile_fraction"]
        self.root.geometry(self.checked_geometry(saved["geometry"]))
        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold")
        self.bold = bold

        # Top bar: reopen command | also plot | export | spectrum side; messages below it
        bar = ttk.Frame(self.root)
        bar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(4, 2))
        self.bar = bar
        ttk.Label(bar, text="Reopen:").pack(side=tk.LEFT, padx=(4, 4))
        self.reopen_entry = ttk.Entry(bar, width=12)     # grows with the window
        self.reopen_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.reopen_entry.insert(0, reopen)
        self.reopen_entry.configure(state="readonly")
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=2)
        ttk.Label(bar, text="Also plot:").pack(side=tk.LEFT)
        self.int_var = tk.IntVar(value=0)
        if not self.buildup:                     # build-ups: the integral is not plotted
            ttk.Checkbutton(bar, text="window integral", variable=self.int_var,
                            command=self.on_integral).pack(side=tk.LEFT, padx=(6, 0))
        self.fph_var = tk.IntVar(value=0)
        ttk.Checkbutton(bar, text="FID phase", variable=self.fph_var,
                        command=self.on_fid_phase).pack(side=tk.LEFT, padx=(10 if not self.buildup else 6, 0))
        if self.buildup:                         # fit model and axes of the build-up
            ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=2)
            ttk.Label(bar, text="Fit:").pack(side=tk.LEFT)
            self.fit_combo = ttk.Combobox(bar, state="readonly", width=10, values=[FIT_SHORT[k] for k in FIT_MODELS])
            self.fit_combo.pack(side=tk.LEFT, padx=(6, 0))
            self.fit_combo.current(0)
            self.fit_combo.bind("<<ComboboxSelected>>", self.on_fit_model)
            self.logd1_var = tk.IntVar(value=0)
            ttk.Checkbutton(bar, text="log D1", variable=self.logd1_var,
                            command=self.on_buildup_axes).pack(side=tk.LEFT, padx=(8, 0))
            self.norm_var = tk.IntVar(value=0)
            ttk.Checkbutton(bar, text="normalized", variable=self.norm_var,
                            command=self.on_buildup_axes).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=2)
        ttk.Label(bar, text="Error bars:").pack(side=tk.LEFT)
        self.err_combo = ttk.Combobox(bar, state="readonly", width=10, values=list(ERROR_MODES.values()))
        self.err_combo.pack(side=tk.LEFT, padx=(6, 0))
        self.err_combo.current(0)
        self.err_combo.bind("<<ComboboxSelected>>", self.on_error_mode)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=2)
        ttk.Label(bar, text="Export:").pack(side=tk.LEFT)
        ttk.Button(bar, text="Build-up EPS" if self.buildup else "Profile EPS",
                   command=self.save_eps).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(bar, text="CSV", width=5, command=self.export_csv).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=2)
        self.spec_btn = ttk.Button(bar, text="Hide spectrum", width=13, command=self.toggle_spectrum)
        self.spec_btn.pack(side=tk.LEFT, padx=(0, 2))
        self.msg = tk.StringVar(value="")
        self.msg_label = ttk.Label(self.root, textvariable=self.msg, foreground=ERROR_FG)
        self.msg_shown = False

        # Error bars: a row below the bar while they are shown
        er = ttk.Frame(self.root)
        self.errrow, self.errrow_shown = er, False
        self.err_text = ttk.Label(er, text="")
        self.err_text.pack(side=tk.LEFT, padx=(8, 8))
        self.noise_box = ttk.Frame(er)
        ttk.Label(self.noise_box, text="noise from").pack(side=tk.LEFT)
        self.noise_from = ttk.Entry(self.noise_box, width=7)
        self.noise_from.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(self.noise_box, text="to").pack(side=tk.LEFT, padx=(4, 0))
        self.noise_to = ttk.Entry(self.noise_box, width=7)
        self.noise_to.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(self.noise_box, text="ppm (empty: outside the intensity window, peaks excluded)",
                  foreground=HINT_FG).pack(side=tk.LEFT, padx=(4, 0))
        for e in (self.noise_from, self.noise_to):
            for ev in ("<Return>", "<KP_Enter>", "<FocusOut>"):
                e.bind(ev, lambda event: self.on_noise_region())
        self.fitsig_var = tk.IntVar(value=0)
        self.fitsig_cb = ttk.Checkbutton(er, text="weight the fits by 1/σ²", variable=self.fitsig_var,
                                         command=self.on_fit_sigma)

        # Bottom: the controls of the spectrum side (packed before the plots, so that they
        # keep their height when the window is made smaller)
        self.ctl = ttk.Frame(self.root)
        self.ctl.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(2, 6))
        # Middle: profile | spectrum side
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        left, self.right = ttk.Frame(self.paned), ttk.Frame(self.paned)
        self.paned.add(left, weight=55)
        self.paned.add(self.right, weight=45)

        # Profile side: run status | information | profile
        st = ttk.Frame(left)
        st.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(4, 0))
        self.status_row = st
        bg = ttk.Style().lookup("TFrame", "background") or "#d9d9d9"
        self.dot = tk.Canvas(st, width=14, height=14, highlightthickness=0, bg=bg)
        self.dot_item = self.dot.create_oval(2, 2, 12, 12, fill=STATE_COLORS["running"], outline="")
        self.dot.pack(side=tk.LEFT)
        self.dot_bg = bg
        ttk.Button(st, text="Refresh", width=8, command=self.manual_refresh).pack(side=tk.RIGHT)
        self.live_var = tk.IntVar(value=1)
        ttk.Checkbutton(st, text="Live (every %g s)" % self.args.interval, variable=self.live_var,
                        command=self.on_live).pack(side=tk.RIGHT, padx=(0, 6))
        self.state_title = ttk.Label(st, text="", font=bold)
        self.state_title.pack(side=tk.LEFT, padx=(6, 8))
        self.state_detail = ttk.Label(st, text="", justify=tk.LEFT)
        self.state_detail.pack(side=tk.LEFT, fill=tk.X, expand=True)
        st.bind("<Configure>", lambda e: self.wrap_state())
        self.info = InfoPanel(left)
        self.info.frame.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(2, 0))

        self.p_png = Panels(reopen)          # plot.png, as without the window (not shown)
        FigureCanvasAgg(self.p_png.fig)
        self.p = Panels(None, with_right=False, figsize=(7.0, 4.0), compact=True)
        self.canvas = FigureCanvasTkAgg(self.p.fig, master=left)
        tbf = ttk.Frame(left)
        tbf.pack(side=tk.BOTTOM, fill=tk.X)
        self.toolbar = NavigationToolbar2Tk(self.canvas, tbf)
        self.toolbar.update()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect("button_press_event", self.on_click)
        self.canvas.mpl_connect("resize_event", lambda e: self.p.fit_layout())

        self.spec = SpectrumPane(self, self.right, self.ctl)
        self.combo = self.spec.combo
        self.root.bind("<Prior>", lambda e: self.spectrum_shown and self.spec.step(-1))
        self.root.bind("<Next>", lambda e: self.spectrum_shown and self.spec.step(1))
        if not saved["spectrum"]:
            self.set_spectrum_shown(False)

    def checked_geometry(self, geo):
        """The saved geometry; only its size if its position is off the screen(s)."""
        if geo is None:
            return DEFAULT_SIZE
        m = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", geo)
        w, x, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
        if -w + 100 < x < self.root.winfo_screenwidth() - 100 and -20 < y < self.root.winfo_screenheight() - 100:
            return geo
        return "%sx%s" % (m.group(1), m.group(2))

    # -- main loop ---------------------------------------------------------
    def run(self):
        self.after_id = self.root.after(10, self.refresh)
        self.root.after(150, self.place_divider)
        self.blink_id = self.root.after(600, self.blink)
        self.root.mainloop()

    def place_divider(self):
        if not self.spectrum_shown:
            return
        self.root.update_idletasks()
        w = self.paned.winfo_width()
        if w > 100:
            self.paned.sashpos(0, int(w * self.profile_frac))

    def remember_divider(self):
        if self.spectrum_shown:
            w = self.paned.winfo_width()
            if w > 100:
                self.profile_frac = min(0.85, max(0.15, self.paned.sashpos(0) / float(w)))

    def close(self):
        try:
            self.remember_divider()
            save_window_state(self.root.wm_geometry(), self.profile_frac, self.spectrum_shown)
        except Exception:
            pass
        for aid in (self.after_id, self.blink_id):
            if aid is not None:
                try:
                    self.root.after_cancel(aid)
                except Exception:
                    pass
        self.root.quit()
        self.root.destroy()

    def set_msg(self, text, error=True):
        """Shows text in the line below the bar (hidden while empty)."""
        self.msg.set(text)
        self.msg_label.configure(foreground=ERROR_FG if error else OK_FG)
        if text and not self.msg_shown:
            self.msg_label.pack(side=tk.TOP, anchor="w", padx=8, after=self.bar)
            self.msg_shown = True
        elif not text and self.msg_shown:
            self.msg_label.pack_forget()
            self.msg_shown = False

    # -- spectrum side and controls --------------------------------------------
    def toggle_spectrum(self):
        self.set_spectrum_shown(not self.spectrum_shown)

    def set_spectrum_shown(self, show):
        if show == self.spectrum_shown:
            return
        if show:
            self.paned.add(self.right, weight=45)
            if self.controls_shown:
                self.ctl.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(2, 6), before=self.paned)
            self.spec_btn.configure(text="Hide spectrum")
            self.spectrum_shown = True
            self.root.after(50, self.place_divider)
        else:
            self.remember_divider()
            self.paned.forget(self.right)
            self.ctl.pack_forget()
            self.spec_btn.configure(text="Show spectrum")
            self.spectrum_shown = False

    def toggle_controls(self):
        if self.controls_shown:
            self.ctl.pack_forget()
        elif self.spectrum_shown:
            self.ctl.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(2, 6), before=self.paned)
        self.controls_shown = not self.controls_shown
        self.spec.ctl_btn.configure(text="Hide controls" if self.controls_shown else "Show controls")

    # -- updates -------------------------------------------------------------
    def cancel_refresh(self):
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def on_live(self):
        self.cancel_refresh()
        if self.live_var.get():
            self.refresh()
        else:
            self.show_state()

    def manual_refresh(self):
        self.refresh(reschedule=False)

    def refresh(self, reschedule=True):
        try:
            phase_changed = self.analyzer.load_phase()
            a = self.analyzer.run(force_fid=getattr(self.args, "csv", False))
            self.last_a = a
            self.updated = time.time()
            sig = signature(self.runpath, a)
            if sig != self.last_sig:
                update_outputs(self.p_png, a, self.runpath, self.png, self.tsv, self.analyzer, self.args)
                layout = self.p.show_phase
                draw(self.p, a, self.runpath)
                if self.p.show_phase != layout:
                    self.toolbar.update()          # new axes: clear the zoom history
                self.canvas.draw_idle()
                self.info.set(buildup_info(a, self.runpath) if a["buildup"] else profile_info(a, self.runpath))
                self.last_sig = sig
            self.update_records(a)
            self.int_var.set(1 if self.analyzer.phase.get("show_integral") else 0)
            self.fph_var.set(1 if self.analyzer.phase.get("show_fid_phase") else 0)
            ph = self.analyzer.phase
            self.err_combo.current(list(ERROR_MODES).index(ph.get("error_bars", "none")))
            self.fitsig_var.set(1 if ph.get("fit_sigma") else 0)
            focus = self.root.focus_get()
            for e, k in ((self.noise_from, "noise_from"), (self.noise_to, "noise_to")):
                if e is not focus:
                    e.delete(0, tk.END)
                    if ph.get(k) is not None:
                        e.insert(0, "%g" % ph[k])
            self.update_errrow()
            if self.buildup:
                ph = self.analyzer.phase
                self.fit_combo.current(list(FIT_MODELS).index(ph.get("fit_model", "mono")))
                self.logd1_var.set(1 if ph.get("log_d1") else 0)
                self.norm_var.set(1 if ph.get("normalize") else 0)
            self.spec.sync(a, phase_changed == "proc", self.selected_row())
            # Live: off from the start for a run that has ended; off when the run ends
            if a["ended"] is None:
                self.seen_running = True
            elif self.live_var.get() and (self.first_refresh or self.seen_running):
                self.live_var.set(0)
                self.seen_running = False
                self.cancel_refresh()
                reschedule = False
            self.first_refresh = False
            self.show_state()
        except Exception as ex:  # keep the window alive through a transient read error
            print("[%s] update failed: %s" % (time.strftime("%H:%M:%S"), ex))
            sys.stdout.flush()
        if reschedule and self.live_var.get():
            self.cancel_refresh()
            self.after_id = self.root.after(int(self.args.interval * 1000), self.refresh)

    def show_state(self):
        """The status row: dot, title and detail of the run."""
        if self.last_a is None:
            return
        st = run_state(self.last_a)
        detail = st["detail"]
        if self.updated is not None:
            if st["kind"] in ("running", "stale") and not self.live_var.get():
                detail += " · Live is off: not updated since %s" % time.strftime("%H:%M:%S", time.localtime(self.updated))
            else:
                detail += " · updated %s" % time.strftime("%H:%M:%S", time.localtime(self.updated))
        self.state = st
        color = STATE_COLORS[st["kind"]]
        self.state_title.configure(text=st["title"], foreground=color if st["kind"] != "complete" else "#222222")
        self.state_detail.configure(text=detail, foreground=ERROR_FG if st["kind"] == "stopped" else "#222222")
        self.dot.itemconfigure(self.dot_item, fill=color)
        self.wrap_state()

    def wrap_state(self):
        """Wraps the detail of the status row to the room left by the other widgets."""
        st = self.status_row
        used = sum(w.winfo_reqwidth() for w in st.winfo_children() if w is not self.state_detail) + 40
        self.state_detail.configure(wraplength=max(150, st.winfo_width() - used))

    def blink(self):
        """The red dot blinks while the run is going and the window is live."""
        if self.state["kind"] == "running" and self.live_var.get():
            self.blink_on = not self.blink_on
            self.dot.itemconfigure(self.dot_item,
                                   fill=STATE_COLORS["running"] if self.blink_on else self.dot_bg)
        elif not self.blink_on:
            self.blink_on = True
            self.dot.itemconfigure(self.dot_item, fill=STATE_COLORS[self.state["kind"]])
        self.blink_id = self.root.after(600, self.blink)

    # -- record list --------------------------------------------------------
    def update_records(self, a):
        """The list holds the records with a spectrum; it shows the record chosen by the
        user, or the latest one while the spectrum side follows the latest record."""
        rows = [r for r in a["results"] if r["readable"]]
        labels = [record_label(r, a["multi_set"]) for r in rows]
        expnos = [r["expno"] for r in rows]
        if labels != self.labels:
            self.labels, self.expnos = labels, expnos
            self.combo["values"] = labels
        if not expnos:
            self.combo.configure(state="disabled")
            return
        self.combo.configure(state="readonly")
        want = self.user_expno if self.user_expno in expnos else expnos[-1]
        i = expnos.index(want)
        if self.combo.current() != i:
            self.combo.current(i)

    def selected_row(self):
        i = self.combo.current()
        if i < 0 or i >= len(self.expnos) or self.last_a is None:
            return None
        for r in self.last_a["results"]:
            if r["expno"] == self.expnos[i]:
                return r
        return None

    def show_record(self, expno):
        """Shows expno on the spectrum side (shown if hidden), which stops following the
        latest record. Returns False if the expno has no spectrum."""
        if expno not in self.expnos:
            return False
        self.user_expno = expno
        self.spec.follow_var.set(0)
        i = self.expnos.index(expno)
        if self.combo.current() != i:
            self.combo.current(i)
        r = self.selected_row()
        if r is None:
            return False
        self.set_spectrum_shown(True)
        self.spec.show(r)
        return True

    def on_select(self, event=None):
        r = self.selected_row()
        if r is not None:
            self.show_record(r["expno"])

    def on_click(self, event):
        """Left click near a point of the profile (or of the FID phase): shows that record."""
        a, p = self.last_a, self.p
        if a is None or event.button != 1 or getattr(self.toolbar, "mode", "") != "":
            return
        if a["buildup"]:
            return self.on_click_buildup(event)
        if a["error_bars"] == "repeats" and event.inaxes in (p.ax1, p.ax1b):
            g, gi = profile_means(a)
            best, dmin = None, 30.0
            for groups, ax in ((g, p.ax1), (gi, p.ax1 if a["use_enh"] else p.ax1b)):
                for q in groups:
                    xp, yp = ax.transData.transform((q["x"], q["y"]))
                    d = math.hypot(xp - event.x, yp - event.y)
                    if d < dmin:
                        best, dmin = max(q["recs"], key=lambda r: r["expno"]), d
            if best is not None and not self.show_record(best["expno"]):
                self.set_msg("expno %d has no processed spectrum to show" % best["expno"])
            return
        if event.inaxes in (p.ax1, p.ax1b):
            targets = [(p.ax1, "y")]
            if a["show_integral"]:
                targets.append((p.ax1 if a["use_enh"] else p.ax1b, "yi"))
        elif p.ax3 is not None and event.inaxes is p.ax3:
            targets = [(p.ax3, "phase")]
        else:
            return
        best, dmin = None, 30.0                # pixels
        for r in a["results"]:
            if r["kind"] != "ON" or r["freq"] is None:
                continue
            for ax, key in targets:
                y = (r["fid"] or {}).get("phase_rel") if key == "phase" else r.get(key)
                if y is None:
                    continue
                xp, yp = ax.transData.transform((r["freq"], y))
                d = math.hypot(xp - event.x, yp - event.y)
                if d < dmin:
                    best, dmin = r, d
        if best is not None and not self.show_record(best["expno"]):
            self.set_msg("expno %d has no processed spectrum to show" % best["expno"])

    # -- display settings and export -----------------------------------------
    def on_integral(self):
        self.set_msg(self.analyzer.set_display(show_integral=bool(self.int_var.get())))
        self.refresh(reschedule=False)

    def on_click_buildup(self, event):
        """Left click near a point of the build-up (or of the FID phase): shows that record."""
        a, p = self.last_a, self.p
        if event.inaxes not in (p.ax1, p.ax1b) and not (p.ax3 is not None and event.inaxes is p.ax3):
            return
        best, dmin = None, 30.0                # pixels
        if p.ax3 is not None and event.inaxes is p.ax3:
            for r in a["results"]:
                y = (r["fid"] or {}).get("phase_rel")
                if y is None or r["d1"] is None:
                    continue
                xp, yp = p.ax3.transData.transform((r["d1"], y))
                d = math.hypot(xp - event.x, yp - event.y)
                if d < dmin:
                    best, dmin = r, d
        else:
            view = buildup_view(a["results"], a["error_bars"])
            sep = len(set(k for k, s in view)) == 2 and not a["normalize"]
            for key, v in view.items():
                f = a["fits"].get(key)
                scale = 1.0
                if a["normalize"]:
                    if f is None or "error" in f or not f["determined"] or not f["s_inf"]:
                        continue
                    scale = 1.0 / f["s_inf"]
                ax = p.ax1b if sep and key[0] == "OFF" else p.ax1
                for x, y, rs in zip(v["x"], v["y"], v["recs"]):
                    xp, yp = ax.transData.transform((x, y * scale))
                    d = math.hypot(xp - event.x, yp - event.y)
                    if d < dmin:          # a mean of repeats: its latest record
                        best, dmin = max(rs, key=lambda q: q["expno"]), d
        if best is not None and not self.show_record(best["expno"]):
            self.set_msg("expno %d has no processed spectrum to show" % best["expno"])

    def update_errrow(self):
        """Shows the error-bar row (and its noise and fit-weight settings) while error bars are on."""
        ph = self.analyzer.phase
        em = ph.get("error_bars", "none")
        if em == "none":
            if self.errrow_shown:
                self.errrow.pack_forget()
                self.errrow_shown = False
            return
        if em == "noise":
            self.err_text.configure(text="±1σ from the noise floor of each record (FID(t0): of each fid):")
            self.noise_box.pack(side=tk.LEFT, after=self.err_text)
        else:
            self.err_text.configure(text="mean ± standard error over the records at the same %s "
                                         "(sets, or a repeated D1)" % ("D1" if self.buildup else "frequency"))
            self.noise_box.pack_forget()
        if self.buildup:
            self.fitsig_cb.pack(side=tk.LEFT, padx=(16, 0))
        if not self.errrow_shown:
            self.errrow.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(0, 2), after=self.bar)
            self.errrow_shown = True

    def on_error_mode(self, event=None):
        mode = list(ERROR_MODES)[max(0, self.err_combo.current())]
        self.set_msg(self.analyzer.set_display(error_bars=mode))
        self.update_errrow()
        self.refresh(reschedule=False)
        self.spec.redraw()

    def on_noise_region(self):
        vals = []
        for e in (self.noise_from, self.noise_to):
            t = e.get().strip()
            try:
                vals.append(float(t) if t else None)
            except ValueError:
                self.set_msg("noise region: '%s' is not a number (ppm)" % t)
                return
        if (vals[0] is None) != (vals[1] is None):
            self.set_msg("noise region: give both ends (ppm), or leave both empty for the automatic region")
            return
        if vals[0] is not None and vals[0] == vals[1]:
            self.set_msg("noise region: the two ends are the same")
            return
        ph = self.analyzer.phase
        if (ph.get("noise_from"), ph.get("noise_to")) == tuple(vals):
            return
        self.set_msg(self.analyzer.set_display(noise_from=vals[0], noise_to=vals[1]))
        self.refresh(reschedule=False)
        self.spec.redraw()

    def on_fit_sigma(self):
        self.set_msg(self.analyzer.set_display(fit_sigma=bool(self.fitsig_var.get())))
        self.refresh(reschedule=False)

    def on_fit_model(self, event=None):
        model = list(FIT_MODELS)[max(0, self.fit_combo.current())]
        self.set_msg(self.analyzer.set_display(fit_model=model))
        self.refresh(reschedule=False)

    def on_buildup_axes(self):
        self.set_msg(self.analyzer.set_display(log_d1=bool(self.logd1_var.get()),
                                               normalize=bool(self.norm_var.get())))
        self.refresh(reschedule=False)

    def on_fid_phase(self):
        self.set_msg(self.analyzer.set_display(show_fid_phase=bool(self.fph_var.get())))
        self.refresh(reschedule=False)

    def save_eps(self):
        path = eps_path(self.runpath, self.buildup)
        w = self.canvas.get_tk_widget()
        aspect = w.winfo_height() / float(max(1, w.winfo_width()))
        try:
            write_profile_eps(path, self.last_a, aspect)
            self.set_msg("Wrote %s (%.1f x %.1f in, the %s as shown, for Adobe Illustrator)"
                         % (path, EPS_WIDTH, min(5.0, max(2.0, EPS_WIDTH * aspect)),
                            "build-up" if self.buildup else "profile"), error=False)
        except Exception as ex:
            self.set_msg("Could not write %s: %s" % (path, ex))

    def export_csv(self):
        path = csv_path(self.runpath)
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            a = self.analyzer.run(force_fid=True)
            self.analyzer.write_csv(path, a)
            self.set_msg("Wrote %s (%d records)" % (path, len(a["results"])), error=False)
        except Exception as ex:
            self.set_msg("Could not write %s: %s" % (path, ex))
        finally:
            self.root.configure(cursor="")

    # -- phase ----------------------------------------------------------------
    def apply_phase(self, ph):
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            err = self.analyzer.set_phase(ph)
            self.set_msg(err)
            if err:
                print("[%s] %s" % (time.strftime("%H:%M:%S"), err))
                sys.stdout.flush()
            self.refresh(reschedule=False)
        finally:
            try:
                self.root.configure(cursor="")
            except Exception:
                pass


class SpectrumPane:
    """One record with the trial settings: phase or magnitude, baseline, and the intensity
    measure, or the start of its FID. 'Apply to all records' makes the settings the
    viewer's. The pane shows the latest record while 'Follow latest' is ticked."""

    def __init__(self, main, parent, ctl):
        self.main = main
        self.row = None
        self.spec = None
        self.note = ""
        self.what = ""
        self.span = None            # shading of the trial window
        self.nspan = None           # shading of the noise region (error bars)
        self.drag = None            # right-button drag: [x0, x1, patch]
        self.fid_shown = False      # the FID(t0) row is packed
        self.trial = None           # from the applied settings at the first refresh
        self.drawn = None           # what the axes show: "spectrum", "fid" or None

        self.fig = Figure(figsize=(5.6, 4.4))
        self.ax = self.fig.add_subplot(111)
        self.canvas = main.FigureCanvas(self.fig, master=parent)

        def bind_entry(entry, fn):
            for ev in ("<Return>", "<KP_Enter>", "<FocusOut>"):
                entry.bind(ev, lambda e: fn())

        # Top: record list, navigation and following; then what the record shows
        nav = ttk.Frame(parent)
        nav.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(4, 0))
        self.follow_var = tk.IntVar(value=1)            # packed first: kept when the pane is narrow
        ttk.Checkbutton(nav, text="Follow latest", variable=self.follow_var,
                        command=self.on_follow).pack(side=tk.RIGHT, padx=(6, 2))
        ttk.Label(nav, text="Record").pack(side=tk.LEFT, padx=(2, 4))
        self.combo = ttk.Combobox(nav, state="disabled", width=20)
        self.combo.pack(side=tk.LEFT)
        self.combo.bind("<<ComboboxSelected>>", main.on_select)
        self.prev_btn = ttk.Button(nav, text="< Prev", width=6, command=lambda: self.step(-1))
        self.prev_btn.pack(side=tk.LEFT, padx=(6, 0))
        self.next_btn = ttk.Button(nav, text="Next >", width=6, command=lambda: self.step(1))
        self.next_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.pos_var = tk.StringVar(value="")
        ttk.Label(nav, textvariable=self.pos_var, foreground=HINT_FG).pack(side=tk.LEFT, padx=(6, 0))
        self.info = InfoPanel(parent, key_width=8)
        self.info.frame.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(2, 0))

        # Below the plot: the view switch, at the right of the zoom toolbar
        tbf = ttk.Frame(parent)
        tbf.pack(side=tk.BOTTOM, fill=tk.X)
        self.ctl_btn = ttk.Button(tbf, text="Hide controls", width=13, command=main.toggle_controls)
        self.ctl_btn.pack(side=tk.RIGHT, padx=(6, 4))
        self.view_var = tk.StringVar(value="spectrum")
        ttk.Radiobutton(tbf, text="FID start", value="fid", variable=self.view_var,
                        command=self.on_view).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Radiobutton(tbf, text="Spectrum", value="spectrum", variable=self.view_var,
                        command=self.on_view).pack(side=tk.RIGHT, padx=(0, 4))
        ttk.Label(tbf, text="Show:").pack(side=tk.RIGHT, padx=(8, 4))
        self.toolbar = main.Toolbar(self.canvas, tbf)
        self.toolbar.update()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect("button_press_event", self.on_press)
        self.canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.canvas.mpl_connect("button_release_event", self.on_release)
        self.canvas.mpl_connect("resize_event", lambda e: relayout(self.fig))
        self.ax.text(0.5, 0.5, "waiting for the first spectrum", transform=self.ax.transAxes,
                     ha="center", va="center", color="0.4")

        # Controls strip, left: phase
        self.ph_frame = ttk.LabelFrame(ctl, text=" Phase ")
        self.ph_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.scales, self.entries = {}, {}
        for row, (name, rng) in enumerate((("ph0", PH0_RANGE), ("ph1", PH1_RANGE))):
            ttk.Label(self.ph_frame, text="%s (deg)" % name.upper()).grid(row=row, column=0, sticky="w",
                                                                           padx=(6, 4))
            sc = tk.Scale(self.ph_frame, from_=-rng, to=rng, resolution=0.1, orient=tk.HORIZONTAL,
                          length=300, showvalue=0,
                          command=lambda v, n=name: self.on_scale(n, v))
            sc.grid(row=row, column=1, sticky="we", padx=4)
            en = ttk.Entry(self.ph_frame, width=8)
            en.grid(row=row, column=2, sticky="w", padx=(0, 6))
            bind_entry(en, lambda n=name: self.on_entry(n))
            self.scales[name], self.entries[name] = sc, en
        ttk.Label(self.ph_frame, text="Pivot (ppm)").grid(row=2, column=0, sticky="w", padx=(6, 4))
        pv = ttk.Frame(self.ph_frame)
        pv.grid(row=2, column=1, columnspan=2, sticky="w", padx=4)
        self.pivot_entry = ttk.Entry(pv, width=8)
        self.pivot_entry.pack(side=tk.LEFT)
        bind_entry(self.pivot_entry, self.on_pivot_entry)
        ttk.Label(pv, text="or left-click in the spectrum", foreground=HINT_FG).pack(side=tk.LEFT, padx=6)
        mf = ttk.Frame(self.ph_frame)
        mf.grid(row=3, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 6))
        self.zero_btn = ttk.Button(mf, text="Zero phase", command=self.zero)
        self.zero_btn.pack(side=tk.LEFT)
        self.mag_var = tk.IntVar(value=0)
        self.mag_cb = ttk.Checkbutton(mf, text="Magnitude |1r + i*1i| instead (no phase)",
                                      variable=self.mag_var, command=self.on_magnitude)
        self.mag_cb.pack(side=tk.LEFT, padx=(12, 0))
        self.ph_frame.columnconfigure(1, weight=1)

        # Controls strip, right: intensity of each record, then baseline
        right = ttk.Frame(ctl)
        right.grid(row=0, column=1, sticky="nsew")
        itf = ttk.LabelFrame(right, text=" Intensity of each record ")
        itf.pack(side=tk.TOP, fill=tk.X)
        mrow = ttk.Frame(itf)
        mrow.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(2, 0))
        self.mode_row = mrow
        ttk.Label(mrow, text="Mode").pack(side=tk.LEFT)
        self.mode_box = ttk.Combobox(mrow, values=list(MODES), width=8, state="readonly")
        self.mode_box.pack(side=tk.LEFT, padx=4)
        self.mode_box.bind("<<ComboboxSelected>>", lambda e: self.on_mode())
        self.mode_help = tk.StringVar(value="")
        ttk.Label(mrow, textvariable=self.mode_help, foreground=HINT_FG).pack(side=tk.LEFT, padx=(4, 0))
        # FID(t0) settings: packed below the mode only while the mode is FID(t0)
        self.fid_row = ttk.Frame(itf)
        ttk.Label(self.fid_row, text="N").pack(side=tk.LEFT)
        self.fidn_box = tk.Spinbox(self.fid_row, from_=1, to=FID_HEAD, width=4, command=self.on_fid_n)
        self.fidn_box.pack(side=tk.LEFT, padx=4)
        bind_entry(self.fidn_box, self.on_fid_n)
        ttk.Label(self.fid_row, text="points from g = ceil(GRPDLY)").pack(side=tk.LEFT)
        self.fidfit_var = tk.IntVar(value=0)
        ttk.Checkbutton(self.fid_row, text="linear fit, at t = GRPDLY", variable=self.fidfit_var,
                        command=self.on_fid_fit).pack(side=tk.LEFT, padx=(12, 0))
        wr = ttk.Frame(itf)
        wr.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(4, 0))
        ttk.Label(wr, text="Window centre").pack(side=tk.LEFT)
        self.c_entry = ttk.Entry(wr, width=8)
        self.c_entry.pack(side=tk.LEFT, padx=4)
        bind_entry(self.c_entry, self.on_window_entry)
        ttk.Label(wr, text="width").pack(side=tk.LEFT, padx=(6, 0))
        self.w_entry = ttk.Entry(wr, width=8)
        self.w_entry.pack(side=tk.LEFT, padx=4)
        bind_entry(self.w_entry, self.on_window_entry)
        ttk.Label(wr, text="ppm").pack(side=tk.LEFT)
        self.whole_var = tk.IntVar(value=0)
        self.whole_cb = ttk.Checkbutton(wr, text="whole spectrum", variable=self.whole_var,
                                        command=self.on_whole)
        self.whole_cb.pack(side=tk.LEFT, padx=(10, 0))
        self.win_hint = ttk.Label(itf, text="", foreground=HINT_FG)
        self.win_hint.pack(side=tk.TOP, anchor="w", padx=6, pady=(0, 4))
        self.bl_frame = ttk.LabelFrame(right, text=" Baseline ")
        self.bl_frame.pack(side=tk.TOP, fill=tk.X, pady=(6, 0))
        brow = ttk.Frame(self.bl_frame)
        brow.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(2, 4))
        self.bl_var = tk.IntVar(value=0)
        self.bl_cb = ttk.Checkbutton(brow, text="Subtract a polynomial of order", variable=self.bl_var,
                                     command=self.on_baseline)
        self.bl_cb.pack(side=tk.LEFT)
        self.order_box = tk.Spinbox(brow, from_=0, to=8, width=3, command=self.on_order)
        self.order_box.pack(side=tk.LEFT, padx=4)
        bind_entry(self.order_box, self.on_order)
        ttk.Label(brow, text="(fitted outside the window)", foreground=HINT_FG).pack(side=tk.LEFT)

        # Controls strip, bottom: buttons, then status
        btns = ttk.Frame(ctl)
        btns.grid(row=1, column=0, columnspan=2, sticky="we", pady=(6, 2))
        ttk.Button(btns, text="Revert to applied", command=self.revert).pack(side=tk.LEFT)
        ttk.Button(btns, text="Fit y-axis", command=self.fit_y).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Apply to all records", command=self.apply).pack(side=tk.RIGHT)
        self.pending = tk.StringVar(value="")
        ttk.Label(btns, textvariable=self.pending, foreground=PENDING_FG).pack(side=tk.RIGHT, padx=8)
        self.status = tk.StringVar(value="")
        ttk.Label(ctl, textvariable=self.status, foreground="#333333", justify=tk.LEFT,
                  wraplength=1200).grid(row=2, column=0, columnspan=2, sticky="w")
        ctl.columnconfigure(0, weight=1)

    # -- settings ------------------------------------------------------------
    def applied_trial(self):
        """The applied settings, with the window the main window uses now."""
        a = self.main.last_a
        ph = dict(self.main.analyzer.phase)
        ph.update(win_set=True, center=a["center"], width=a["width"], mode=a["mode"])
        return ph

    def normalised(self, ph, spec):
        """ph as it would be applied: base from spec, unused fields cleared."""
        ph = dict(ph)
        ph["win_set"] = True
        if phase_active(ph) and spec is not None:
            ph["base0"], ph["base1"] = spec["phc0"], spec["phc1"]
        if not phase_active(ph):
            ph["ph0"] = ph["ph1"] = 0.0
            ph["pivot"] = ph["base0"] = ph["base1"] = None
        return ph

    def fid_mode(self):
        return self.trial is not None and self.trial["mode"] == FID_MODE

    # -- record --------------------------------------------------------------
    def sync(self, a, phase_changed, target):
        """Called after each refresh of the main window; target is the record the list
        shows (the latest while following)."""
        if self.trial is None:                       # first refresh
            self.trial = self.applied_trial()
            self.view_var.set("fid" if self.trial["mode"] == FID_MODE else "spectrum")
            self.sync_widgets()
            phase_changed = False
        elif phase_changed:
            pivot = self.trial["pivot"]
            self.trial = self.applied_trial()
            if self.trial["pivot"] is None:
                self.trial["pivot"] = pivot
            self.note = ("The settings file was changed outside this viewer; the settings below "
                         "were reset to it.")
        if target is None:
            self.update_nav()
            self.update_status()
            return
        if self.row is None or target["expno"] != self.row["expno"]:
            self.show(target)                        # the first record, or a new latest one
            return
        if target["readable"] and target["files"] != self.row["files"]:
            self.show(target, keep_view=True)        # reprocessed: reload
            return
        self.update_nav()                            # new records may have arrived
        if phase_changed:
            self.sync_widgets()
            self.redraw(fit=True)
        else:
            self.update_status()

    def show(self, row, keep_view=None):
        """Shows row. keep_view (default: when the same view is already drawn, i.e. when
        moving between records or reloading) keeps the x range; y is rescaled."""
        a = self.main.last_a
        view = self.view_var.get()
        keep = (self.drawn == view) if keep_view is None else (keep_view and self.drawn == view)
        xl = self.ax.get_xlim()
        self.row = row
        self.what = record_what(row, a["multi_set"])
        self.update_nav()
        try:
            self.spec = self.main.analyzer.spectrum(a["ds_dir"], row["expno"], row["files"])
        except Exception as ex:
            self.spec = None
            if view == "spectrum":
                self.info.set([("Value", "expno %d: %s" % (row["expno"], ex), True)])
                self.ax.clear()
                self.drawn = None
                self.ax.text(0.5, 0.5, "expno %d: %s" % (row["expno"], ex), transform=self.ax.transAxes,
                             ha="center", va="center", color="0.3")
                self.canvas.draw_idle()
                self.update_status()
                return
        if self.spec is not None and self.trial["pivot"] is None:
            self.trial["pivot"] = default_pivot(self.spec, self.trial["center"])
        self.sync_widgets()
        if view == "fid":
            self.draw_fid(xl if keep else None)
            if not keep:
                self.toolbar.update()                # new view: start the zoom history here
            return

        spec = self.spec
        ax = self.ax
        ax.clear()
        self.span = None
        ppm, ns = spec["ppm"], float(spec["ns"])
        self.l_orig, = ax.plot(ppm, spec["re"] / ns, color="0.68", lw=0.8, label="as processed (TopSpin)")
        self.l_trial, = ax.plot(ppm, spec["re"] / ns, color="0.1", lw=0.9, label="with the settings below")
        ax.axhline(0.0, color="0.8", lw=0.6)
        self.l_pivot = ax.axvline(self.trial["pivot"], color="#e67e22", ls="--", lw=1.0, label="pivot")
        self.l_point, = ax.plot([], [], "o", color="#c0392b", ms=6)
        ax.set_xlim(float(ppm.max()), float(ppm.min()))
        ax.set_xlabel("ppm")
        ax.set_ylabel("intensity per scan")
        ax.legend(loc="upper right", fontsize=8)
        self.drawn = "spectrum"
        if not keep:
            self.toolbar.update()          # new view: start the zoom history here
        self.redraw(draw=False)
        if keep:
            ax.set_xlim(xl)
        self.fit_y(draw=False)
        relayout(self.fig)
        self.canvas.draw_idle()

    def draw_fid(self, xl=None):
        """The start of the record's FID with the trial N and method; xl: x range to keep."""
        a, tr, row = self.main.last_a, self.trial, self.row
        ax = self.ax
        ax.clear()
        self.span = None
        self.drawn = "fid"
        try:
            fid = self.main.analyzer.fid(a["ds_dir"], row["expno"])
            draw_fid_record(ax, fid, int(tr["fid_n"]), bool(tr["fid_fit"]), None)
            if xl is not None:
                ax.set_xlim(xl)
        except Exception as ex:
            ax.text(0.5, 0.5, "expno %d: %s" % (row["expno"], ex), transform=ax.transAxes,
                    ha="center", va="center", color="0.3")
        self.info.set([("Value", self.fid_text(), False),
                       ("Shows", "start of the FID: |fid| / (NS·RG) against the point index; "
                                 "N %d, %s" % (int(tr["fid_n"]), "line fitted, at t = GRPDLY" if tr["fid_fit"]
                                               else "mean"), False)])
        relayout(self.fig)
        self.canvas.draw_idle()
        self.update_status()

    def step(self, d):
        """Shows the previous (d = -1) or next (d = +1) record of the list."""
        ex = self.main.expnos
        if self.row is None or not ex:
            return
        j = ex.index(self.row["expno"]) + d if self.row["expno"] in ex else 0
        if 0 <= j < len(ex):
            self.main.show_record(ex[j])

    def update_nav(self):
        ex = self.main.expnos
        i = ex.index(self.row["expno"]) if self.row is not None and self.row["expno"] in ex else None
        self.prev_btn.configure(state="normal" if i is not None and i > 0 else "disabled")
        self.next_btn.configure(state="normal" if i is not None and i < len(ex) - 1 else "disabled")
        self.pos_var.set("%d/%d" % (i + 1, len(ex)) if i is not None else "")

    def on_follow(self):
        m = self.main
        if self.follow_var.get():
            m.user_expno = None
            if m.last_a is not None:
                m.update_records(m.last_a)
                r = m.selected_row()
                if r is not None and (self.row is None or r["expno"] != self.row["expno"]):
                    self.show(r)
        elif self.row is not None:
            m.user_expno = self.row["expno"]

    def unfollow(self):
        """A phase, baseline or window control was touched: stay on this record."""
        if self.follow_var.get():
            self.follow_var.set(0)
            if self.row is not None:
                self.main.user_expno = self.row["expno"]

    def on_view(self):
        if self.row is not None:
            self.show(self.row, keep_view=False)

    # -- drawing -------------------------------------------------------------
    def draw_span(self):
        if self.span is not None:
            try:
                self.span.remove()
            except Exception:
                pass
            self.span = None
        c, w = self.trial["center"], self.trial["width"]
        if c is not None:
            self.span = self.ax.axvspan(c - w / 2.0, c + w / 2.0, color="#1f5fa8", alpha=0.12, zorder=0)
        if self.nspan is not None:
            try:
                self.nspan.remove()
            except Exception:
                pass
            self.nspan = None
        ph = self.main.analyzer.phase
        if ph.get("error_bars") == "noise" and ph.get("noise_from") is not None \
                and ph.get("noise_to") is not None and self.drawn == "spectrum":
            self.nspan = self.ax.axvspan(ph["noise_from"], ph["noise_to"], color="#7f8c8d", alpha=0.18,
                                         zorder=0)

    def fid_text(self):
        """FID(t0) and the FID phase of the record shown, with the trial N and method."""
        a, tr = self.main.last_a, self.trial
        try:
            m = fid_t0(self.main.analyzer.fid(a["ds_dir"], self.row["expno"]), int(tr["fid_n"]))
        except Exception as ex:
            return "FID(t0): %s" % ex
        v = m["fit"] if tr["fid_fit"] else m["mean"]
        if v is None:
            return "FID(t0): the linear fit needs N >= 2"
        s = "FID(t0) %.4g per NS·RG · FID phase %+.1f°" % (v, m["phase"])
        if a["fid_ref"] is not None:
            s += " (%+.1f° from the ON median)" % wrap_pm180(m["phase"] - a["fid_ref"])
        return s

    def redraw(self, draw=True, fit=False):
        """fit=True rescales y to the visible traces; phase changes (PH0, PH1, pivot)
        keep the scale so that the effect of each change can be compared."""
        if self.row is not None and self.drawn == "fid":
            self.draw_fid(self.ax.get_xlim())
            return
        if self.spec is None or self.drawn != "spectrum":
            self.update_status()
            return
        spec, tr = self.spec, self.trial
        fid = self.fid_mode()
        y, notes, _ = corrected(spec, tr, tr["center"], tr["width"], force=True)
        y = y / float(spec["ns"])
        self.l_trial.set_ydata(y)
        val_txt = ""
        if fid:
            self.l_point.set_data([], [])
            val_txt = self.fid_text()
            try:
                val_txt += " · window integral %.4g" % integrate(spec["ppm"], y, tr["center"], tr["width"])
            except Exception as ex:
                notes.append(str(ex))
        else:
            try:
                val, at = measure(spec["ppm"], y, tr["center"], tr["width"], tr["mode"])
                val_txt = "%s %.4g per scan · integral %.4g · NS %d" % (
                    tr["mode"], val, integrate(spec["ppm"], y, tr["center"], tr["width"]), spec["ns"])
                if at is not None:
                    self.l_point.set_data([at], [val])
                else:
                    self.l_point.set_data([], [])
            except Exception as ex:
                self.l_point.set_data([], [])
                notes.append(str(ex))
        self.l_pivot.set_xdata([tr["pivot"], tr["pivot"]])
        self.l_pivot.set_visible(not (tr["magnitude"] or fid))
        self.draw_span()
        if fid:
            settings = "FID(t0), N %d, %s; the spectrum is shown with the settings below" % (
                int(tr["fid_n"]), "line fitted, at t = GRPDLY" if tr["fid_fit"] else "mean")
        else:
            if tr["magnitude"]:
                settings = "magnitude"
            else:
                settings = "PH0 %+.1f°, PH1 %+.1f°, pivot %.2f ppm" % (tr["ph0"], tr["ph1"], tr["pivot"])
            settings += " · %s · %s" % ("baseline order %d" % tr["order"] if tr["baseline"] else "no baseline",
                                        window_desc(tr["center"], tr["width"]).replace("+/-", "±"))
        self.ax.set_title("")
        a = self.main.last_a
        if a is not None and a.get("error_bars") == "noise" and self.row is not None:
            r = [q for q in a["results"] if q["expno"] == self.row["expno"]]
            if r and r[0].get("err") is not None:
                val_txt += " · σ %.3g (noise, applied settings)" % r[0]["err"]
            elif r and r[0].get("err_note"):
                val_txt += " · %s" % r[0]["err_note"]
        self.info.set([("Value", val_txt, False), ("Settings", settings, False)])
        self.update_status(notes)
        if fit:
            self.fit_y(draw=False)
        if draw:
            self.canvas.draw_idle()

    def fit_y(self, draw=True):
        if self.drawn == "fid":
            self.ax.relim()
            self.ax.autoscale_view(scalex=False)
            self.canvas.draw_idle()
            return
        if self.spec is None or self.drawn != "spectrum":
            return
        ppm = self.spec["ppm"]
        x0, x1 = sorted(self.ax.get_xlim())
        sel = (ppm >= x0) & (ppm <= x1)
        if not np.any(sel):
            return
        ys = np.concatenate([np.asarray(self.l_orig.get_ydata())[sel],
                             np.asarray(self.l_trial.get_ydata())[sel]])
        ys = ys[np.isfinite(ys)]
        if ys.size == 0:
            return
        lo, hi = float(ys.min()), float(ys.max())
        pad = 0.05 * (hi - lo) if hi > lo else 1.0
        self.ax.set_ylim(lo - pad, hi + pad)
        if draw:
            self.canvas.draw_idle()

    def update_status(self, notes=None):
        a = self.main.last_a
        if self.trial is None or a is None:
            return
        ap = self.main.analyzer.phase
        if a["mode"] == FID_MODE:
            measure_txt = mode_label(a["mode"], ap)
        else:
            measure_txt = "%s, %s" % (window_desc(a["center"], a["width"]), a["mode"])
        lines = ["Applied to all records: %s; %s" % (describe_phase(ap, window=False), measure_txt)]
        pending = proc_key(self.normalised(self.trial, self.spec)) != \
            proc_key(self.normalised(self.applied_trial(), self.spec))
        self.pending.set("Changes not applied yet" if pending else "")
        if self.fid_mode():
            lines.append("FID(t0) comes from the raw fid: phase, magnitude, baseline and window do not affect "
                         "it. Choose another mode to change them (they still set the window integral).")
        if self.spec is not None:
            if self.spec["im"] is None:
                lines.append("No usable 1i for this record (%s): neither the phase nor the magnitude "
                             "can be computed." % self.spec["im_note"])
            elif phase_active(ap) and not ap.get("magnitude") and not base_matches(self.spec, ap):
                lines.append("This record was processed with PHC0 %.3f, PHC1 %.3f, not with the values the "
                             "applied correction is for; the profile shows it as processed."
                             % (self.spec["phc0"], self.spec["phc1"]))
        if notes:
            lines.append("; ".join(notes))
        if self.note:
            lines.append(self.note)
        self.status.set("\n".join(lines))

    # -- widgets -------------------------------------------------------------
    def sync_widgets(self):
        tr = self.trial
        fid = self.fid_mode()
        for name in ("ph0", "ph1"):           # a disabled Tk scale ignores set()
            self.scales[name].configure(state="normal")
        for name in ("ph0", "ph1"):
            self.scales[name].set(tr[name])
            self.set_entry(self.entries[name], "%.1f" % tr[name])
        self.set_entry(self.pivot_entry, "%.2f" % tr["pivot"] if tr["pivot"] is not None else "")
        self.mag_var.set(1 if tr["magnitude"] else 0)
        self.bl_var.set(1 if tr["baseline"] else 0)
        self.set_entry(self.order_box, str(int(tr["order"])))
        whole = tr["center"] is None
        self.whole_var.set(1 if whole else 0)
        if not whole:
            self.set_entry(self.c_entry, "%.2f" % tr["center"])
        self.set_entry(self.w_entry, "%.2f" % tr["width"])
        for e in (self.c_entry, self.w_entry):
            e.configure(state="disabled" if (whole or fid) else "normal")
        self.mode_box.set(tr["mode"])
        self.mode_help.set(MODE_HELP.get(tr["mode"], ""))
        state = "disabled" if (tr["magnitude"] or fid) else "normal"
        for name in ("ph0", "ph1"):
            self.scales[name].configure(state=state)
            self.entries[name].configure(state=state)
        self.pivot_entry.configure(state=state)
        # FID(t0) does not use the phase, magnitude, baseline or window
        other = "disabled" if fid else "normal"
        for w in (self.zero_btn, self.mag_cb, self.bl_cb, self.order_box, self.whole_cb):
            w.configure(state=other)
        suffix = " - not used by FID(t0) " if fid else " "
        self.ph_frame.configure(text=" Phase" + suffix)
        self.bl_frame.configure(text=" Baseline" + suffix)
        self.win_hint.configure(text="window not used by FID(t0); choose another mode to change it" if fid
                                else "or drag with the right mouse button in the spectrum")
        self.set_entry(self.fidn_box, str(int(tr["fid_n"])))
        self.fidfit_var.set(1 if tr["fid_fit"] else 0)
        if fid != self.fid_shown:
            if fid:
                self.fid_row.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(4, 0), after=self.mode_row)
            else:
                self.fid_row.pack_forget()
            self.fid_shown = fid

    @staticmethod
    def set_entry(entry, text):
        disabled = str(entry.cget("state")) == "disabled"
        if disabled:
            entry.configure(state="normal")
        entry.delete(0, tk.END)
        entry.insert(0, text)
        if disabled:
            entry.configure(state="disabled")

    def limit(self, name, v):
        return wrap180(v) if name == "ph0" else max(-PH1_RANGE, min(PH1_RANGE, v))

    def on_scale(self, name, v):
        v = float(v)
        if self.trial is None or self.trial["magnitude"] or self.fid_mode() or abs(v - self.trial[name]) < 0.05:
            return                                   # echo, or not in use
        self.trial[name] = v
        self.set_entry(self.entries[name], "%.1f" % v)
        self.note = ""
        self.unfollow()
        self.redraw()

    def on_entry(self, name):
        try:
            v = self.limit(name, float(self.entries[name].get()))
        except ValueError:
            self.set_entry(self.entries[name], "%.1f" % self.trial[name])
            return
        if v == self.trial[name]:
            return
        self.trial[name] = v
        self.scales[name].set(v)
        self.set_entry(self.entries[name], "%.1f" % v)
        self.note = ""
        self.unfollow()
        self.redraw()

    def set_pivot(self, p):
        """Moves the pivot without changing the phase applied to the spectrum."""
        old = self.trial["pivot"]
        if self.spec is not None and old is not None:
            du = (old - p) * self.spec["sf"] / self.spec["sw_p"]
            self.trial["ph0"] = wrap180(self.trial["ph0"] + self.trial["ph1"] * du)
        self.trial["pivot"] = float(p)
        self.unfollow()
        self.sync_widgets()
        self.redraw()

    def on_pivot_entry(self):
        try:
            p = float(self.pivot_entry.get())
        except ValueError:
            self.sync_widgets()
            return
        if self.trial["pivot"] is None or abs(p - self.trial["pivot"]) > 1e-9:
            self.set_pivot(p)

    def set_window(self, center, width):
        self.trial["center"] = None if center is None else float(center)
        if width is not None:
            self.trial["width"] = float(width)
        self.note = ""
        self.unfollow()
        self.sync_widgets()
        self.redraw(fit=self.trial["baseline"])   # the baseline fit leaves out the window

    def on_window_entry(self):
        if self.whole_var.get() or self.fid_mode():
            return
        try:
            c = float(self.c_entry.get())
            w = float(self.w_entry.get())
            if not w > 0:
                raise ValueError
        except ValueError:
            self.sync_widgets()
            return
        if c != self.trial["center"] or w != self.trial["width"]:
            self.set_window(c, w)

    def on_whole(self):
        if self.whole_var.get():
            self.last_center = self.trial["center"]
            self.set_window(None, None)
        else:
            c = getattr(self, "last_center", None)
            if c is None and self.spec is not None:
                c = default_pivot(self.spec, None)
            self.set_window(c, None)

    def on_mode(self):
        m = self.mode_box.get()
        if m in MODES and m != self.trial["mode"]:
            was_fid = self.fid_mode()
            self.trial["mode"] = m
            self.sync_widgets()
            if (m == FID_MODE) != was_fid:           # the view follows the mode; it can be switched back
                self.view_var.set("fid" if m == FID_MODE else "spectrum")
                if self.row is not None:
                    self.show(self.row, keep_view=False)
                    return
            self.redraw()

    def on_fid_n(self):
        try:
            v = max(1, min(FID_HEAD, int(float(self.fidn_box.get()))))
        except ValueError:
            v = int(self.trial["fid_n"])
        self.set_entry(self.fidn_box, str(v))
        if v != self.trial["fid_n"]:
            self.trial["fid_n"] = v
            self.redraw()

    def on_fid_fit(self):
        self.trial["fid_fit"] = bool(self.fidfit_var.get())
        self.redraw()

    def on_magnitude(self):
        self.trial["magnitude"] = bool(self.mag_var.get())
        self.unfollow()
        self.sync_widgets()
        self.redraw(fit=True)

    def on_baseline(self):
        self.trial["baseline"] = bool(self.bl_var.get())
        self.unfollow()
        self.redraw(fit=True)

    def on_order(self):
        try:
            v = max(0, min(8, int(float(self.order_box.get()))))
        except ValueError:
            v = int(self.trial["order"])
        self.set_entry(self.order_box, str(v))
        if v != self.trial["order"]:
            self.trial["order"] = v
            self.unfollow()
            if self.trial["baseline"]:
                self.redraw(fit=True)
            else:
                self.update_status()

    # -- mouse: left click = pivot, right drag = window ---------------------
    def toolbar_busy(self):
        return getattr(self.toolbar, "mode", "") != ""      # zoom or pan is active

    def on_press(self, event):
        if event.inaxes is not self.ax or event.xdata is None or self.spec is None or self.toolbar_busy():
            return
        if self.fid_mode() or self.drawn != "spectrum":
            return                                           # neither pivot nor window is used
        if event.button == 1 and not self.trial["magnitude"]:
            self.set_pivot(event.xdata)
        elif event.button == 3:
            self.drag = [event.xdata, event.xdata, None]

    def on_motion(self, event):
        if self.drag is None or event.inaxes is not self.ax or event.xdata is None:
            return
        self.drag[1] = event.xdata
        if self.drag[2] is not None:
            try:
                self.drag[2].remove()
            except Exception:
                pass
        lo, hi = sorted(self.drag[:2])
        self.drag[2] = self.ax.axvspan(lo, hi, color="#e67e22", alpha=0.25, zorder=0)
        self.canvas.draw_idle()

    def on_release(self, event):
        if self.drag is None:
            return
        if event.inaxes is self.ax and event.xdata is not None:
            self.drag[1] = event.xdata
        x0, x1, patch = self.drag
        self.drag = None
        if patch is not None:
            try:
                patch.remove()
            except Exception:
                pass
        ppm = self.spec["ppm"]
        step = abs(float(ppm[0] - ppm[1])) if ppm.size > 1 else 0.0
        if abs(x1 - x0) <= 3 * step:           # a click: move the window, keep its width
            self.set_window(x0, None)
        else:
            self.set_window((x0 + x1) / 2.0, abs(x1 - x0))

    # -- buttons ---------------------------------------------------------------
    def zero(self):
        self.trial["ph0"] = self.trial["ph1"] = 0.0
        self.unfollow()
        self.sync_widgets()
        self.redraw(fit=True)

    def revert(self):
        pivot = self.trial["pivot"]
        self.trial = self.applied_trial()
        if self.trial["pivot"] is None:
            self.trial["pivot"] = pivot
        self.note = ""
        self.sync_widgets()
        self.redraw(fit=True)

    def apply(self):
        tr = self.trial
        if (tr["magnitude"] or phase_active(tr)) and (self.spec is None or self.spec["im"] is None):
            self.note = ("Not applied: this record has no usable 1i, so neither the phase nor the "
                         "magnitude can be set on it.")
            self.update_status()
            return
        if self.fid_mode() and tr["fid_fit"] and int(tr["fid_n"]) < 2:
            self.note = "Not applied: the linear fit needs N >= 2."
            self.update_status()
            return
        if self.spec is not None and tr["center"] is not None:
            try:
                measure(self.spec["ppm"], self.spec["re"], tr["center"], tr["width"], tr["mode"])
            except Exception as ex:
                self.note = "Not applied: %s." % ex
                self.update_status()
                return
        self.note = ""
        ph = self.normalised(tr, self.spec)
        ph["show_integral"] = self.main.analyzer.phase.get("show_integral", False)
        ph["show_fid_phase"] = self.main.analyzer.phase.get("show_fid_phase", False)
        self.main.apply_phase(ph)
        self.update_status()


# --------------------------------------------------------------------------
def mode_arg(text):
    m = canon_mode(text)
    if m is None:
        raise argparse.ArgumentTypeError("choose from extreme, max, sum, FID(t0)")
    return m


def main():
    ap = argparse.ArgumentParser(description="Plot a DNP frequency profile or build-up from a run file (fs_runs/<run id>/run.txt).")
    ap.add_argument("runfile")
    ap.add_argument("--ppm", type=float, default=None, help="window centre in ppm (default: from run file)")
    ap.add_argument("--width", type=float, default=None, help="full window width in ppm (default: from run file)")
    ap.add_argument("--mode", type=mode_arg, default=None,
                    help="intensity measure: extreme, max, sum, or FID(t0) (also: fid) (default: from run file)")
    ap.add_argument("--interval", type=float, default=15.0, help="refresh interval in s")
    ap.add_argument("--once", action="store_true", help="draw once and exit")
    ap.add_argument("--csv", action="store_true",
                    help="also write records.csv (one row per record) whenever the PNG and TSV are written")
    args = ap.parse_args()

    runpath = os.path.abspath(args.runfile)
    if not os.path.exists(runpath):
        sys.exit("fs_plot.py: run file not found: %s" % runpath)
    png, tsv, _ = output_paths(runpath)
    reopen = reopen_command(runpath, args)
    print("[%s] fs_plot.py: %s\n    reopen with: %s"
          % (time.strftime("%Y-%m-%d %H:%M:%S"), runpath, reopen))
    sys.stdout.flush()

    analyzer = Analyzer(runpath, args)
    win = None
    if not args.once and os.environ.get("DISPLAY"):
        if tk is None:
            print("fs_plot.py: tkinter is not installed; writing the PNG and TSV only")
        else:
            try:
                win = MainWindow(runpath, args, analyzer, reopen, png, tsv)
            except Exception as ex:
                print("fs_plot.py: could not open a window (%s); writing the PNG and TSV only" % ex)
        sys.stdout.flush()
    if win is not None:
        win.run()
    else:
        run_files_only(runpath, args, analyzer, reopen, png, tsv)


if __name__ == "__main__":
    main()
