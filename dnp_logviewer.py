#!/usr/bin/env python3
"""
DNP log viewer: plots the logs that dnp_monitor.py writes, for any time range.

Panels: one per MAS3 controller, the Lake Shore 336, and the LN2 level
(AMI 1700). Every logged variable has a checkbox; each panel shows one small
subplot per unit, and all subplots share one time axis. Colours follow the
monitor: spin rate in the controller's colour, bearing in blue, drive in
orange, LN2 in teal; variables the monitor does not show are in greys and
olives, told apart by line style.

Long ranges are drawn as a min/max envelope (short excursions stay visible).
Zooming in with the toolbar re-reads that span at full resolution.

Read-only: the viewer reads the .csv and .csv.gz log files and never changes
them. Exports (CSV, PNG) go to <base dir>/exports.

Uses pandas if it is installed (several times faster for weeks of data);
works without it.

Run:   python3 /home/nmrsu/dnp_monitor/dnp_logviewer.py
       python3 dnp_logviewer.py --start "2026-11-01 08:00" --stop "2026-11-02 08:00"
"""

import argparse
import calendar
import configparser
import csv
import gzip
import math
import operator
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from dateutil import tz as dateutil_tz   # installed with matplotlib

try:
    import pandas as pd
except ImportError:
    pd = None


# ==========================================================================
# Settings
# ==========================================================================

BASE_DIR = "/home/nmrsu/dnp_monitor"
CONFIG_NAME = "dnp_monitor.conf"
MAS_LOG_SUBDIR = "mas_logs"
LS_LOG_SUBDIR = "lakeshore336_logs"
AMI_LOG_SUBDIR = "ami1700_logs"
EXPORT_SUBDIR = "exports"

FULL_RES_MAX_ROWS = 400000     # per source; longer ranges are read as min/max bins
TARGET_BINS = 6000             # about this many bins across the range when binned
DRAW_MAX_POINTS = 6000         # full-resolution data above this is drawn as an envelope
BIN_WIDTHS_S = (1, 2, 5, 10, 15, 20, 30, 60, 120, 180, 300, 600, 900, 1200, 1800,
                3600, 7200, 10800, 21600, 43200, 86400)
CACHE_BUDGET_BYTES = 150e6     # parsed files kept in memory, so refreshes only re-read the newest file
NOW_REFRESH_S = 30             # "Now" mode reloads at least this far apart
ZOOM_SETTLE_MS = 700           # after zooming/panning stops for this long, the view is updated
SPEED_FILE = Path.home() / ".dnp_logviewer_speed"   # learned reading speed, for the time estimate
LAYOUT_PX = dict(left=76, right=14, top=6, bottom=44, title=20, panel_gap=16, gap=7)
EXPORT_ASK_ROWS = 1000000      # bigger CSV exports ask first (they take minutes)
DEFAULT_SPAN_S = 24 * 3600
PRESETS = (("1 h", 3600), ("6 h", 6 * 3600), ("12 h", 12 * 3600), ("24 h", 24 * 3600), ("7 d", 7 * 86400), ("30 d", 30 * 86400))
TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")

LOCAL_TZ = dateutil_tz.tzlocal()
EPOCH_NUM = mdates.date2num(datetime(1970, 1, 1, tzinfo=timezone.utc))   # plot x = UTC, labels local
NAN = float("nan")

# Colours: the first group is shared with dnp_monitor.py
MAS_COLORS = ("#5b2a86", "#1b7a3e", "#8a5a00")   # per controller, in config order
BEARING = "#0072B2"
DRIVE = "#D55E00"
BEARING_LIGHT = "#56B4E9"
AMI_COLOR = "#0f7f8c"
INK = "#26364a"
MUTED = "#526277"
PANEL_BG = "#f4f7fb"
ERROR_RED = "#b42318"
OK_GREEN = "#16714b"
UI_FONT = "Helvetica"
# Variables the monitor does not show
GREY = "#6b7480"
GREY_LIGHT = "#a3aab3"
OLIVE = "#7d7a1c"
OLIVE_LIGHT = "#b5b15a"

SOLID = "-"
DASHED = (0, (6, 4))
DASHDOT = (0, (7, 3, 1.5, 3))
DOTTED = (0, (1.5, 2.5))
SHORTDASH = (0, (3, 2.5))


# ==========================================================================
# What is plotted
# ==========================================================================

class Var:
    """One plottable variable: CSV column(s), how to compute it, how to draw it."""

    def __init__(self, key, label, group, color, style=SOLID, width=1.2, alpha=1.0,
                 default=False, columns=None, fn=None, step=False):
        self.key, self.label, self.group = key, label, group
        self.color, self.style, self.width, self.alpha = color, style, width, alpha
        self.default, self.step = default, step
        self.columns = tuple(columns or (key,))
        self.fn = fn

    def compute(self, cols):
        return self.fn(cols) if self.fn else cols[self.columns[0]]


class Group:
    """One subplot: variables with the same unit."""

    def __init__(self, key, ylabel, weight=1.0, ticks=None, floor=None, min_pad=0.5, short=None):
        self.key, self.ylabel, self.weight = key, ylabel, weight
        self.ticks, self.floor, self.min_pad = ticks, floor, min_pad
        self.short = short or ylabel           # y label for a small subplot
        # smallest readable height in pixels (tick labels must not overlap)
        self.min_px = max(36, 15 * len(ticks) + 6) if ticks else 50


class Source:
    """One instrument's logs: folder, file names, time column, variables."""

    def __init__(self, key, title, tag, color, folder, name_re, name_time, time_col, time_kind,
                 groups, variables, gap_s, nominal_s):
        self.key, self.title, self.tag, self.color = key, title, tag, color
        self.folder, self.name_re, self.name_time = folder, name_re, name_time
        self.time_col, self.time_kind = time_col, time_kind
        self.groups = OrderedDict((g.key, g) for g in groups)
        self.variables = variables
        self.gap_s, self.nominal_s = gap_s, nominal_s
        columns = [time_col]
        for var in variables:
            columns += [c for c in var.columns if c not in columns]
        self.columns = columns


TEXT_COLUMNS = {"frame_cooling": {"on": 1.0, "off": 0.0}}
ON_OFF = ((0, "off"), (1, "on"))


def local_name_time(match):
    y, mo, d, h, mi, s = (int(v) for v in match.groups()[:6])
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


def utc_name_time(match):
    y, mo, d, h, mi, s = (int(v) for v in match.groups()[:6])
    return calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0))


def mas_source(base, name, color):
    groups = [
        Group("hz", "Spin rate (Hz)", 1.0, floor=0, min_pad=2, short="Hz"),
        Group("mbar", "Pressure (mbar)", 1.0, min_pad=5, short="mbar"),
        Group("signal", "Signal (%)", 0.55, floor=0, min_pad=1, short="%"),
        Group("gain", "Gain", 0.55, min_pad=1),
        Group("fc", "Frame cool.", 0.4, ticks=ON_OFF, short="frame"),
    ]
    variables = [
        Var("spin_rate_hz", "Spin rate", "hz", color, width=1.3, default=True),
        Var("bearing_mbar", "Bearing", "mbar", BEARING, default=True),
        Var("drive_mbar", "Drive", "mbar", DRIVE, default=True),
        Var("bearing_sense_mbar", "Bearing sense", "mbar", BEARING_LIGHT, DASHED),
        Var("frame_cooling_set_mbar", "Frame cooling (set)", "mbar", GREY, DOTTED, width=1.4),
        Var("signal_level_pct", "Signal level", "signal", GREY),
        Var("gain", "Gain", "gain", OLIVE),
        Var("frame_cooling", "Frame cooling on/off", "fc", GREY, step=True),
    ]
    pattern = re.compile(r"^" + re.escape(name) + r"_(\d{4})-(\d\d)-(\d\d)_(\d\d)(\d\d)(\d\d)\.csv(\.gz)?$")
    return Source("mas:" + name, name, name, color, Path(base) / MAS_LOG_SUBDIR / name, pattern,
                  local_name_time, "unix_time", "unix", groups, variables, gap_s=10.0, nominal_s=1.0)


def _masked_temperature(channel):
    def fn(cols):
        temperature, status = cols["temp_%s_K" % channel], cols["status_%s" % channel]
        with np.errstate(invalid="ignore"):
            bad = (status > 0) | (status < 0)       # a blank (NaN) status keeps the reading
        return np.where(bad, NAN, temperature)
    return fn


def _ramp_rate(output):
    def fn(cols):
        enabled, rate = cols["out%d_ramp_enabled" % output], cols["out%d_ramp_rate_K_per_min" % output]
        return np.where(enabled == 1, rate, np.where(enabled == 0, 0.0, NAN))
    return fn


def lakeshore_source(base):
    groups = [
        Group("K", "Temperature (K)", 1.0, floor=0, min_pad=0.05, short="K"),
        Group("htr", "Heater (%)", 0.7, floor=0, min_pad=1, short="%"),
        Group("range", "Range", 0.5, ticks=((0, "Off"), (1, "Low"), (2, "Med"), (3, "High"))),
        Group("ramp", "Ramp (K/min)", 0.55, floor=0, min_pad=0.1, short="K/min"),
        Group("ramping", "Ramping", 0.4, ticks=((0, "no"), (1, "yes")), short="ramp"),
        Group("pid", "PID", 0.7, floor=0, min_pad=1),
        Group("htrst", "Heater fault", 0.5, ticks=((0, "none"), (1, "open"), (2, "short")), short="fault"),
    ]
    variables = [
        Var("temp_A_K", "Bearing temp. (A)", "K", BEARING, width=1.6, default=True,
            columns=("temp_A_K", "status_A"), fn=_masked_temperature("A")),
        Var("temp_B_K", "Drive temp. (B)", "K", DRIVE, width=1.6, default=True,
            columns=("temp_B_K", "status_B"), fn=_masked_temperature("B")),
        Var("out1_setpoint_K", "Bearing setpoint (out 1)", "K", BEARING, DASHED, alpha=0.7, default=True),
        Var("out2_setpoint_K", "Drive setpoint (out 2)", "K", DRIVE, DASHED, alpha=0.7, default=True),
        Var("temp_C_K", "Input C", "K", GREY, columns=("temp_C_K", "status_C"), fn=_masked_temperature("C")),
        Var("temp_D_K", "Input D", "K", OLIVE, columns=("temp_D_K", "status_D"), fn=_masked_temperature("D")),
        Var("out1_level_percent", "Bearing heater (out 1)", "htr", BEARING, width=1.0, alpha=0.45, default=True),
        Var("out2_level_percent", "Drive heater (out 2)", "htr", DRIVE, width=1.0, alpha=0.45, default=True),
        Var("out3_level_percent", "Output 3", "htr", GREY, DOTTED, width=1.4),
        Var("out4_level_percent", "Output 4", "htr", OLIVE, DOTTED, width=1.4),
        Var("out1_range_code", "Bearing heater range", "range", BEARING, step=True),
        Var("out2_range_code", "Drive heater range", "range", DRIVE, SHORTDASH, step=True),
        Var("out1_ramp_rate", "Bearing ramp rate", "ramp", BEARING, SHORTDASH,
            columns=("out1_ramp_enabled", "out1_ramp_rate_K_per_min"), fn=_ramp_rate(1)),
        Var("out2_ramp_rate", "Drive ramp rate", "ramp", DRIVE, SHORTDASH,
            columns=("out2_ramp_enabled", "out2_ramp_rate_K_per_min"), fn=_ramp_rate(2)),
        Var("out1_ramping", "Bearing ramping", "ramping", BEARING, step=True),
        Var("out2_ramping", "Drive ramping", "ramping", DRIVE, SHORTDASH, step=True),
        Var("out1_P", "Bearing P", "pid", BEARING),
        Var("out1_I", "Bearing I", "pid", BEARING, DASHED),
        Var("out1_D", "Bearing D", "pid", BEARING, DOTTED, width=1.4),
        Var("out2_P", "Drive P", "pid", DRIVE),
        Var("out2_I", "Drive I", "pid", DRIVE, DASHED),
        Var("out2_D", "Drive D", "pid", DRIVE, DOTTED, width=1.4),
        Var("out1_heater_status", "Bearing heater fault", "htrst", BEARING, step=True),
        Var("out2_heater_status", "Drive heater fault", "htrst", DRIVE, SHORTDASH, step=True),
    ]
    pattern = re.compile(r"^lakeshore336_(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)_\d{6}Z\.csv(\.gz)?$")
    return Source("ls", "Lake Shore 336", "lakeshore336", INK, Path(base) / LS_LOG_SUBDIR, pattern,
                  utc_name_time, "timestamp_utc", "iso", groups, variables, gap_s=15.0, nominal_s=5.0)


def ami_source(base, poll_s):
    groups = [
        Group("level", "LN2 level (%)", 1.0, floor=0, min_pad=1, short="%"),
        Group("fill", "Fill state", 0.5, ticks=((0, "idle"), (1, "filling"), (2, "timeout"), (3, "off")), short="fill"),
        Group("state", "On/off", 0.4, ticks=ON_OFF),
        Group("timeout", "Timeout (min)", 0.45, floor=0, min_pad=1, short="min"),
    ]
    variables = [
        Var("ln2_level", "LN2 level", "level", AMI_COLOR, width=1.6, default=True),
        Var("autofill_start", "Fill start", "level", AMI_COLOR, DASHED, alpha=0.8, default=True),
        Var("autofill_stop", "Fill stop", "level", AMI_COLOR, DASHDOT, alpha=0.8, default=True),
        Var("alarm1_setpoint", "Alarm 1 level", "level", GREY, DOTTED, width=1.4),
        Var("alarm2_setpoint", "Alarm 2 level", "level", OLIVE, DOTTED, width=1.4),
        Var("autofill_state", "Fill state", "fill", AMI_COLOR, step=True),
        Var("valve_open", "Valve open", "state", AMI_COLOR, step=True),
        Var("alarm", "Alarm", "state", GREY, SHORTDASH, step=True),
        Var("level_alarm", "Level alarm", "state", OLIVE, step=True),
        Var("timeout_alarm", "Timeout alarm", "state", GREY_LIGHT, DOTTED, width=1.4, step=True),
        Var("autofill_timeout", "Fill timeout", "timeout", GREY),
    ]
    pattern = re.compile(r"^ami1700_(\d{4})-(\d\d)-(\d\d)_(\d\d)(\d\d)(\d\d)\.csv(\.gz)?$")
    return Source("ami", "LN2 level (AMI 1700)", "ami1700", AMI_COLOR, Path(base) / AMI_LOG_SUBDIR, pattern,
                  local_name_time, "unix_time", "unix", groups, variables,
                  gap_s=max(3 * poll_s, 30.0), nominal_s=poll_s)


def build_sources(base):
    """MAS controllers in the config file's order (as in the monitor), then any other MAS log folders."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(str(Path(base) / CONFIG_NAME))      # read only; a missing file is fine
    except configparser.Error:
        pass
    names, ami_poll = [], 60.0
    for section in parser.sections():
        if section.lower() == "lakeshore336":
            continue
        if section.lower() == "ami1700":
            try:
                ami_poll = float(parser.get(section, "poll_seconds", fallback="60"))
            except ValueError:
                pass
            continue
        names.append(section)
    try:
        folders = sorted(p.name for p in (Path(base) / MAS_LOG_SUBDIR).iterdir() if p.is_dir())
    except OSError:
        folders = []
    names += [n for n in folders if n not in names]
    sources = [mas_source(base, name, MAS_COLORS[i % len(MAS_COLORS)]) for i, name in enumerate(names)]
    sources.append(lakeshore_source(base))
    sources.append(ami_source(base, ami_poll))
    return sources


# ==========================================================================
# Reading the logs
# ==========================================================================

def list_files(source, t0, t1):
    """Log files that may hold rows in [t0, t1]: (start, path), oldest first."""
    try:
        entries = list(os.scandir(str(source.folder)))
    except OSError:
        return []
    found = {}
    for entry in entries:
        match = source.name_re.match(entry.name)
        if not match:
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        stem = entry.name[:-3] if entry.name.endswith(".gz") else entry.name
        if stem in found and not entry.name.endswith(".gz"):
            continue          # being compressed right now: both copies exist; either will do
        found[stem] = (source.name_time(match), entry.path, stat.st_size, stat.st_mtime)
    files = sorted(found.values())
    # A file's rows run from the time in its name to its last write (gzip keeps that time).
    # The hour of slack covers local-time names around a daylight-saving change.
    return [f for f in files if f[0] <= t1 + 3660 and f[3] >= t0 - 60]


def _open_text(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", newline="", encoding="utf-8", errors="replace")
    return open(path, "r", newline="", encoding="utf-8", errors="replace")


def _last_line_complete(path):
    if path.endswith(".gz"):
        return True
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                return True
            handle.seek(max(0, handle.tell() - 65536))
            tail = handle.read().rstrip(b"\0")       # ignore a NUL-filled tail (see read_plain)
            return not tail or tail.endswith(b"\n")
    except OSError:
        return True


def read_plain(path, columns):
    """csv-module reader: (rows, {column: tuple of strings}) for the columns present."""
    with _open_text(path) as handle:
        # NUL bytes: the tail of a file that was being written during a power cut or hard reset
        reader = csv.reader(line.replace("\0", "") if "\0" in line else line for line in handle)
        header = next(reader, None)
        if not header:
            return 0, {}
        index = {name: i for i, name in enumerate(header)}
        present = [c for c in columns if c in index]
        if not present:
            return 0, {}
        width = len(header)
        getter = operator.itemgetter(*[index[c] for c in present])
        rows = [getter(row) for row in reader if len(row) == width]
    if not rows:
        return 0, {}
    if len(present) == 1:
        rows = [(r,) for r in rows]
    return len(rows), dict(zip(present, zip(*rows)))


def read_pandas(path, columns):
    """pandas reader: (rows, {column: Series}) for the columns present."""
    wanted = set(columns)
    options = dict(usecols=lambda c: c in wanted, low_memory=False)
    major_minor = tuple(int(p) for p in re.findall(r"\d+", pd.__version__)[:2])
    if major_minor >= (1, 3):
        options["on_bad_lines"] = "skip"
    else:
        options["error_bad_lines"] = False
        options["warn_bad_lines"] = False
    try:
        frame = pd.read_csv(path, **options)
    except pd.errors.EmptyDataError:
        return 0, {}
    return len(frame), {c: frame[c] for c in frame.columns}


def _is_series(values):
    return pd is not None and isinstance(values, pd.Series)


def to_numbers(values):
    if _is_series(values):
        return pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    strings = np.array(values)
    try:
        return np.where(strings == "", "nan", strings).astype(float)
    except ValueError:
        out = np.empty(len(values))
        for i, text in enumerate(values):
            try:
                out[i] = float(text)
            except ValueError:
                out[i] = NAN
        return out


def text_to_numbers(values, mapping):
    if _is_series(values):
        return values.astype(str).str.strip().str.lower().map(mapping).to_numpy(dtype=float)
    return np.array([mapping.get(v.strip().lower(), NAN) for v in values], dtype=float)


ISO_RE = re.compile(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.(\d{1,6}))?(Z|[+-]\d\d:?\d\d)?$")


def iso_epoch(text):
    match = ISO_RE.match(text.strip())
    if not match:
        return NAN
    y, mo, d, h, mi, s, fraction, zone = match.groups()
    epoch = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(s), 0, 0, 0))
    epoch += int((fraction or "0").ljust(6, "0")) / 1e6
    if zone and zone != "Z":
        digits = zone[1:].replace(":", "")
        epoch -= (int(digits[:2]) * 3600 + int(digits[2:]) * 60) * (1 if zone[0] == "+" else -1)
    elif zone is None:
        epoch = time.mktime((int(y), int(mo), int(d), int(h), int(mi), int(s), 0, 0, -1)) + (epoch % 1)
    return epoch


def iso_to_epochs(values):
    """UTC ISO time stamps ('2026-10-28T04:27:35.486+00:00') to epoch seconds."""
    if _is_series(values):
        stamps = pd.to_datetime(values, utc=True, errors="coerce")
        nat = stamps.isna().to_numpy()
        epochs = np.asarray(stamps.values).astype("datetime64[ns]").astype("int64") / 1e9
        epochs[nat] = NAN
        return epochs
    if all(v.endswith("+00:00") and len(v) == 29 for v in values):
        try:
            return np.array([v[:23] for v in values], dtype="datetime64[ms]").astype("int64") / 1000.0
        except ValueError:
            pass
    return np.array([iso_epoch(v) for v in values], dtype=float)


def read_file(source, path, use_pandas):
    """One log file -> (epoch seconds, {var key: values}), time-ordered."""
    if use_pandas:
        try:
            count, cols = read_pandas(path, source.columns)
        except Exception:            # e.g. a damaged file; the csv-module reader skips what it cannot use
            count, cols = read_plain(path, source.columns)
    else:
        count, cols = read_plain(path, source.columns)
    if count and not _last_line_complete(path):
        count -= 1                       # the monitor is writing that line right now
    empty = np.zeros(0)
    if count <= 0 or source.time_col not in cols:
        return empty, {v.key: empty for v in source.variables}
    raw_time = cols[source.time_col]
    t = to_numbers(raw_time) if source.time_kind == "unix" else iso_to_epochs(raw_time)
    numbers = {}
    for column in source.columns[1:]:
        if column not in cols:
            numbers[column] = np.full(len(t), NAN)   # e.g. older MAS files without pressures
        elif column in TEXT_COLUMNS:
            numbers[column] = text_to_numbers(cols[column], TEXT_COLUMNS[column])
        else:
            numbers[column] = to_numbers(cols[column])
    keep = np.isfinite(t)
    keep[count:] = False
    if not keep.all():
        t = t[keep]
        numbers = {k: v[keep] for k, v in numbers.items()}
    if t.size > 1 and np.any(np.diff(t) < 0):
        order = np.argsort(t, kind="mergesort")
        t = t[order]
        numbers = {k: v[order] for k, v in numbers.items()}
    values = {}
    with np.errstate(invalid="ignore"):
        for var in source.variables:
            values[var.key] = np.asarray(var.compute(numbers), dtype=float)
    return t, values


def bin_file(t, values, width):
    """Per-bin min and max of each variable; bins are aligned to multiples of width (epoch seconds)."""
    if t.size == 0:
        return np.zeros(0, dtype=np.int64), {}, {}
    ids = np.floor(t / width).astype(np.int64)
    starts = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]])
    lows, highs = {}, {}
    with np.errstate(all="ignore"):
        for key, v in values.items():
            lows[key] = np.fmin.reduceat(v, starts)
            highs[key] = np.fmax.reduceat(v, starts)
    return ids[starts], lows, highs


def choose_bin_width(span):
    for width in BIN_WIDTHS_S:
        if span / width <= TARGET_BINS:
            return width
    return BIN_WIDTHS_S[-1]


def envelope(x, y, max_points):
    """Per-time-bin min/max pairs of a long series, broken at missing readings and empty bins."""
    if len(x) <= max_points or x[-1] <= x[0]:
        return x, y
    width = (x[-1] - x[0]) / (max_points // 3)
    bins = np.floor((x - x[0]) / width).astype(int)
    starts = np.flatnonzero(np.r_[True, bins[1:] != bins[:-1]])
    with np.errstate(all="ignore"):
        lows = np.fmin.reduceat(y, starts)
        highs = np.fmax.reduceat(y, starts)
    has_nan = np.add.reduceat(np.isnan(y).astype(int), starts) > 0
    ids = bins[starts]
    breaks = has_nan | np.r_[ids[1:] > ids[:-1] + 1, False]
    xs = np.repeat(x[starts], 3)
    ys = np.empty(3 * len(starts))
    ys[0::3], ys[1::3] = lows, highs
    ys[2::3] = np.where(breaks, NAN, highs)
    return xs, ys


class FileCache:
    """Parsed files, keyed by path, size, time stamp and bin width; least recently used dropped first."""

    def __init__(self, budget):
        self.budget = budget
        self.items = OrderedDict()
        self.size = 0
        self.lock = threading.Lock()

    @staticmethod
    def _nbytes(piece):
        total = 0
        for part in piece:
            if isinstance(part, np.ndarray):
                total += part.nbytes
            elif isinstance(part, dict):
                total += sum(a.nbytes for a in part.values())
        return total

    def has(self, key):
        with self.lock:
            return key in self.items

    def get(self, key):
        with self.lock:
            item = self.items.pop(key, None)
            if item is None:
                return None
            self.items[key] = item
            return item[0]

    def put(self, key, piece):
        nbytes = self._nbytes(piece)
        with self.lock:
            for old in [k for k in self.items if k[:2] == key[:2] and k[-1] == key[-1]]:
                self.size -= self.items.pop(old)[1]       # an older version of the same file
            self.items[key] = (piece, nbytes)
            self.size += nbytes
            while self.size > self.budget and len(self.items) > 1:
                self.size -= self.items.popitem(last=False)[1][1]


class Loaded:
    """One source's data for one range, ready to draw."""

    def __init__(self, source, t0, t1, mode, width, files, rows, t=None, values=None, ids=None, lows=None, highs=None):
        self.source, self.t0, self.t1 = source, t0, t1
        self.mode, self.width, self.files, self.rows = mode, width, files, rows
        self.t, self.values = t, values
        self.curves = {}
        if mode == "binned":
            x = (ids + 0.5) * width
            gap_bins = max(1, int(math.ceil(source.gap_s / width)))
            breaks = np.r_[np.diff(ids) > gap_bins, True] if ids.size else np.zeros(0, dtype=bool)
            xs = np.repeat(x, 3)
            for key in lows:
                ys = np.empty(3 * ids.size)
                ys[0::3], ys[1::3] = lows[key], highs[key]
                ys[2::3] = np.where(breaks, NAN, highs[key])
                self.curves[key] = (xs, ys)
        self.has_rows = rows > 0

    def covers(self, a, b):
        return self.t0 - 1 <= a and b <= self.t1 + 1

    def curve(self, key, a, b):
        if self.mode == "binned":
            return self.curves.get(key, (np.zeros(0), np.zeros(0)))
        t = self.t
        i0 = max(0, int(np.searchsorted(t, a)) - 1)
        i1 = min(t.size, int(np.searchsorted(t, b)) + 1)
        x, y = t[i0:i1], self.values[key][i0:i1]
        if x.size > DRAW_MAX_POINTS:
            x, y = envelope(x, y, DRAW_MAX_POINTS)
        return x, y

    def describe(self):
        if not self.has_rows:
            return "no data in this range"
        if self.mode == "full":
            return "full resolution, {:,} rows".format(self.rows)
        return "min/max per {}, {:,} rows read".format(duration_text(self.width), self.rows)


def text_size(path, size):
    """Bytes of CSV text in a log file; for .gz the uncompressed size stored in its last 4 bytes."""
    if not path.endswith(".gz"):
        return size
    try:
        with open(path, "rb") as handle:
            handle.seek(-4, 2)
            return int.from_bytes(handle.read(4), "little") or size * 8
    except OSError:
        return size * 8


def span_text(seconds):
    if seconds >= 2 * 86400:
        return "{:.0f} days".format(seconds / 86400)
    if seconds >= 2 * 3600:
        return "{:.0f} hours".format(seconds / 3600)
    return "{:.0f} minutes".format(max(1, seconds / 60))


def seconds_text(seconds):
    if seconds < 90:
        return "{:.0f} s".format(seconds)
    return "{:.0f} min {:02.0f} s".format(seconds // 60, seconds % 60)


def duration_text(seconds):
    for unit, size in (("d", 86400), ("h", 3600), ("min", 60)):
        if seconds >= size and seconds % size == 0:
            return "{} {}".format(seconds // size, unit)
    return "{} s".format(seconds)


class Cancelled(Exception):
    pass


def load_source(source, t0, t1, use_pandas, cache, files, check, step):
    """Read the files of one source for [t0, t1]; full resolution when short enough, else min/max bins."""
    span = t1 - t0
    full = span / source.nominal_s <= FULL_RES_MAX_ROWS
    width = None if full else choose_bin_width(span)
    pieces, rows = [], 0
    for start, path, size, mtime in files:
        check()
        key = (source.key, path, size, mtime, use_pandas, width)
        piece = cache.get(key)
        if piece is None:
            try:
                t, values = read_file(source, path, use_pandas)
            except FileNotFoundError:            # compressed by the monitor since it was listed
                if not path.endswith(".gz") and os.path.exists(path + ".gz"):
                    t, values = read_file(source, path + ".gz", use_pandas)
                else:
                    t, values = np.zeros(0), {}
            except (OSError, EOFError, csv.Error, ValueError, UnicodeError) as error:
                print("Could not read {}: {}".format(path, error), file=sys.stderr)
                t, values = np.zeros(0), {}
            piece = (t, values) if full else bin_file(t, values, width) + (t.size,)
            cache.put(key, piece)
        pieces.append(piece)
        step()
    empty = np.zeros(0)
    if full:
        pieces = [p for p in pieces if p[0].size]
        if pieces:
            t = np.concatenate([p[0] for p in pieces])
            values = {v.key: np.concatenate([p[1][v.key] for p in pieces]) for v in source.variables}
        else:
            t, values = empty, {v.key: empty for v in source.variables}
        if t.size > 1 and np.any(np.diff(t) < 0):
            order = np.argsort(t, kind="mergesort")
            t, values = t[order], {k: v[order] for k, v in values.items()}
        inside = (t >= t0 - source.gap_s) & (t <= t1 + source.gap_s)
        t, values = t[inside], {k: v[inside] for k, v in values.items()}
        rows = t.size
        gaps = np.flatnonzero(np.diff(t) > source.gap_s) + 1 if t.size > 1 else np.zeros(0, dtype=int)
        if gaps.size:
            t = np.insert(t, gaps, (t[gaps - 1] + t[gaps]) / 2)
            values = {k: np.insert(v, gaps, NAN) for k, v in values.items()}
        return Loaded(source, t0, t1, "full", None, len(files), rows, t=t, values=values)
    pieces = [p for p in pieces if p[0].size]
    rows = sum(p[3] for p in pieces)
    if pieces:
        ids = np.concatenate([p[0] for p in pieces])
        lows = {v.key: np.concatenate([p[1][v.key] for p in pieces]) for v in source.variables}
        highs = {v.key: np.concatenate([p[2][v.key] for p in pieces]) for v in source.variables}
        if ids.size > 1 and np.any(np.diff(ids) <= 0):          # files sharing a bin, or out of order
            order = np.argsort(ids, kind="mergesort")
            ids = ids[order]
            starts = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]])
            with np.errstate(all="ignore"):
                lows = {k: np.fmin.reduceat(v[order], starts) for k, v in lows.items()}
                highs = {k: np.fmax.reduceat(v[order], starts) for k, v in highs.items()}
            ids = ids[starts]
        inside = (ids >= math.floor(t0 / width) - 1) & (ids <= math.floor(t1 / width) + 1)
        ids = ids[inside]
        lows = {k: v[inside] for k, v in lows.items()}
        highs = {k: v[inside] for k, v in highs.items()}
    else:
        ids = np.zeros(0, dtype=np.int64)
        lows = {v.key: empty for v in source.variables}
        highs = dict(lows)
    return Loaded(source, t0, t1, "binned", width, len(files), rows, ids=ids, lows=lows, highs=highs)


def format_value(value):
    return "" if value != value else repr(float(value))


def export_source(source, keys, a, b, use_pandas, folder, check, step):
    """Full-resolution rows in [a, b] of the ticked variables, written as one CSV; returns (path, rows)."""
    files = list_files(source, a, b)
    start = datetime.fromtimestamp(a).strftime("%Y%m%d-%H%M%S")
    stop = datetime.fromtimestamp(b).strftime("%Y%m%d-%H%M%S")
    path = folder / "{}_{}_to_{}.csv".format(source.tag, start, stop)
    rows = 0
    with open(str(path), "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_local", "unix_time"] + keys)
        for _start, file_path, _size, _mtime in files:
            check()
            try:
                t, values = read_file(source, file_path, use_pandas)
            except FileNotFoundError:
                gz = file_path + ".gz"
                t, values = read_file(source, gz, use_pandas) if os.path.exists(gz) else (np.zeros(0), {})
            inside = (t >= a) & (t <= b)
            t = t[inside]
            columns = [values[k][inside] for k in keys] if t.size else []
            for i in range(t.size):
                stamp = datetime.fromtimestamp(t[i]).isoformat(timespec="milliseconds")
                writer.writerow([stamp, "{:.3f}".format(t[i])] + [format_value(c[i]) for c in columns])
            rows += t.size
            step()
    return path, rows


# ==========================================================================
# Window
# ==========================================================================

def parse_local(text):
    text = text.strip()
    if text.lower() == "now":
        return time.time()
    for fmt in TIME_FORMATS:
        try:
            return time.mktime(datetime.strptime(text, fmt).timetuple())
        except ValueError:
            pass
    raise ValueError("use YYYY-MM-DD HH:MM, e.g. {}".format(datetime.now().strftime("%Y-%m-%d %H:%M")))


def format_local(epoch):
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


def to_plot(x):
    return x / 86400.0 + EPOCH_NUM


def from_plot(value):
    return (value - EPOCH_NUM) * 86400.0


def blend(color, alpha, background="#ffffff"):
    """A colour mixed with the background, for the sidebar swatches of faint lines."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    br, bg, bb = (int(background[i:i + 2], 16) for i in (1, 3, 5))
    mix = [round(alpha * c + (1 - alpha) * back) for c, back in ((r, br), (g, bg), (b, bb))]
    return "#{:02x}{:02x}{:02x}".format(*mix)


def swatch_color(var, on=True):
    if not on:
        return "#3a424d" if THEME["dark"] else "#d5dae0"
    return blend(theme_color(var.color, "plot"), var.alpha, "#1b222c" if THEME["dark"] else "#ffffff")


def tk_dash(style):
    if style == SOLID:
        return ()
    return tuple(max(1, int(round(v))) for v in style[1])


# ==========================================================================
# Dark mode (the same code is in dnp_monitor.py and dnp_logviewer.py)
#
# Colours stay written as the light-mode values everywhere else. In dark
# mode every Tk colour option is translated on its way to Tk (one hook in
# tkinter's option handling), with separate tables for backgrounds and
# for text, so a colour used as a banner background and as text colour
# (INK) gets a suitable dark-mode value in each role. Switching walks the
# existing widgets once; matplotlib figures are recoloured the same way.
# The choice is remembered in THEME_FILE, shared by both programs.
# ==========================================================================

THEME_FILE = Path.home() / ".dnp_monitor_theme"
THEME = {"dark": False}

_DARK_BG = {          # light background -> dark background
    "#f4f7fb": "#1b222c",   # panels
    "#ffffff": "#0f141a",   # white boxes, plot areas, entries
    "white": "#0f141a",
    "#e8edf3": "#2a323d",   # disabled fields and buttons
    "#d9d9d9": "#2b333e",   # Tk default
    "#ececec": "#3a4552",   # Tk default active
    "#e4ebf4": "#36414e",
    "#dcecf8": "#1f3a52",   # Apply, when there is something to apply
    "#ffe3a3": "#5a4512",   # edited, not yet applied
    "#fff4d6": "#4a3d1a",   # "Loading" box
    "#26364a": "#0b1118",   # dark banners and bars
    "#7b8794": "#55606d",   # selected while locked
}
_DARK_FG = {          # light-mode text colour -> dark-mode text colour
    "#000000": "#d6dde6",
    "black": "#d6dde6",
    "#26364a": "#dfe6ee",   # INK
    "#526277": "#9aabbd",   # MUTED
    "#b42318": "#ff7b72",   # errors
    "#16714b": "#4cc38a",   # OK
    "#a3adb8": "#5d6773",   # disabled
    "#a3a3a3": "#5e6874",   # Tk default disabled
    "#a3aab3": "#5f6975",
    "#b26a00": "#f0a93b",
    "#5b2a86": "#b88cf0",   # MAS controller colours
    "#1b7a3e": "#4cc77f",
    "#8a5a00": "#e0a63a",
    "#0f7f8c": "#33c1d1",   # LN2
    "#0072b2": "#4aa8ff",   # bearing
    "#d55e00": "#ff8c42",   # drive
}
_DARK_PLOT = {        # matplotlib colours
    "#ffffff": "#0f141a",
    "#000000": "#c9d1d9",
    "#b0b0b0": "#6e7681",   # grid
    "#cccccc": "#444c56",   # legend frame
    "#26364a": "#dfe6ee",
    "#526277": "#9aabbd",
    "#b42318": "#ff7b72",
    "#5b2a86": "#b88cf0",
    "#1b7a3e": "#4cc77f",
    "#8a5a00": "#e0a63a",
    "#0f7f8c": "#33c1d1",
    "#0072b2": "#4aa8ff",
    "#d55e00": "#ff8c42",
    "#56b4e9": "#8fd0ff",   # viewer: bearing sense
    "#6b7480": "#9aa4b0",   # viewer: greys and olives
    "#a3aab3": "#6c7580",
    "#7d7a1c": "#c2be5a",
    "#b5b15a": "#8a8640",
}
_DARK_SELECT = {      # 'selectcolor': the fill of a selected segment button (INK in light mode)
    "#26364a": "#3a6ea5",
    "#7b8794": "#55606d",
    "#ffffff": "#0f141a",
    "#f4f7fb": "#1b222c",   # image check boxes (no indicator) take the panel colour
    "#d9d9d9": "#2b333e",
}
_LIGHT_SELECT = {dark: light for light, dark in _DARK_SELECT.items()}
_LIGHT_BG = {dark: light for light, dark in _DARK_BG.items() if light != "white"}
_LIGHT_FG = {dark: light for light, dark in _DARK_FG.items() if light != "black"}
_LIGHT_PLOT = {dark: light for light, dark in _DARK_PLOT.items()}
_BG_OPTIONS = ("background", "bg", "activebackground", "highlightbackground", "selectcolor",
               "disabledbackground", "readonlybackground", "troughcolor", "selectbackground")
_FG_OPTIONS = ("foreground", "fg", "activeforeground", "disabledforeground", "insertbackground",
               "highlightcolor", "selectforeground")
_BG_SET, _FG_SET = set(_BG_OPTIONS), set(_FG_OPTIONS)


def _brightness(hex_color):
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return None
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _dark_value(name, hex_color, widget_class=""):
    """Dark-mode value of one colour option: from the tables, or else, for colours the program never
    sets itself (the desktop's own defaults, e.g. KDE's #232627 text on #eff0f1), by brightness."""
    if name == "selectcolor":
        new = _DARK_SELECT.get(hex_color)
    elif name in _BG_SET:
        new = _DARK_BG.get(hex_color)
    else:
        new = _DARK_FG.get(hex_color)
    if new is not None:
        return new
    level = _brightness(hex_color)
    if level is None:
        return None
    if widget_class == "Scrollbar" and name in ("background", "activebackground") and level > 0.6:
        return "#4a5563" if name == "background" else "#5c6878"
    if name == "troughcolor" and level > 0.6:
        return "#161c24"
    if name == "selectcolor" and level > 0.75:
        return "#0f141a"
    if name in _BG_SET and level > 0.75:
        return "#2b333e"
    if name == "disabledforeground" and level < 0.3:
        return "#6b7480"
    if name in _FG_SET and name != "disabledforeground" and level < 0.35:
        return "#d6dde6"
    return None


def _translate(widget, options):
    if not isinstance(options, dict):
        return options
    out = {}
    for key, value in options.items():
        name = key.rstrip("_")
        if name == "bg":
            name = "background"
        elif name == "fg":
            name = "foreground"
        if isinstance(value, str) and value and (name in _BG_SET or name in _FG_SET):
            new = _dark_value(name, _hex(widget, value))
            if new is not None:
                value = new
        out[key] = value
    return out


_tk_options = tk.Misc._options


def _themed_options(self, cnf, kw=None):
    if THEME["dark"]:
        root = self._root()
        cnf, kw = _translate(root, cnf), _translate(root, kw)
    return _tk_options(self, cnf, kw)


tk.Misc._options = _themed_options


def theme_color(color, role="fg"):
    """A light-mode colour as it should be shown now (role: 'fg', 'bg' or 'plot')."""
    if not THEME["dark"]:
        return color
    table = {"fg": _DARK_FG, "bg": _DARK_BG, "plot": _DARK_PLOT}[role]
    return table.get(color.lower(), color)


def _hex(widget, value):
    value = str(value).strip().lower()
    if not value or value.startswith("#") and len(value) == 7:
        return value
    try:
        r, g, b = widget.winfo_rgb(value)
    except tk.TclError:
        return value
    return "#{:02x}{:02x}{:02x}".format(r >> 8, g >> 8, b >> 8)


_ORIGINAL_COLORS = {}   # (widget path, option) -> (light-mode value, the dark value put in its place)


def recolor_widgets(root, dark):
    """Translate the colour options of every existing widget (bypassing the hook). Going back to
    light restores the values saved on the way to dark. Toolbar icons: recolor_toolbar()."""
    bg_table, fg_table = _LIGHT_BG, _LIGHT_FG
    select_table = _LIGHT_SELECT
    stack = [root]
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        try:
            available = widget.configure()
        except tk.TclError:
            continue
        if not available:
            continue
        for name in _BG_OPTIONS + _FG_OPTIONS:
            if name not in available or name in ("bg", "fg"):
                continue
            try:
                value = _hex(widget, widget.cget(name))
            except tk.TclError:
                continue
            key = (widget._w, name)
            if dark:
                new = _dark_value(name, value, widget.winfo_class())
                if new is not None:
                    _ORIGINAL_COLORS[key] = (value, new)
            else:
                original, applied = _ORIGINAL_COLORS.pop(key, (None, None))
                if original is not None and value == applied:
                    new = original
                else:          # set while dark through the hook: undo the table translation
                    table = select_table if name == "selectcolor" else bg_table if name in _BG_SET else fg_table
                    new = table.get(value)
            if new is not None:
                try:
                    widget.tk.call(widget._w, "configure", "-" + name, new)
                except tk.TclError:
                    pass


_TOOLBAR_ICONS = {}     # toolbar button -> (light image, light select image, light-on-dark image, dimmed one)


def recolor_toolbar(toolbar, dark):
    """Light toolbar icons on the dark toolbar, made from matplotlib's own PNG icons. Tk draws a
    disabled icon with a light checkerboard, so in dark mode Back/Forward are never disabled: with
    nothing to go back or forward to they show a dimmed icon instead (and a click does nothing)."""
    import base64
    import io
    import matplotlib
    import matplotlib.image as mimage
    names = {item[0]: item[2] for item in toolbar.toolitems if item[0] is not None and item[2]}
    names = {text: os.path.splitext(os.path.basename(str(name)))[0] for text, name in names.items()}
    folder = os.path.join(matplotlib.get_data_path(), "images")
    surface = np.array([0x2b, 0x33, 0x3e]) / 255.0            # the dark toolbar colour
    for text, button in getattr(toolbar, "_buttons", {}).items():
        key = str(button)
        if key not in _TOOLBAR_ICONS:
            try:
                light = str(button.cget("image"))
                light_select = str(button.cget("selectimage")) if "selectimage" in button.configure() else ""
                width = int(button.tk.call("image", "width", light))
                pixels = None
                for suffix in ("", "_large"):     # the smallest icon file at least as large as the button image
                    path = os.path.join(folder, names[text] + suffix + ".png")
                    if os.path.exists(path):
                        pixels = mimage.imread(path)
                        if pixels.shape[1] >= width:
                            break
                rows = (np.arange(width) * pixels.shape[0] / width).astype(int)
                cols = (np.arange(width) * pixels.shape[1] / width).astype(int)
                pixels = np.array(pixels[rows][:, cols], dtype=float)
                alpha = pixels[..., 3:4] if pixels.shape[2] == 4 else np.ones(pixels.shape[:2] + (1,))
                made = []
                for brightness in (0.85, 0.3):                           # normal, dimmed
                    ink = brightness * (1 - pixels[..., :3]) + 0.1       # black -> light grey
                    flat = ink * alpha + surface * (1 - alpha)
                    buffer = io.BytesIO()
                    mimage.imsave(buffer, np.clip(flat, 0, 1), format="png")
                    made.append(tk.PhotoImage(master=toolbar, format="png",
                                              data=base64.b64encode(buffer.getvalue()).decode("ascii")))
            except Exception:
                continue
            _TOOLBAR_ICONS[key] = (light, light_select, made[0], made[1])
        light, light_select, dark_image, _dim = _TOOLBAR_ICONS[key]
        try:
            if dark:
                button.configure(image=dark_image)
                if light_select:
                    button.configure(selectimage=dark_image)
            else:
                button.configure(image=light)
                if light_select:
                    button.configure(selectimage=light_select)
        except tk.TclError:
            pass
    if not hasattr(toolbar, "_theme_history"):
        original = toolbar.set_history_buttons

        def set_history_buttons():
            original()
            if not THEME["dark"]:
                return
            for text in ("Back", "Forward"):
                button = getattr(toolbar, "_buttons", {}).get(text)
                icons = _TOOLBAR_ICONS.get(str(button))
                if button is None or icons is None:
                    continue
                usable = str(button.cget("state")) != "disabled"
                button.configure(state="normal", image=icons[2] if usable else icons[3])
                button._theme_usable = usable
        toolbar._theme_history = original
        toolbar.set_history_buttons = set_history_buttons
    if dark:
        toolbar.set_history_buttons()
    else:
        toolbar._theme_history()


def recolor_figure(figure, dark):
    """Translate the colours of every artist in a matplotlib figure; also sets the colours of future ticks."""
    from matplotlib.colors import to_hex, to_rgba
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.text import Text
    table = _DARK_PLOT if dark else _LIGHT_PLOT

    def mapped(color):
        try:
            rgba = to_rgba(color)
        except (TypeError, ValueError):
            return color
        new = table.get(to_hex(rgba, keep_alpha=False))
        return color if new is None else to_rgba(new, rgba[3])

    figure.set_facecolor(mapped(figure.get_facecolor()))
    for artist in figure.findobj():
        if isinstance(artist, Text):
            artist.set_color(mapped(artist.get_color()))
        elif isinstance(artist, Line2D):
            artist.set_color(mapped(artist.get_color()))
            artist.set_markerfacecolor(mapped(artist.get_markerfacecolor()))
            artist.set_markeredgecolor(mapped(artist.get_markeredgecolor()))
        elif isinstance(artist, Patch):
            artist.set_facecolor(mapped(artist.get_facecolor()))
            artist.set_edgecolor(mapped(artist.get_edgecolor()))
    ink = "#c9d1d9" if dark else "#000000"
    for ax in figure.axes:
        ax.tick_params(axis="both", which="both", colors=ink, grid_color="#6e7681" if dark else "#b0b0b0")


def load_theme():
    try:
        return THEME_FILE.read_text().strip() == "dark"
    except OSError:
        return False


def save_theme(dark):
    try:
        THEME_FILE.write_text("dark\n" if dark else "light\n")
    except OSError:
        pass


class ViewerApp:
    def __init__(self, root, args, sources):
        self.root = root
        self.args = args
        self.base = Path(args.base_dir)
        self.sources = sources
        self.use_pandas = pd is not None and not args.no_pandas
        self.cache = FileCache(CACHE_BUDGET_BYTES)
        self.events = queue.Queue()
        self.generation = 0
        self.busy = False
        self.loaded = {}
        self.view = None
        self.history = []
        self.last_load_s = 0.0
        self.refresh_job = None
        self.zoom_job = None
        self.setting_limits = False
        self.user_y = set()
        self.axes_info = []
        self.panels = []
        self.reset_y = True
        self.exporting = False
        self.loading = None
        self.learned_speed = None
        try:
            kind, value = SPEED_FILE.read_text().split()
            if kind == ("pandas" if self.use_pandas else "csv"):
                self.learned_speed = float(value)
        except (OSError, ValueError):
            pass
        self.snapshot_done = False

        root.title("DNP log viewer")
        root.report_callback_exception = self._callback_error
        root.configure(bg=PANEL_BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.var_states = OrderedDict()
        for source in sources:
            for var in source.variables:
                self.var_states[(source.key, var.key)] = tk.BooleanVar(master=root, value=var.default)

        self._build_top_bar()
        self._build_status_bar()
        body = tk.Frame(root, bg=PANEL_BG)
        body.pack(side="top", fill="both", expand=True)
        self._build_sidebar(body)
        self._build_plot(body)
        style = ttk.Style(root)
        self.progress_style = {key: style.lookup("Horizontal.TProgressbar", key) or style.lookup("TProgressbar", key)
                               for key in ("troughcolor", "background")}
        self.progress_style = {k: v for k, v in self.progress_style.items() if v}
        if load_theme():
            self.dark_var.set(True)
            self.set_dark(True)

        now = time.time()
        if args.start:
            t0 = parse_local(args.start)
            t1 = parse_local(args.stop) if args.stop else now
            self.now_var.set(not args.stop)
        else:
            t0, t1 = now - DEFAULT_SPAN_S, now
            self.now_var.set(True)
        self.span = t1 - t0
        self._now_toggled(load=False)
        self.root.after(100, self._poll_events)
        self.load(t0, t1, push_history=False)

    # ---- layout ---------------------------------------------------------

    def _button(self, parent, text, command, width=None, bold=False):
        button = tk.Button(parent, text=text, command=command, font=(UI_FONT, 10, "bold" if bold else "normal"),
                           padx=6, pady=1, bg="white", activebackground="#e4ebf4", relief="raised", bd=1)
        if width:
            button.configure(width=width)
        return button

    def _build_top_bar(self):
        bar = tk.Frame(self.root, bg=PANEL_BG, padx=8, pady=6)
        bar.pack(side="top", fill="x")
        font = (UI_FONT, 10)
        self.dark_var = tk.BooleanVar(master=self.root, value=False)
        tk.Checkbutton(bar, text="Dark mode", variable=self.dark_var, command=self.dark_clicked, bg=PANEL_BG,
                       fg=INK, activebackground=PANEL_BG, font=(UI_FONT, 9, "bold"), highlightthickness=0,
                       cursor="hand2").pack(side="left", padx=(0, 16))
        tk.Label(bar, text="From", bg=PANEL_BG, fg=INK, font=font).pack(side="left")
        self.from_entry = tk.Entry(bar, width=17, font=(UI_FONT, 11), justify="center")
        self.from_entry.pack(side="left", padx=(4, 10))
        tk.Label(bar, text="To", bg=PANEL_BG, fg=INK, font=font).pack(side="left")
        self.to_entry = tk.Entry(bar, width=17, font=(UI_FONT, 11), justify="center",
                                 disabledbackground="#e8edf3", disabledforeground=MUTED)
        self.to_entry.pack(side="left", padx=(4, 2))
        # "Now" sits right next to the To field it controls; clicking the greyed-out field also releases it
        self.now_var = tk.BooleanVar(master=self.root, value=True)
        tk.Checkbutton(bar, text="Now", variable=self.now_var, command=self._now_toggled, bg=PANEL_BG,
                       fg=INK, font=(UI_FONT, 10, "bold"), activebackground=PANEL_BG).pack(side="left", padx=(0, 8))
        self.to_entry.bind("<Button-1>", self._to_clicked)
        for entry in (self.from_entry, self.to_entry):
            entry.bind("<Return>", lambda _e: self.load_from_entries())
        self.load_button = self._button(bar, "Load", self.load_or_cancel, width=6, bold=True)
        self.load_button.pack(side="left", padx=(0, 14))
        tk.Label(bar, text="Last", bg=PANEL_BG, fg=MUTED, font=font).pack(side="left", padx=(0, 4))
        self.range_buttons = []
        for label, seconds in PRESETS:
            button = self._button(bar, label, lambda s=seconds: self.preset(s), width=4)
            button.pack(side="left", padx=1)
            self.range_buttons.append(button)
        self.back_button = self._button(bar, "< Previous range", self.previous_range)
        self.back_button.pack(side="left", padx=(14, 0))
        self.range_buttons.append(self.back_button)
        exports = tk.Frame(bar, bg=PANEL_BG)
        exports.pack(side="right")
        buttons = tk.Frame(exports, bg=PANEL_BG)
        buttons.pack(side="top", anchor="e")
        self._button(buttons, "Export CSV", self.export_csv).pack(side="left", padx=(0, 4))
        self._button(buttons, "Export PNG", self.export_png).pack(side="left")
        tk.Label(exports, text="both save the time span on screen", bg=PANEL_BG, fg=MUTED,
                 font=(UI_FONT, 8)).pack(side="top", anchor="e")

    def _build_status_bar(self):
        bar = tk.Frame(self.root, bg=PANEL_BG, padx=8, pady=3)
        bar.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(bar, length=220, mode="determinate", maximum=1.0)
        self.progress.pack(side="right")
        self.status = tk.Label(bar, text="", bg=PANEL_BG, fg=MUTED, font=(UI_FONT, 9), anchor="w")
        self.status.pack(side="left", fill="x", expand=True)

    def _build_sidebar(self, parent):
        outer = tk.Frame(parent, bg=PANEL_BG, width=250)
        outer.pack(side="left", fill="y")
        outer.pack_propagate(False)
        canvas = tk.Canvas(outer, bg=PANEL_BG, highlightthickness=0, width=232)
        scroll = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        bottom = tk.Frame(outer, bg=PANEL_BG)
        bottom.pack(side="bottom", fill="x", pady=6)
        self._button(bottom, "Default selection", self.default_selection).pack()
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=PANEL_BG)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))

        def wheel(event):
            if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
                canvas.yview_scroll(-2, "units")
            else:
                canvas.yview_scroll(2, "units")

        def bind_wheel(_event):
            for sequence in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
                canvas.bind_all(sequence, wheel)

        def unbind_wheel(_event):
            for sequence in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
                canvas.unbind_all(sequence)

        outer.bind("<Enter>", bind_wheel)
        outer.bind("<Leave>", unbind_wheel)

        self.source_notes = {}
        self.source_on = {}
        self.source_widgets = {}
        for source in self.sources:
            head = tk.Frame(inner, bg=PANEL_BG)
            head.pack(fill="x", padx=2, pady=(10, 0))
            self.source_on[source.key] = tk.BooleanVar(master=self.root, value=True)
            master = tk.Checkbutton(head, text=source.title, variable=self.source_on[source.key],
                                    command=lambda s=source: self.source_toggled(s), fg=source.color,
                                    activeforeground=source.color, bg=PANEL_BG, activebackground=PANEL_BG,
                                    font=(UI_FONT, 11, "bold"), anchor="w", padx=0)
            master.pack(side="left")
            widgets = self.source_widgets[source.key] = {"master": master, "boxes": [], "labels": []}
            note = tk.Label(head, text="", fg=MUTED, bg=PANEL_BG, font=(UI_FONT, 8))
            note.pack(side="left", padx=(6, 0))
            self.source_notes[source.key] = note
            for group in source.groups.values():
                members = [v for v in source.variables if v.group == group.key]
                label = tk.Label(inner, text=group.ylabel, fg=MUTED, bg=PANEL_BG, font=(UI_FONT, 8), anchor="w")
                label.pack(fill="x", padx=(14, 4), pady=(3, 0))
                widgets["labels"].append(label)
                for var in members:
                    row = tk.Frame(inner, bg=PANEL_BG)
                    row.pack(fill="x", padx=(18, 4))
                    swatch = tk.Canvas(row, width=30, height=12, bg=PANEL_BG, highlightthickness=0)
                    swatch.pack(side="left")
                    color = swatch_color(var)
                    points = (2, 9, 11, 9, 11, 3, 20, 3, 20, 9, 29, 9) if var.step else (2, 6, 29, 6)
                    swatch.create_line(*points, fill=color, width=2, dash=tk_dash(var.style), tags="line")
                    box = tk.Checkbutton(row, text=var.label, variable=self.var_states[(source.key, var.key)],
                                         command=self.selection_changed, bg=PANEL_BG, fg=INK,
                                         activebackground=PANEL_BG, font=(UI_FONT, 9), anchor="w",
                                         padx=0, pady=0, disabledforeground=GREY_LIGHT)
                    box.pack(side="left", fill="x")
                    widgets["boxes"].append((box, swatch, var))
            if not source.folder.is_dir():
                note.configure(text="(no logs)")

    def _build_plot(self, parent):
        frame = tk.Frame(parent, bg="white")
        frame.pack(side="left", fill="both", expand=True)
        bar = tk.Frame(frame, bg=PANEL_BG)
        bar.pack(side="bottom", fill="x")
        # The figure sits in a scrollable area: with many variables ticked it grows taller than
        # the window instead of squeezing the subplots until their labels overlap.
        area = tk.Frame(frame, bg="white")
        area.pack(side="top", fill="both", expand=True)
        self.plot_scroll = tk.Scrollbar(area, orient="vertical")
        self.scroller = tk.Canvas(area, bg="white", highlightthickness=0, yscrollcommand=self.plot_scroll.set)
        self.plot_scroll.configure(command=self.scroller.yview)
        self.scroller.pack(side="left", fill="both", expand=True)
        self.figure = Figure(figsize=(10, 7), dpi=100, facecolor="white")
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.scroller)
        self.figure_window = self.scroller.create_window(0, 0, window=self.canvas.get_tk_widget(), anchor="nw")
        self.needed_height = 0
        self.overlay = tk.Label(area, text="", font=(UI_FONT, 13), bg="#fff4d6", fg=INK, justify="center",
                                padx=22, pady=12, relief="solid", bd=1)
        self.scroller.bind("<Configure>", lambda _e: self._fit_scroller())

        def wheel(event):
            if self.plot_scroll.winfo_ismapped():
                up = getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0
                self.scroller.yview_scroll(-3 if up else 3, "units")
        for sequence in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.canvas.get_tk_widget().bind(sequence, wheel, add="+")
        bar.pack(side="bottom", fill="x")
        try:
            self.toolbar = NavigationToolbar2Tk(self.canvas, bar, pack_toolbar=False)
        except TypeError:   # matplotlib < 3.3
            self.toolbar = NavigationToolbar2Tk(self.canvas, bar)
        self.toolbar.update()
        self.toolbar.pack(side="left", fill="x", expand=True)
        self.canvas.mpl_connect("resize_event", lambda _e: self.layout_axes())

    def _fit_scroller(self):
        width, visible = self.scroller.winfo_width(), self.scroller.winfo_height()
        if width < 20 or visible < 20:
            return
        height = max(visible, self.needed_height)
        if height > visible:
            if not self.plot_scroll.winfo_ismapped():
                self.plot_scroll.pack(side="right", fill="y", before=self.scroller)
        elif self.plot_scroll.winfo_ismapped():
            self.plot_scroll.pack_forget()
            self.scroller.yview_moveto(0)
        self.scroller.itemconfigure(self.figure_window, width=width, height=height)
        self.scroller.configure(scrollregion=(0, 0, width, height))

    # ---- time range -----------------------------------------------------

    def _to_clicked(self, _event):
        if self.now_var.get():
            self.now_var.set(False)
            self._now_toggled(load=False)
            self.to_entry.focus_set()
            self.to_entry.select_range(0, "end")
            self.say("'Now' is off: type an end time and press Load (or Enter).")

    def set_entries(self, t0, t1):
        self.from_entry.delete(0, "end")
        self.from_entry.insert(0, format_local(t0))
        self.to_entry.configure(state="normal")
        self.to_entry.delete(0, "end")
        self.to_entry.insert(0, "now" if self.now_var.get() else format_local(t1))
        if self.now_var.get():
            self.to_entry.configure(state="disabled")

    def say(self, text, color=MUTED):
        self.status.configure(text=text, fg=color)

    def load_or_cancel(self):
        if self.busy:
            self.cancel_load()
        else:
            self.load_from_entries()

    def cancel_load(self):
        self.generation += 1
        self._end_loading()
        self.busy = False
        self.now_var.set(False)
        self._now_toggled(load=False)
        self.load_button.configure(text="Load")
        self.progress.configure(value=0)
        self.say("Loading cancelled; the plots show the previous range.", ERROR_RED)
        if self.loaded:
            first = next(iter(self.loaded.values()))
            self.view = (first.t0, first.t1)
            self.set_entries(*self.view)

    def load_from_entries(self):
        try:
            t0 = parse_local(self.from_entry.get())
            t1 = time.time() if self.now_var.get() else parse_local(self.to_entry.get())
        except ValueError as error:
            self.say("Could not read the time: {}".format(error), ERROR_RED)
            return
        if t1 <= t0:
            self.say("'From' must be earlier than 'To'.", ERROR_RED)
            return
        self.span = t1 - t0
        self.reset_y = True
        self.load(t0, t1)

    def preset(self, seconds):
        now = time.time()
        self.span = seconds
        self.reset_y = True
        self.load(now - seconds, now)

    def _now_toggled(self, load=True):
        if self.refresh_job:
            self.root.after_cancel(self.refresh_job)
            self.refresh_job = None
        if self.view:
            self.set_entries(*self.view)
        if load and self.now_var.get():
            now = time.time()
            span = self.view[1] - self.view[0] if self.view else DEFAULT_SPAN_S
            self.span = span
            self.load(now - span, now)

    def _schedule_refresh(self):
        if self.refresh_job:
            self.root.after_cancel(self.refresh_job)
            self.refresh_job = None
        if self.now_var.get():
            delay = max(NOW_REFRESH_S, 2 * self.last_load_s)
            self.refresh_job = self.root.after(int(delay * 1000), self._refresh_now)

    def _refresh_now(self):
        self.refresh_job = None
        if self.now_var.get() and not self.busy:
            now = time.time()
            self.load(now - self.span, now, push_history=False, quiet=True)
        else:
            self._schedule_refresh()

    def previous_range(self):
        if not self.history:
            self.say("No earlier range in this session.")
            return
        t0, t1 = self.history.pop()
        self.now_var.set(False)
        self._now_toggled(load=False)
        self.span = t1 - t0
        self.reset_y = True
        self.load(t0, t1, push_history=False)

    def default_selection(self):
        for source in self.sources:
            if not self.source_on[source.key].get():
                self.source_on[source.key].set(True)
                self.source_toggled(source)
            for var in source.variables:
                self.var_states[(source.key, var.key)].set(var.default)
        self.selection_changed()

    def checked(self, source):
        if not self.source_on[source.key].get():
            return []
        return [v for v in source.variables if self.var_states[(source.key, v.key)].get()]

    def source_toggled(self, source):
        """The instrument's master checkbox: off hides its panel and greys out its variables (their ticks are kept)."""
        on = self.source_on[source.key].get()
        widgets = self.source_widgets[source.key]
        widgets["master"].configure(fg=source.color if on else GREY_LIGHT,
                                    activeforeground=source.color if on else GREY_LIGHT)
        for label in widgets["labels"]:
            label.configure(fg=MUTED if on else GREY_LIGHT)
        for box, swatch, var in widgets["boxes"]:
            box.configure(state="normal" if on else "disabled")
            swatch.itemconfigure("line", fill=swatch_color(var, on))
        self.selection_changed()

    # ---- dark mode ------------------------------------------------------------------

    def dark_clicked(self):
        self.set_dark(bool(self.dark_var.get()))
        save_theme(THEME["dark"])

    def set_dark(self, dark):
        if THEME["dark"] == dark:
            return
        THEME["dark"] = dark
        recolor_widgets(self.root, dark)
        for source in self.sources:
            on = self.source_on[source.key].get()
            for _box, swatch, var in self.source_widgets[source.key]["boxes"]:
                swatch.itemconfigure("line", fill=swatch_color(var, on))
        style = ttk.Style(self.root)
        if dark:
            style.configure("Horizontal.TProgressbar", troughcolor="#2b333e", background="#4aa8ff")
        else:
            style.configure("Horizontal.TProgressbar", **self.progress_style)
        recolor_toolbar(self.toolbar, dark)
        recolor_figure(self.figure, dark)
        self.canvas.draw_idle()

    def selection_changed(self):
        if not self.view:
            return
        missing = [s for s in self.sources if self.checked(s) and s.key not in self.loaded]
        if missing and not self.busy:
            self.load(*self.view, push_history=False)
        else:
            self.render()

    # ---- loading --------------------------------------------------------

    def load(self, t0, t1, push_history=True, quiet=False):
        if push_history and self.view and (abs(self.view[0] - t0) > 1 or abs(self.view[1] - t1) > 1):
            self.history.append(self.view)
            del self.history[:-30]
        self.view = (t0, t1)
        self.set_entries(t0, t1)
        self.generation += 1
        generation = self.generation
        sources = [s for s in self.sources if self.checked(s)]
        self.busy = True
        self.load_button.configure(text="Cancel")
        self.loading = None
        if not quiet:
            self.say("Loading {} to {} ...".format(format_local(t0), "now" if self.now_var.get() else format_local(t1)))
            self.progress.configure(value=0)
            self.loading = {"started": time.time(), "span": t1 - t0, "estimate": None, "fraction": 0.0,
                            "generation": generation}
            for button in self.range_buttons:
                button.configure(state="disabled")      # one load at a time; Cancel stops it
            self._show_loading()
        thread = threading.Thread(target=self._load_worker, args=(generation, sources, t0, t1), daemon=True)
        thread.start()

    # ---- "Loading" box with a time estimate --------------------------------

    def _planned(self, nbytes):
        if not self.loading:
            return
        self.loading["bytes"] = nbytes
        self.loading["estimate"] = nbytes / self.speed + 0.3

    def _show_loading(self):
        info = self.loading
        if not info or info["generation"] != self.generation:
            return
        elapsed = time.time() - info["started"]
        if elapsed >= 0.4:              # quick loads finish without the box flashing up
            lines = ["Loading {} of logs ...".format(span_text(info["span"]))]
            estimate = info["estimate"]
            if estimate is None:
                lines.append("finding the files")
            elif estimate < 2:
                lines.append("a moment")
            else:
                fraction = info["fraction"]
                if fraction > 0.2:      # once under way, the progress so far is the better guide
                    left = elapsed * (1 - fraction) / fraction
                else:
                    left = estimate - elapsed
                lines.append("estimated {} in total, {} so far ({:.0f} %)".format(
                    seconds_text(estimate), seconds_text(elapsed), 100 * fraction))
                lines.append("about {} left".format(seconds_text(left)) if left >= 1 else "almost done")
            lines.append("Press Cancel to stop. Loaded ranges come back instantly.")
            self.overlay.configure(text="\n".join(lines))
            if not self.overlay.winfo_ismapped():
                self.overlay.place(relx=0.5, rely=0.42, anchor="center")
                self.overlay.lift()
        self.root.after(500, self._show_loading)

    def _end_loading(self):
        self.loading = None
        self.overlay.place_forget()
        for button in self.range_buttons:
            button.configure(state="normal")

    @property
    def speed(self):
        """Bytes of CSV text parsed per second on this computer (learned; starting guess below)."""
        return self.learned_speed or (60e6 if self.use_pandas else 15e6)

    def learn_speed(self, value):
        old = self.learned_speed
        self.learned_speed = value if not old else 0.5 * old + 0.5 * value
        try:      # remembered between sessions; a convenience only
            with open(str(SPEED_FILE), "w") as handle:
                handle.write("{} {:.0f}\n".format("pandas" if self.use_pandas else "csv", self.learned_speed))
        except OSError:
            pass

    def _check(self, generation):
        def check():
            if generation != self.generation:
                raise Cancelled()
        return check

    def _load_worker(self, generation, sources, t0, t1):
        started = time.time()
        check = self._check(generation)
        try:
            plan = [(s, list_files(s, t0, t1)) for s in sources]
            total = max(1, sum(len(files) for _s, files in plan))
            to_read = 0
            for source, files in plan:
                width = None if (t1 - t0) / source.nominal_s <= FULL_RES_MAX_ROWS else choose_bin_width(t1 - t0)
                for _start, path, size, mtime in files:
                    if not self.cache.has((source.key, path, size, mtime, self.use_pandas, width)):
                        to_read += text_size(path, size)
            self.events.put(("plan", generation, to_read))
            done = [0]

            def step():
                done[0] += 1
                self.events.put(("progress", generation, done[0] / total))

            results = {}
            for source, files in plan:
                results[source.key] = load_source(source, t0, t1, self.use_pandas, self.cache, files, check, step)
            self.events.put(("loaded", generation, (t0, t1, results, time.time() - started)))
        except Cancelled:
            pass
        except Exception as error:      # shown in the status bar rather than lost in a thread
            self.events.put(("failed", generation, "{}: {}".format(type(error).__name__, error)))

    def _poll_events(self):
        try:
            while True:
                kind, generation, payload = self.events.get_nowait()
                if kind.startswith("export"):
                    self._export_event(kind, payload)
                    continue
                if generation != self.generation:
                    continue
                if kind == "progress":
                    self.progress.configure(value=payload)
                    if self.loading:
                        self.loading["fraction"] = payload
                elif kind == "plan":
                    self._planned(payload)
                elif kind == "loaded":
                    self._loaded(*payload)
                elif kind == "failed":
                    self._end_loading()
                    self.busy = False
                    self.load_button.configure(text="Load")
                    self.say("Loading failed: " + payload, ERROR_RED)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _loaded(self, t0, t1, results, seconds):
        if self.loading and self.loading.get("bytes", 0) > 100e6 and seconds > 2:   # long loads: per-byte time dominates
            self.learn_speed(self.loading["bytes"] / seconds)
        self._end_loading()
        self.busy = False
        self.load_button.configure(text="Load")
        self.loaded = results
        self.last_load_s = seconds
        self.progress.configure(value=1.0)
        for source in self.sources:
            loaded = results.get(source.key)
            note = ""
            if not source.folder.is_dir():
                note = "(no logs)"
            elif loaded is not None and not loaded.has_rows:
                note = "(no data in range)"
            self.source_notes[source.key].configure(text=note)
        self.render()
        rows = sum(r.rows for r in results.values())
        binned = any(r.mode == "binned" for r in results.values())
        self.say("{} to {}: {:,} rows from {} files in {:.1f} s{}{}{}".format(
            format_local(t0), format_local(t1), rows, sum(r.files for r in results.values()), seconds,
            " (pandas)" if self.use_pandas else "",
            "; long range shown as min/max, zoom in for full resolution" if binned else "",
            "; refreshing every {:.0f} s".format(max(NOW_REFRESH_S, 2 * seconds)) if self.now_var.get() else ""))
        self._schedule_refresh()
        if any(self.checked(s) and s.key not in results for s in self.sources):
            self.load(t0, t1, push_history=False, quiet=True)     # ticked while this load was running
            return
        if self.args.snapshot and not self.snapshot_done:
            self.snapshot_done = True
            self.root.update_idletasks()
            self.canvas.draw()
            self.figure.savefig(self.args.snapshot, dpi=100, facecolor=self.figure.get_facecolor())
            self.root.after(200, self.close)

    # ---- plotting -------------------------------------------------------

    def render(self):
        """Rebuild the subplots for the ticked variables and the loaded data."""
        kept = {} if self.reset_y else {(src.key, grp.key): ax.get_ylim()
                                        for ax, src, grp, _l, _d in self.axes_info if ax in self.user_y}
        self.reset_y = False
        self.setting_limits = True
        self.figure.clear()
        self.axes_info = []
        self.panels = []
        self.user_y = set()
        base_ax = None
        number = 0
        for source in self.sources:
            loaded = self.loaded.get(source.key)
            checked = self.checked(source)
            if loaded is None or not checked:
                continue
            panel = []
            for group in source.groups.values():
                members = [v for v in checked if v.group == group.key]
                if not members:
                    continue
                number += 1
                ax = self.figure.add_axes([0.1, 0.1, 0.8, 0.8], sharex=base_ax, label="ax{}".format(number))
                base_ax = base_ax or ax
                lines = []
                for var in members:
                    line, = ax.plot([], [], color=var.color, linestyle=var.style, linewidth=var.width,
                                    alpha=var.alpha, label=var.label,
                                    drawstyle="steps-post" if var.step else "default")
                    lines.append((line, var))
                self._style_axis(ax, group)
                if len(lines) > 1 or group.ticks is None:
                    ax.legend(loc="upper left", fontsize=7, ncol=min(len(lines), 4), framealpha=0.75,
                              handlelength=2.4, borderaxespad=0.3, borderpad=0.3, labelspacing=0.2,
                              columnspacing=1.2)
                if not panel:
                    ax.set_title(source.title, loc="left", color=source.color, fontsize=10,
                                 fontweight="bold", pad=3)
                    ax.set_title(loaded.describe(), loc="right", color=MUTED, fontsize=8, pad=3)
                if not loaded.has_rows:
                    ax.text(0.5, 0.5, "no data in this range", transform=ax.transAxes, ha="center",
                            va="center", color=MUTED, fontsize=10)
                if (source.key, group.key) in kept:
                    ax.set_ylim(*kept[(source.key, group.key)])
                    self.user_y.add(ax)
                panel.append((ax, group))
                self.axes_info.append((ax, source, group, lines, loaded))
            self.panels.append(panel)
        if base_ax is None:
            self.figure.text(0.5, 0.5, "Nothing ticked, or no logs found for this range.", ha="center",
                             va="center", color=MUTED, fontsize=12)
        else:
            self._style_time_axis(base_ax)
            for ax, *_rest in self.axes_info:     # the toolbar only reports the axis it acted on
                ax.callbacks.connect("ylim_changed", self._ylim_changed)
                ax.callbacks.connect("xlim_changed", self._xlim_changed)
            base_ax.set_xlim(to_plot(self.view[0]), to_plot(self.view[1]))
            bottom = self.axes_info[-1][0]
            for ax, *_rest in self.axes_info:
                if ax is not bottom:
                    ax.tick_params(labelbottom=False)
                    ax.xaxis.get_offset_text().set_visible(False)
        panels = [p for p in self.panels if p]
        self.needed_height = (self._fixed_height(panels) + sum(g.min_px for p in panels for _a, g in p)) if panels else 0
        self._fit_scroller()
        self.layout_axes(draw=False)
        if THEME["dark"]:
            recolor_figure(self.figure, True)     # the new artists were made with light-mode colours
        self.toolbar.update()          # fresh zoom history for the new axes
        self.setting_limits = False
        self.refresh_display()

    @staticmethod
    def _style_axis(ax, group):
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=8)
        ax.set_ylabel(group.ylabel, fontsize=8)
        if group.ticks:
            values = [v for v, _ in group.ticks]
            ax.set_yticks(values)
            ax.set_yticklabels([label for _, label in group.ticks])
            ax.set_ylim(min(values) - 0.3, max(values) + 0.3)
        else:
            ax.ticklabel_format(axis="y", useOffset=False, style="plain")

    @staticmethod
    def _style_time_axis(ax):
        locator = mdates.AutoDateLocator(minticks=4, maxticks=10, tz=LOCAL_TZ)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(
            locator, tz=LOCAL_TZ, zero_formats=["", "%Y", "%b", "%d %b", "%H:%M", "%H:%M"],
            offset_formats=["", "%Y", "%b %Y", "%d %b %Y", "%d %b %Y", "%d %b %Y"]))
        ax.xaxis.get_offset_text().set_x(0.5)
        ax.xaxis.get_offset_text().set_horizontalalignment("center")

    def layout_axes(self, draw=True):
        """Place the subplots in pixels: fixed margins, panel titles, small gaps within a panel."""
        width, height = self.figure.get_size_inches() * self.figure.dpi
        if not self.axes_info or width < 50 or height < 50:
            if draw:
                self.canvas.draw_idle()
            return
        left, right, top = LAYOUT_PX["left"], LAYOUT_PX["right"], LAYOUT_PX["top"]
        title, panel_gap, gap = LAYOUT_PX["title"], LAYOUT_PX["panel_gap"], LAYOUT_PX["gap"]
        panels = [p for p in self.panels if p]
        groups = [g for p in panels for _ax, g in p]
        free = height - self._fixed_height(panels)
        # heights in proportion to the weights, but none below its readable minimum
        low, high = 0.0, free / sum(g.weight for g in groups)
        for _ in range(40):
            scale = (low + high) / 2
            if sum(max(g.min_px, g.weight * scale) for g in groups) > free:
                high = scale
            else:
                low = scale
        y = height - top
        for panel in panels:
            y -= title
            for ax, group in panel:
                h = max(group.min_px, group.weight * low)
                ax.set_position([left / width, (y - h) / height, (width - left - right) / width, h / height])
                ax.set_ylabel(group.ylabel if h >= 6 * len(group.ylabel) + 6 else group.short, fontsize=8)
                ax.yaxis.set_label_coords(-(left - 16) / (width - left - right), 0.5)   # fixed, whatever the tick width
                y -= h + gap
            y += gap - panel_gap
        if draw:
            self.canvas.draw_idle()

    @staticmethod
    def _fixed_height(panels):
        subplots = sum(len(p) for p in panels)
        return (LAYOUT_PX["top"] + LAYOUT_PX["bottom"] + LAYOUT_PX["title"] * len(panels)
                + LAYOUT_PX["panel_gap"] * (len(panels) - 1) + LAYOUT_PX["gap"] * (subplots - len(panels)))

    def refresh_display(self):
        """Draw the loaded data for the current view, and fit the y axes to what is visible."""
        if not self.axes_info:
            self.canvas.draw_idle()
            return
        x0, x1 = self.axes_info[0][0].get_xlim()
        a, b = from_plot(x0), from_plot(x1)
        self.setting_limits = True
        for ax, source, group, lines, loaded in self.axes_info:
            visible = []
            for line, var in lines:
                x, y = loaded.curve(var.key, a, b)
                line.set_data(to_plot(x), y)
                if x.size:
                    inside = (x >= a) & (x <= b)
                    visible.append(y[inside])
            if group.ticks is None and ax not in self.user_y:
                self._fit_y(ax, group, visible)
        self.setting_limits = False
        self.canvas.draw_idle()

    @staticmethod
    def _fit_y(ax, group, arrays):
        values = np.concatenate(arrays) if arrays else np.zeros(0)
        values = values[np.isfinite(values)]
        if values.size == 0:
            ax.set_ylim(0, 1)
            return
        low, high = float(values.min()), float(values.max())
        pad = max((high - low) * 0.08, group.min_pad)
        low, high = low - pad, high + pad
        if group.floor is not None and low < group.floor <= float(values.min()):
            low = group.floor
        ax.set_ylim(low, high)

    def _ylim_changed(self, ax):
        if not self.setting_limits:
            self.user_y.add(ax)            # zoomed by hand: leave this axis alone

    def _xlim_changed(self, _ax):
        if self.setting_limits:
            return
        if self.zoom_job:
            self.root.after_cancel(self.zoom_job)
        self.zoom_job = self.root.after(ZOOM_SETTLE_MS, self._view_changed)

    def _view_changed(self):
        """After a toolbar zoom or pan: re-read at full resolution if needed, else just redraw."""
        self.zoom_job = None
        if not self.axes_info:
            return
        x0, x1 = self.axes_info[0][0].get_xlim()
        a, b = from_plot(x0), from_plot(x1)
        if self.view and abs(a - self.view[0]) < 1 and abs(b - self.view[1]) < 1:
            return
        if self.now_var.get():
            self.now_var.set(False)
            self._now_toggled(load=False)
        self.history.append(self.view)
        del self.history[:-30]
        self.view = (a, b)
        self.span = b - a
        self.set_entries(a, b)
        reread = False
        for loaded in self.loaded.values():
            if not loaded.covers(a, b):
                reread = True
            elif loaded.mode == "binned" and (b - a) < 0.6 * (loaded.t1 - loaded.t0):
                reread = True
        if reread and not self.busy:
            self.load(a, b, push_history=False)
        else:
            self.refresh_display()

    # ---- export ---------------------------------------------------------

    def export_folder(self):
        for folder in (self.base / EXPORT_SUBDIR, Path.home() / "dnp_exports"):
            try:
                folder.mkdir(parents=True, exist_ok=True)
                if os.access(str(folder), os.W_OK):
                    return folder
            except OSError:
                pass
        return Path.cwd()

    def current_view(self):
        if self.axes_info:
            x0, x1 = self.axes_info[0][0].get_xlim()
            return from_plot(x0), from_plot(x1)
        return self.view

    def export_png(self):
        a, b = self.current_view()
        name = "dnp_logs_{}_to_{}.png".format(datetime.fromtimestamp(a).strftime("%Y%m%d-%H%M"),
                                              datetime.fromtimestamp(b).strftime("%Y%m%d-%H%M"))
        path = filedialog.asksaveasfilename(parent=self.root, title="Save the plots as PNG",
                                            initialdir=str(self.export_folder()), initialfile=name,
                                            defaultextension=".png", filetypes=[("PNG image", "*.png")])
        if not path:
            return
        try:
            self.figure.savefig(path, dpi=150, facecolor=self.figure.get_facecolor())
        except (OSError, ValueError) as error:
            self.say("Could not save {}: {}".format(path, error), ERROR_RED)
            return
        self.say("Saved {}".format(path), OK_GREEN)

    def export_csv(self):
        a, b = self.current_view()
        jobs = [(s, [v.key for v in self.checked(s)]) for s in self.sources if self.checked(s)]
        if not jobs:
            self.say("Nothing ticked to export.", ERROR_RED)
            return
        if self.exporting:
            self.say("An export is already running.", ERROR_RED)
            return
        rows = sum((b - a) / s.nominal_s for s, _k in jobs)
        if rows > EXPORT_ASK_ROWS and not messagebox.askyesno(
                "CSV export", "About {:,.0f} rows at full resolution. Writing them can take several minutes "
                "and a few hundred MB of disk.\n\nZoom in first for a smaller file, or export anyway?".format(rows),
                parent=self.root):
            return
        self.exporting = True
        folder = self.export_folder()
        self.say("Exporting {} to {} at full resolution ...".format(format_local(a), format_local(b)))
        self.progress.configure(value=0)
        threading.Thread(target=self._export_worker, args=(jobs, a, b, folder), daemon=True).start()

    def _export_worker(self, jobs, a, b, folder):
        try:
            total = max(1, sum(len(list_files(s, a, b)) for s, _k in jobs))
            done = [0]

            def step():
                done[0] += 1
                self.events.put(("export-progress", 0, done[0] / total))

            written = []
            for source, keys in jobs:
                written.append(export_source(source, keys, a, b, self.use_pandas, folder, lambda: None, step))
            self.events.put(("export-done", 0, (folder, written)))
        except Exception as error:
            self.events.put(("export-failed", 0, "{}: {}".format(type(error).__name__, error)))

    def _export_event(self, kind, payload):
        if kind == "export-progress":
            self.progress.configure(value=payload)
            return
        self.exporting = False
        if kind == "export-failed":
            self.say("Export failed: " + payload, ERROR_RED)
        else:
            folder, written = payload
            self.progress.configure(value=1.0)
            lines = ["{}  ({:,} rows)".format(path.name, rows) for path, rows in written]
            self.say("Exported {} file(s) to {}".format(len(written), folder), OK_GREEN)
            messagebox.showinfo("CSV export", "Saved in {}:\n\n{}".format(folder, "\n".join(lines)),
                                parent=self.root)

    def _callback_error(self, kind, error, trace):
        import traceback
        traceback.print_exception(kind, error, trace)
        try:
            self.say("Internal error: {}: {} (details in the terminal)".format(kind.__name__, error), ERROR_RED)
        except tk.TclError:
            pass

    def close(self):
        if self.exporting and not self.args.snapshot and not messagebox.askyesno(
                "DNP log viewer", "A CSV export is still being written. Close anyway (the file will be incomplete)?",
                parent=self.root):
            return
        self.generation += 1          # stops a running load
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main():
    parser = argparse.ArgumentParser(description="Plots the logs written by dnp_monitor.py.")
    parser.add_argument("--base-dir", default=BASE_DIR, help="folder with the log folders (default %(default)s)")
    parser.add_argument("--start", help='start, local time, "YYYY-MM-DD HH:MM" (default: 24 h ago)')
    parser.add_argument("--stop", help='end, local time (default: now, refreshing)')
    parser.add_argument("--geometry", help="window size and position, e.g. 1700x950+0+0")
    parser.add_argument("--no-pandas", action="store_true", help="do not use pandas even if installed")
    parser.add_argument("--snapshot", help=argparse.SUPPRESS)   # tests: save the first plot as PNG and exit
    args = parser.parse_args()
    if args.stop and not args.start:
        parser.error("--stop needs --start")
    for value in (args.start, args.stop):
        if value:
            try:
                parse_local(value)
            except ValueError as error:
                parser.error("{!r}: {}".format(value, error))

    root = tk.Tk()
    if args.geometry:
        root.geometry(args.geometry)
    else:
        width = min(1700, root.winfo_screenwidth() - 40)
        height = min(1000, root.winfo_screenheight() - 90)
        root.geometry("{}x{}+20+20".format(width, height))
    ViewerApp(root, args, build_sources(args.base_dir))
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
