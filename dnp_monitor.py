#!/usr/bin/env python3
"""
DNP monitor for the Topspin PC (bruk800wb): MAS spin rate and pressures from
the Bruker MAS3 controllers, and Lake Shore 336 bearing/drive temperatures,
in one window.

Left half:  one panel per MAS3 controller (both logged all the time), stacked
            in the order of the config file. Each shows the spin rate (largest),
            bearing and drive pressures, bearing sense and frame cooling, the
            spin-rate RMSD over 10 s and 2 min, and a plot: past 24 h (left,
            2/3 of the width) and past 30 min (right, 1/3).
Right half: Lake Shore 336 bearing (A) and drive (B) temperatures with the
            setpoint/ramp/PID controls (Control checkbox, locks after 30 s
            without edits), the heat-exchanger LN2 level from the AMI Model
            1700 with its autofill start/stop levels (same kind of Control
            checkbox), and plots of the past 24 h and 30 min.

Everything lives under BASE_DIR (default /home/nmrsu/dnp_monitor):
    dnp_monitor.py                 this program
    dnp_monitor.conf               controller IPs and login (read at start-up;
                                   written with defaults if missing)
    mas_logs/<controller>/         MAS CSV files, one folder per controller
    lakeshore336_logs/             Lake Shore CSV files (full and _fast)
    ami1700_logs/                  AMI 1700 LN2 level CSV files
    housekeeping.log               what the log housekeeping compressed/deleted

Housekeeping: log files are gzipped (file.csv -> file.csv.gz) 2 days after
their last write and deleted 365 days after it (COMPRESS_AFTER_DAYS and
DELETE_AFTER_DAYS below). Read a compressed log with zcat, or pandas.read_csv.

MAS3 access is read-only: the spin rate comes from /DeviceStatus.html (no
login) and the pressures from a plain read of the Manual Rotation page with a
login session. The program only ever submits the login and logout forms; it
never submits any form of the Manual Rotation page.

Requires Python >= 3.6 with matplotlib, numpy, and tkinter.

Run:   python3 /home/nmrsu/dnp_monitor/dnp_monitor.py
Stop:  close the window, or Ctrl+C in the terminal.
"""

import argparse
import configparser
import csv
import fcntl
import gzip
import ipaddress
import json
import math
import os
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from tkinter import messagebox

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from dateutil import tz as dateutil_tz   # installed with matplotlib

# Plot x-values are UTC (monotonic through daylight-saving changes); the axis
# labels are converted to local time, with the DST rules applied per tick.
LOCAL_TZ = dateutil_tz.tzlocal()


# ==========================================================================
# Settings
# ==========================================================================

BASE_DIR = "/home/nmrsu/dnp_monitor"
CONFIG_NAME = "dnp_monitor.conf"
MAS_LOG_SUBDIR = "mas_logs"
LS_LOG_SUBDIR = "lakeshore336_logs"
LOCK_NAME = ".dnp_monitor.lock"

LONG_SPAN_S = 24 * 3600        # 24 h plots
SHORT_SPAN_S = 30 * 60         # 30 min plots
MIN_SPAN_S = 5 * 60            # minimum visible span right after starting
LONG_REDRAW_S = 30.0           # the 24 h plots are redrawn this often
SHORT_REDRAW_S = 2.0           # the 30 min plots are redrawn this often
LONG_MAX_POINTS = 3000         # above this, 24 h traces show a min/max envelope
NEW_FILE_EVERY_S = 24 * 3600   # all loggers start a new CSV file this often
TRACE_HIDE_S = 30             # traces unticked under a plot come back by themselves after this
FOLLOW_RESUME_S = 30           # "Follow live" switches itself back on after this
COMPRESS_AFTER_DAYS = 2        # log files untouched for this long are gzipped (about 10x smaller)
DELETE_AFTER_DAYS = 365        # log files untouched for this long are deleted
HOUSEKEEPING_FIRST_S = 120     # first housekeeping pass this long after start-up
HOUSEKEEPING_EVERY_S = 6 * 3600
UI_TICK_MS = 250
YLABEL_EDGE_PX = 17            # plot y labels: their axis-side edge this far from the figure's left edge

# --- MAS -------------------------------------------------------------------
MAS_COLORS = ("#5b2a86", "#1b7a3e", "#8a5a00")   # banner/plot colour, in config order
MAS_POLL_INTERVAL_S = 1.0      # spin rate (DeviceStatus.html) is read this often
MAS_PRESSURE_EVERY_S = 2.0     # pressures (Manual Rotation page) are read this often
MAS_REQUEST_TIMEOUT_S = 2.0
MAS_RELOGIN_AFTER_S = 30.0     # minimum time between login attempts
MAS_ERROR_LOG_EVERY_S = 60.0   # an unreachable controller writes one error row per minute
PRESSURE_STALE_AFTER_S = 6.0   # older pressure readings are shown/logged as missing
RMSD_WINDOWS_S = (10, 120)
RMSD_MIN_POINTS = 3
MAS_STALE_AFTER_S = 5.0        # no valid spin reading for this long -> "NO DATA"
MAS_GAP_S = 10.0               # saved readings further apart are not joined
MAS_CSV_COLUMNS = [
    "time_local", "unix_time", "controller", "ip",
    "spin_rate_hz", "signal_level_pct", "signal_note", "gain", "status",
    "bearing_mbar", "bearing_sense_mbar", "drive_mbar",
    "frame_cooling", "frame_cooling_set_mbar", "rotation_state",
]

# --- Lake Shore 336 (unchanged from lakeshore336_logger.py) -------------------
LS_HOST = "lakeshore336.example.com"
LS_PORT = 7777
CONTROL_IDLE_SECONDS = 30
DEFAULT_INTERVAL_SECONDS = 3     # Lake Shore fast interval at start-up
MIN_INTERVAL_SECONDS = 2
FULL_REFRESH_SECONDS = 5
QUERY_GAP_SECONDS = 0.05  # Model 336 minimum quiet time after each response/command.
FAST_QUERIES = ("KRDG? A", "KRDG? B",
                "HTR? 1", "SETP? 1", "HTR? 2", "SETP? 2")
MODES = {0: "off", 1: "PID", 2: "zone", 3: "open_loop",
         4: "monitor", 5: "warmup", 6: "mirroring"}
INPUTS = {0: "none", 1: "A", 2: "B", 3: "C", 4: "D"}
# Monitoring queries remain separate from explicitly enabled setting changes.
READ_QUERY = re.compile(
    r"(?:\*IDN\?|(?:KRDG|RDGST|INTYPE)\? [ABCD]|"
    r"(?:OUTMODE|PID|RANGE|SETP)\? [1-4]|(?:HTR|HTRSET|HTRST|RAMP|RAMPST)\? [12]|AOUT\? [34])"
)
CHANNELS = (("A", "bearing", "#0072B2"), ("B", "drive", "#D55E00"))
HEATER_RANGES = ((0, "Off"), (1, "Low"), (2, "Med"), (3, "High"))   # RANGE codes of outputs 1 and 2
HEATER_FAULTS = {1: "OPEN LOAD", 2: "SHORT"}                        # HTRST? codes
LS_FEATURES = {"htrst": True}      # set False (for the whole run) if the 336 does not answer HTRST?

# --- AMI Model 1700 (heat-exchanger LN2 level) ----------------------------------
AMI_LOG_SUBDIR = "ami1700_logs"
AMI_DEFAULTS = {"ip": "192.0.2.30", "http_port": 80, "scpi_port": 7180, "poll_seconds": 60.0, "enabled": True}

# --- Look --------------------------------------------------------------------
UI_FONT = "Helvetica"
MUTED = "#526277"
ERROR_RED = "#b42318"
OK_GREEN = "#16714b"
INK = "#26364a"
PANEL_BG = "#f4f7fb"
DISABLED_BG = "#e8edf3"
ALL_OFF_RED = "#e2231a"        # Lake Shore front-panel ALL OFF key
ALL_OFF_PRESSED = "#b0170f"
ALL_OFF_DIM = "#eba6a2"        # while Control is locked
PENDING_BG = "#ffe3a3"         # amber: an edit that has not been applied yet
PENDING_DARK = "#b26a00"
LOCKED_SELECTED = "#7b8794"    # selected heater range while Control is locked
LIVE_GREEN = "#16714b"


# ==========================================================================
# Small helpers
# ==========================================================================

NAN = float("nan")
ISO_RE = re.compile(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.(\d{1,6}))?(Z|[+-]\d\d:?\d\d)?$")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def parse_iso(text):
    """datetime.fromisoformat replacement (that only exists from Python 3.7)."""
    match = ISO_RE.match(text.strip())
    if not match:
        raise ValueError("Not an ISO timestamp: {!r}".format(text))
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    value = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second),
                     int((fraction or "0").ljust(6, "0")))
    if zone is None:
        return value
    if zone == "Z":
        offset = 0
    else:
        digits = zone[1:].replace(":", "")
        offset = (int(digits[:2]) * 60 + int(digits[2:])) * (1 if zone[0] == "+" else -1)
    return value.replace(tzinfo=timezone(timedelta(minutes=offset)))


def number(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"Non-finite reading: {text!r}")
    return value


def number_or_nan(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return NAN
    return result if math.isfinite(result) else NAN


def to_plot_time(epoch):
    return mdates.date2num(datetime.fromtimestamp(epoch, timezone.utc))


def to_plot_times(epochs):
    return mdates.date2num([datetime.fromtimestamp(t, timezone.utc) for t in epochs])


def envelope(x, y, max_points):
    """
    Reduce a long series to per-time-bin min/max pairs, so short excursions
    stay visible. The line is broken (NaN) after a bin that contains a missing
    reading and across empty bins, so gaps are not bridged by a straight line.
    """
    if len(x) <= max_points or x[-1] <= x[0]:
        return x, y
    width = (x[-1] - x[0]) / (max_points // 3)
    bins = np.floor((x - x[0]) / width).astype(int)
    starts = np.flatnonzero(np.r_[True, bins[1:] != bins[:-1]])
    with np.errstate(all="ignore"):
        lows = np.fmin.reduceat(y, starts)
        highs = np.fmax.reduceat(y, starts)
    has_nan = np.add.reduceat(np.isnan(y).astype(int), starts) > 0
    bin_ids = bins[starts]
    xs, ys = [], []
    for j, start in enumerate(starts):
        xs += [x[start], x[start]]
        ys += [lows[j], highs[j]]
        gap_follows = j + 1 < len(starts) and bin_ids[j + 1] > bin_ids[j] + 1
        if has_nan[j] or gap_follows:
            xs.append(x[start])
            ys.append(NAN)
    return np.array(xs), np.array(ys)


def recent_columns(data, since_epoch, width):
    """
    Columns (as float arrays) of the rows of a time-ordered deque with epoch >= since_epoch.
    Walks back from the newest row, so the 30 min plots never touch the rest of the 24 h buffer.
    """
    rows = []
    for row in reversed(data):
        if row[0] < since_epoch:
            break
        rows.append(row)
    rows.reverse()
    table = np.array(rows, dtype=float).reshape(-1, width)
    return [table[:, k] for k in range(width)]


def visible_limits(epochs, now, span_s):
    """
    x-limits (as plot times). The 24 h plots start at the oldest point (at least
    MIN_SPAN_S); shorter plots always show their full span.
    """
    keep = epochs >= now - span_s
    if span_s < LONG_SPAN_S:
        return keep, to_plot_time(now - span_s), to_plot_time(now + 30)
    oldest = epochs[keep][0] if keep.any() else now
    left = max(min(oldest, now - MIN_SPAN_S), now - span_s)
    return keep, to_plot_time(left), to_plot_time(now + 60)


def set_y_limits(ax, values, minimum_pad, floor=None):
    finite = values[np.isfinite(values)]
    if finite.size:
        low, high = float(finite.min()), float(finite.max())
        pad = max(0.1 * (high - low), minimum_pad)
        bottom = low - pad
        if floor is not None and low >= floor:
            # a small margin below the floor keeps a flat trace at the floor visible above the axis line
            bottom = max(bottom, floor - 0.03 * (high + pad - floor))
        ax.set_ylim(bottom, high + pad)


def differs(text, value):
    """True if an edit field's text is not the given live value (unparsable text counts as changed)."""
    try:
        return not math.isclose(float(text), float(value), abs_tol=1e-9)
    except (TypeError, ValueError):
        return True


# ==========================================================================
# Configuration file
# ==========================================================================

AMI_CONFIG_TEXT = """
[AMI1700]
# AMI Model 1700 LN2 level meter on the heat exchanger. Its address is assigned
# by DHCP: if it changes, read the new one on the instrument's network
# configuration screen and update ip here. enabled = no hides it.
ip = 192.0.2.30
poll_seconds = 60
enabled = yes
"""

DEFAULT_CONFIG_TEXT = """\
# DNP monitor configuration.
# Read only when the monitor starts: restart the monitor after editing.
# The addresses below are placeholders (192.0.2.x is reserved for examples):
# replace them with your instruments' addresses.
#
# Each [MAS3-...] section is one MAS3 controller. Panels are stacked in this
# order (first = top). The section name is also the log folder name, so keep
# it unchanged to keep the history.
#   ip              IPv4 address of the controller
#   user, password  login used only to READ the pressures from the Manual
#                   Rotation page (nothing is ever submitted to that page)
#   read_pressures  yes/no; "no" skips the login and shows spin rate only

[MAS3-test-stand]
ip = 192.0.2.10
user = Administrator
password = admin
read_pressures = yes

[MAS3-above-console]
ip = 192.0.2.20
user = Administrator
password = admin
read_pressures = yes

[LakeShore336]
host = lakeshore336.example.com
port = 7777
""" + AMI_CONFIG_TEXT


class ConfigError(Exception):
    pass


def load_config(path):
    """
    Returns (MAS controllers in file order, Lake Shore host/port, AMI 1700 settings,
    whether the file was created, whether the [AMI1700] section was added to it).
    """
    path = Path(path)
    created = False
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_TEXT)
        os.chmod(str(path), 0o600)
        created = True
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with open(str(path)) as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as error:
        raise ConfigError("{}: {}".format(path, error))
    ami_added = False
    if not any(name.lower() == "ami1700" for name in parser.sections()):
        try:                      # a config file from an earlier version: add the new section
            with open(str(path), "a") as handle:
                handle.write(AMI_CONFIG_TEXT)
            ami_added = True
        except OSError:
            pass
        parser.read_string(AMI_CONFIG_TEXT)

    controllers = OrderedDict()
    lakeshore = {"host": LS_HOST, "port": LS_PORT}
    ami = dict(AMI_DEFAULTS)
    for name in parser.sections():
        section = parser[name]

        def fail(message):
            raise ConfigError("{}, section [{}]: {}".format(path, name, message))

        if name.lower() == "lakeshore336":
            lakeshore["host"] = section.get("host", LS_HOST).strip()
            try:
                lakeshore["port"] = section.getint("port", LS_PORT)
            except ValueError:
                fail("port must be a whole number")
            continue
        if name.lower() == "ami1700":
            ami["ip"] = section.get("ip", AMI_DEFAULTS["ip"]).strip()
            try:
                ipaddress.IPv4Address(ami["ip"])
            except ValueError:
                fail("ip = {!r} is not an IPv4 address".format(ami["ip"]))
            try:
                ami["http_port"] = section.getint("http_port", 80)
                ami["scpi_port"] = section.getint("scpi_port", 7180)
                ami["poll_seconds"] = section.getfloat("poll_seconds", 60.0)
                ami["enabled"] = section.getboolean("enabled", True)
            except ValueError as error:
                fail(str(error))
            if not 10 <= ami["poll_seconds"] <= 3600:
                fail("poll_seconds must be 10-3600")
            continue
        if not re.match(r"^[A-Za-z0-9_.-]+$", name):
            fail("the name may contain only letters, digits, '-', '_' and '.'")
        ip = section.get("ip", "").strip()
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            fail("ip = {!r} is not an IPv4 address".format(ip))
        try:
            port = section.getint("port", 80)
            read_pressures = section.getboolean("read_pressures", True)
        except ValueError as error:
            fail(str(error))
        if not 1 <= port <= 65535:
            fail("port must be 1-65535")
        controllers[name] = {
            "ip": ip,
            "host": ip if port == 80 else "{}:{}".format(ip, port),
            "user": section.get("user", "Administrator"),
            "password": section.get("password", "admin"),
            "read_pressures": read_pressures,
            "color": MAS_COLORS[len(controllers) % len(MAS_COLORS)],
        }
    if not controllers:
        raise ConfigError("{}: no MAS controller sections".format(path))
    if len(controllers) > 3:
        raise ConfigError("{}: at most 3 MAS controllers fit in the window".format(path))
    return controllers, lakeshore, ami, created, ami_added


# ==========================================================================
# MAS: reading the controller pages, logging, history
# ==========================================================================

TAG_RE = re.compile(r"<[^>]+>")
SPIN_RE = re.compile(r"Spin Rate \(Hz\)\s*(-?[\d.]+)")
SIGNAL_RE = re.compile(r"Signal Level\s*([\d.]+)\s*%(?:\s*-\s*(.*?))?\s*(?=Gain\b|$)")
GAIN_RE = re.compile(r"Gain\s*\([^)]*\)\s*(\d+)")
# Talk to the controllers directly, never through an http_proxy setting.
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def mas_status_url(host):
    return "http://{}/DeviceStatus.html".format(host)


def page_to_text(html):
    text = unescape(TAG_RE.sub(" ", html))
    return re.sub(r"\s+", " ", text).strip()


def parse_mas_status(text):
    """
    Parse the plain text of DeviceStatus.html, e.g.
      "Rotation Running Spin Rate (Hz) 120 Signal Level 7.5% - Critical Gain (0..63) 245"
    """
    match = SPIN_RE.search(text)
    if not match:
        raise ValueError("'Spin Rate (Hz)' not found on the status page")
    result = {"spin_hz": float(match.group(1)), "status": text[:match.start()].strip()[:120],
              "signal_pct": None, "signal_note": "", "gain": None}
    signal_match = SIGNAL_RE.search(text)
    if signal_match:
        result["signal_pct"] = float(signal_match.group(1))
        result["signal_note"] = (signal_match.group(2) or "").strip()
    gain_match = GAIN_RE.search(text)
    if gain_match:
        result["gain"] = int(gain_match.group(1))
    return result


def read_mas_controller(host, timeout):
    with HTTP.open(mas_status_url(host), timeout=timeout) as response:
        html = response.read().decode("utf-8", "replace")
    result = parse_mas_status(page_to_text(html))
    result["status_error"] = 'class="error"' in html     # the controller marks error messages this way
    return result


# --- Manual Rotation page (pressures) -------------------------------------------

MANUAL_ROTATION_PATH = "/ewp/device/main/ManualRotation/"
PRESSURE_IDS = (("bearing_mbar", "BEARING_PRESSURE"),
                ("bearing_sense_mbar", "BEARING_SENSE_PRESSURE"),
                ("drive_mbar", "DRIVE_PRESSURE"))
SESSION_RE = re.compile(r'name="session"\s+value="([0-9a-fA-F]{8,})"')
FRAME_STATE_RE = re.compile(r"Frame cooling is</span>.*?<span>([^<]*)</span>", re.S)
FRAME_SET_RE = re.compile(r'name="FrameCoolingPressure"[^>]*\bvalue="(-?[\d.]+)"')
ROTATION_STATE_RE = re.compile(r"Rotation State</span>.*?<span>([^<]*)</span>", re.S)
PRESSURE_KEYS = ("bearing_mbar", "bearing_sense_mbar", "drive_mbar",
                 "frame_cooling", "frame_cooling_set_mbar", "rotation_state")


class NeedLogin(Exception):
    pass


def parse_manual_rotation(html):
    """Values from the Manual Rotation page; NeedLogin if the page was refused."""
    if "<title>Access Denied" in html or 'id="BEARING_PRESSURE"' not in html:
        raise NeedLogin()
    values = {}
    for key, element in PRESSURE_IDS:
        match = re.search(r'id="{}"[^>]*>\s*(-?[\d.]+)\s*<'.format(element), html)
        values[key] = float(match.group(1)) if match else None
    match = FRAME_STATE_RE.search(html)
    values["frame_cooling"] = match.group(1).strip() if match else ""
    match = FRAME_SET_RE.search(html)
    values["frame_cooling_set_mbar"] = float(match.group(1)) if match else None
    match = ROTATION_STATE_RE.search(html)
    values["rotation_state"] = match.group(1).strip() if match else ""
    return values


class ManualRotationReader:
    """
    Reads the pressures with a login session. The only requests it ever makes:
      POST /ewp/login (user, password), GET the Manual Rotation page with
      ?session=..., and POST /ewp/logout (session) when the program stops.
    """

    def __init__(self, host, user, password, timeout):
        self.host, self.user, self.password, self.timeout = host, user, password, timeout
        self.session = None
        self.last_login_attempt = None
        self.login_error = ""

    def _request(self, path, form=None):
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        request = urllib.request.Request("http://{}{}".format(self.host, path), data=data)
        try:
            with HTTP.open(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:   # the refused page comes back as HTTP 403
            return error.read().decode("utf-8", "replace")

    def _login_allowed(self):
        return self.last_login_attempt is None or time.monotonic() - self.last_login_attempt >= MAS_RELOGIN_AFTER_S

    def _login(self):
        self.last_login_attempt = time.monotonic()
        self.session = None
        html = self._request("/ewp/login", {"user": self.user, "password": self.password})
        match = SESSION_RE.search(html)
        if not match or "logged in as" not in html:
            self.login_error = "login as {} refused".format(self.user)
            raise PermissionError(self.login_error)
        self.session = match.group(1)
        self.login_error = ""

    def read(self):
        if self.session is None:
            if not self._login_allowed():
                raise PermissionError(self.login_error or "not logged in")
            self._login()
        html = self._request(MANUAL_ROTATION_PATH + "?session=" + self.session)
        try:
            return parse_manual_rotation(html)
        except NeedLogin:
            self.session = None              # session expired or was ended elsewhere
            if not self._login_allowed():
                raise PermissionError("session ended; logging in again shortly")
            self._login()
            html = self._request(MANUAL_ROTATION_PATH + "?session=" + self.session)
            try:
                return parse_manual_rotation(html)
            except NeedLogin:
                self.session = None
                raise PermissionError("logged in as {} but the Manual Rotation page was refused".format(self.user))

    def logout(self):
        if self.session is not None:
            try:
                self._request("/ewp/logout", {"session": self.session, "logoutSubmit": "Log out"})
            except Exception:
                pass
            self.session = None


# --- Logging ------------------------------------------------------------------------

def load_mas_history(folder, name, since_epoch):
    """[(unix_time, spin_hz or NaN)] from this controller's folder; rows naming another controller are skipped and counted."""
    points, foreign = [], 0
    if not folder.is_dir():
        return points, foreign
    for path in sorted(folder.glob(name + "_*.csv")):
        try:
            if path.stat().st_mtime < since_epoch:
                continue
            with open(str(path), "r", newline="") as handle:
                for row in csv.DictReader(handle):
                    try:
                        if row.get("controller") != name:
                            foreign += 1
                            continue
                        epoch = float(row["unix_time"])
                        if epoch >= since_epoch:
                            value = (row.get("spin_rate_hz") or "").strip()
                            points.append((epoch, float(value) if value else NAN))
                    except (KeyError, TypeError, ValueError):
                        pass
        except OSError as error:
            print("Could not read {}: {}".format(path, error))
    points.sort(key=lambda item: item[0])
    return points, foreign


class MasCsvLog:
    """One MAS controller's CSV output; a new file every NEW_FILE_EVERY_S."""

    def __init__(self, folder, name, ip):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.name, self.ip = name, ip
        self.handle = self.writer = self.started = self.path = None

    def write(self, reading):
        new_path = None
        if self.handle is None or reading["epoch"] - self.started >= NEW_FILE_EVERY_S:
            self.close()
            stamp = datetime.fromtimestamp(reading["epoch"]).strftime("%Y-%m-%d_%H%M%S")
            self.path = self.folder / "{}_{}.csv".format(self.name, stamp)
            self.handle = open(str(self.path), "a", newline="")
            self.writer = csv.writer(self.handle)
            if self.handle.tell() == 0:
                self.writer.writerow(MAS_CSV_COLUMNS)
            self.started = reading["epoch"]
            new_path = self.path

        def blank(value):
            return "" if value is None else value

        self.writer.writerow([
            datetime.fromtimestamp(reading["epoch"]).isoformat(timespec="milliseconds"),
            "{:.3f}".format(reading["epoch"]), self.name, self.ip,
            blank(reading["spin_hz"]), blank(reading["signal_pct"]), reading["signal_note"],
            blank(reading["gain"]),
            "ERROR: " + reading["error"] if reading["error"] else reading["status"],
        ] + [blank(reading[key]) for key in PRESSURE_KEYS])
        self.handle.flush()
        return new_path

    def close(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


class MasPoller(threading.Thread):
    """
    Reads one MAS controller and writes its CSV. Spin rate every
    MAS_POLL_INTERVAL_S; pressures every MAS_PRESSURE_EVERY_S. While the
    controller is unreachable, one error row is written per MAS_ERROR_LOG_EVERY_S.
    """

    def __init__(self, name, cfg, folder, out_queue):
        super().__init__(daemon=True)
        self.controller = name
        self.host = cfg["host"]
        self.out_queue = out_queue
        self.stop_event = threading.Event()
        self.log = MasCsvLog(folder, name, cfg["ip"])
        self.reader = (ManualRotationReader(cfg["host"], cfg["user"], cfg["password"], MAS_REQUEST_TIMEOUT_S)
                       if cfg["read_pressures"] else None)
        self.pressures = {}
        self.pressure_epoch = None
        self.pressure_error = "" if self.reader else "pressure reading off in the config file"

    def stop(self):
        self.stop_event.set()

    def run(self):
        next_time = time.monotonic()
        next_pressure = next_time
        previous_error = False
        last_error_logged = None
        try:
            while not self.stop_event.is_set():
                reading = {"epoch": time.time(), "spin_hz": None, "signal_pct": None,
                           "signal_note": "", "gain": None, "status": "", "error": "", "status_error": False}
                reading.update((key, None) for key in PRESSURE_KEYS)
                try:
                    reading.update(read_mas_controller(self.host, MAS_REQUEST_TIMEOUT_S))
                except Exception as error:  # network, HTTP, or parse error
                    reading["error"] = "{}: {}".format(type(error).__name__, error)

                if not reading["error"] and self.reader is not None and time.monotonic() >= next_pressure:
                    next_pressure = time.monotonic() + MAS_PRESSURE_EVERY_S
                    try:
                        self.pressures = self.reader.read()
                        self.pressure_epoch = time.time()
                        self.pressure_error = ""
                    except Exception as error:
                        self.pressure_error = "{}: {}".format(type(error).__name__, error)
                if (not reading["error"] and self.pressure_epoch is not None
                        and reading["epoch"] - self.pressure_epoch <= PRESSURE_STALE_AFTER_S):
                    reading.update(self.pressures)
                reading["pressure_error"] = self.pressure_error
                if self.stop_event.is_set():
                    break

                write_row = True
                if reading["error"]:
                    write_row = (not previous_error or last_error_logged is None
                                 or reading["epoch"] - last_error_logged >= MAS_ERROR_LOG_EVERY_S)
                    if write_row:
                        last_error_logged = reading["epoch"]
                previous_error = bool(reading["error"])
                if write_row:
                    try:
                        new_path = self.log.write(reading)
                        if new_path is not None:
                            self.out_queue.put(("file", self.controller, str(new_path)))
                    except OSError as error:
                        self.out_queue.put(("log_error", self.controller, str(error)))
                self.out_queue.put(("reading", self.controller, reading))

                next_time += MAS_POLL_INTERVAL_S
                delay = next_time - time.monotonic()
                if delay < 0:
                    next_time, delay = time.monotonic(), 0
                self.stop_event.wait(delay)
        finally:
            self.log.close()
            if self.reader is not None:
                self.reader.logout()


def rmsd_about_mean(data, now, window_s):
    """RMSD of the valid readings in the last window_s about their own mean."""
    values = []
    for epoch, _, spin in reversed(data):
        if epoch < now - window_s:
            break
        if not math.isnan(spin):
            values.append(spin)
    if len(values) < RMSD_MIN_POINTS:
        return None, len(values), None
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)), len(values), mean


# ==========================================================================
# Lake Shore 336: communication and acquisition (from lakeshore336_logger.py;
# only logging paths, file rotation, and Python 3.6 compatibility changed)
# ==========================================================================

def associated(row, channel):
    """Output assigned to an input; prefer a control loop over an off/monitor output."""
    if not row:
        return None
    candidates = [n for n in range(1, 5) if row.get(f"out{n}_control_input") == channel]
    return next((n for n in candidates if row.get(f"out{n}_mode") in ("PID", "zone")),
                candidates[0] if candidates else None)


class Controller:
    def __init__(self, host, port, timeout):
        self.sock = socket.create_connection((host, port), timeout)
        self.sock.settimeout(timeout)
        self.buffer = b""
        self.last_reply = 0.0
        self.responses = {}

    def close(self):
        self.sock.close()

    def query(self, command):
        if not READ_QUERY.fullmatch(command):
            raise ValueError(f"Query is not in the read-only allowlist: {command!r}")
        # Keep requests separate; TCP packets do not define response boundaries.
        time.sleep(max(0.0, QUERY_GAP_SECONDS - (time.monotonic() - self.last_reply)))
        self.sock.sendall((command + "\r\n").encode("ascii"))
        deadline = time.monotonic() + self.sock.gettimeout()
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for {command}")
            timeout = self.sock.gettimeout()
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(4096)
            finally:
                self.sock.settimeout(timeout)
            if not chunk:
                raise ConnectionError(f"Controller disconnected during {command}")
            self.buffer += chunk
            if len(self.buffer) > 8192:
                raise ValueError("Oversized controller response")
        line, self.buffer = self.buffer.split(b"\n", 1)
        self.last_reply = time.monotonic()
        reply = line.decode("ascii").strip()
        if not reply:
            raise ValueError(f"Empty response to {command}")
        self.responses[command] = reply
        return reply

    def apply_control(self, request, controls):
        self.control_write_attempted = False
        self.control_target_K = None
        self.control_active_sp_K = None
        output, channel = request["output"], request["channel"]
        if output not in (1, 2) or channel not in ("A", "B"):
            raise ValueError("Controls support heater outputs 1 and 2 assigned to A/B")
        controls.check(request)
        mode, assigned, _ = map(int, self.query(f"OUTMODE? {output}").split(","))
        if assigned != {"A": 1, "B": 2}[channel]:
            raise ValueError("Output assignment changed; switch Control off/on to reload")
        units = int(self.query(f"INTYPE? {channel}").split(",")[-1])
        if units not in (1, 2) or units != request["units"]:
            raise ValueError("Input units changed or are not temperature units; reload controls")
        wanted = validate_controls(request["values"])
        baseline = request["baseline"]
        change_sp = wanted[0] != baseline[0]
        change_pid = wanted[1:] != baseline[1:]
        actual_sp = number(self.query(f"SETP? {output}"))
        actual_sp_K = actual_sp if units == 1 else actual_sp + 273.15
        actual_pid = tuple(map(number, self.query(f"PID? {output}").split(",")))
        ramp_enabled, ramp_rate = self.query(f"RAMP? {output}").split(",")
        actual_ramp = number(ramp_rate) if int(ramp_enabled) else 0.0
        was_ramping = bool(int(self.query(f"RAMPST? {output}")))
        wanted_ramp = validate_ramp(request.get("ramp_rate", actual_ramp))
        baseline_ramp = request.get("ramp_baseline", actual_ramp)
        change_ramp = not math.isclose(wanted_ramp, baseline_ramp, abs_tol=0.001)
        if change_ramp and not math.isclose(actual_ramp, baseline_ramp, abs_tol=0.001):
            raise ValueError("Ramp setting changed at controller; switch Control off/on to reload")
        wanted_range = request.get("range")
        range_baseline = request.get("range_baseline")
        actual_range = int(self.query(f"RANGE? {output}"))
        change_range = wanted_range is not None and wanted_range != range_baseline
        if change_range:
            if wanted_range not in (0, 1, 2, 3):
                raise ValueError("Heater range must be Off, Low, Med, or High")
            if actual_range not in (range_baseline, wanted_range):
                raise ValueError("Heater range changed at controller; switch Control off/on to reload")
            change_range = actual_range != wanted_range
        # A previous attempt may already have reached the target despite a lost reply.
        change_sp = change_sp and not math.isclose(actual_sp_K, wanted[0], abs_tol=0.001)
        change_pid = change_pid and any(not math.isclose(a, b, abs_tol=0.001)
                                        for a, b in zip(actual_pid, wanted[1:]))
        if change_sp and not was_ramping and not math.isclose(actual_sp_K, baseline[0], abs_tol=0.001):
            raise ValueError("Setpoint changed at controller; switch Control off/on to reload")
        if change_pid and any(not math.isclose(a, b, abs_tol=0.001)
                              for a, b in zip(actual_pid, baseline[1:])):
            raise ValueError("PID changed at controller; switch Control off/on to reload")
        commands = []
        if change_ramp:
            commands.append(f"RAMP {output},{int(wanted_ramp > 0)},{wanted_ramp:g}")
        if change_sp:
            raw_sp = wanted[0] if units == 1 else wanted[0] - 273.15
            commands.append(f"SETP {output},{raw_sp:.6g}")
        if change_pid:
            commands.append(f"PID {output}," + ",".join(f"{v:g}" for v in wanted[1:]))
        if change_range:
            commands.append(f"RANGE {output},{wanted_range}")
        for command in commands:
            controls.check(request)
            time.sleep(max(0.0, QUERY_GAP_SECONDS - (time.monotonic() - self.last_reply)))
            controls.check(request)
            self.control_write_attempted = True
            self.sock.sendall((command + "\r\n").encode("ascii"))
            self.last_reply = time.monotonic()
        # Read back without retrying writes: a lost response never replays a change.
        deadline = time.monotonic() + 2.0
        while True:
            read_sp = number(self.query(f"SETP? {output}"))
            read_sp_K = read_sp if units == 1 else read_sp + 273.15
            self.control_active_sp_K = read_sp_K
            read_pid = tuple(map(number, self.query(f"PID? {output}").split(",")))
            ramp_on, rate = self.query(f"RAMP? {output}").split(",")
            read_rate = number(rate) if int(ramp_on) else 0.0
            ramping = bool(int(self.query(f"RAMPST? {output}")))
            read_range = int(self.query(f"RANGE? {output}"))
            range_ok = not change_range or read_range == wanted_range
            sp_ok = not change_sp or math.isclose(read_sp_K, wanted[0], rel_tol=1e-5, abs_tol=0.001)
            pid_ok = not change_pid or all(math.isclose(a, b, abs_tol=0.051 if n < 2 else 0.51)
                                          for n, (a, b) in enumerate(zip(read_pid, wanted[1:])))
            ramp_ok = not change_ramp or math.isclose(read_rate, wanted_ramp, abs_tol=0.051)
            ramp_progress = (change_sp and ramping and read_rate > 0 and
                             min(actual_sp_K, wanted[0]) - .01 <= read_sp_K <= max(actual_sp_K, wanted[0]) + .01)
            if ramp_progress and pid_ok and ramp_ok and range_ok and not sp_ok:
                self.control_target_K = wanted[0]
                return (f"Target {wanted[0]:g} K sent; ramp active at {read_rate:g} K/min "
                        f"(active setpoint {read_sp_K:g} K)")
            if sp_ok and pid_ok and ramp_ok and range_ok:
                break
            if time.monotonic() >= deadline:
                raise ValueError(f"Setpoint/PID/range readback differs: SP {read_sp_K:g} K, PID {read_pid}, "
                                 f"range {read_range}; requested SP {wanted[0]:g} K, PID {wanted[1:]}, "
                                 f"ramp {wanted_ramp:g} K/min, range {wanted_range}")
            time.sleep(0.1)  # Repeat read queries only, never the write commands.
        return "Applied and read back" if commands else "No changes to apply"

    def all_heaters_off(self, request, controls):
        """RANGE 1,0 and RANGE 2,0 (both heater outputs off), then read back."""
        self.control_write_attempted = False
        self.control_target_K = self.control_active_sp_K = None
        controls.check(request)
        for output in (1, 2):
            time.sleep(max(0.0, QUERY_GAP_SECONDS - (time.monotonic() - self.last_reply)))
            self.control_write_attempted = True
            self.sock.sendall(f"RANGE {output},0\r\n".encode("ascii"))
            self.last_reply = time.monotonic()
        deadline = time.monotonic() + 2.0
        while True:            # read back; never repeat the writes
            ranges = [int(self.query(f"RANGE? {output}")) for output in (1, 2)]
            if ranges == [0, 0]:
                return "ALL OFF: heater outputs 1 and 2 are off (read back)"
            if time.monotonic() >= deadline:
                raise ValueError(f"ALL OFF read-back shows ranges {ranges}")
            time.sleep(0.1)

    def sample(self, identity, responses=None):
        query = self.query if responses is None else responses.__getitem__
        row = {"timestamp_utc": utc_now(), "identity": identity, "error": ""}
        for channel in "ABCD":
            row[f"temp_{channel}_K"] = number(query(f"KRDG? {channel}"))
            row[f"status_{channel}"] = int(query(f"RDGST? {channel}"))
            setup = query(f"INTYPE? {channel}").split(",")
            row[f"units_{channel}"] = {1: "K", 2: "C", 3: "sensor"}[int(setup[-1])]
        for output in range(1, 5):
            prefix = f"out{output}_"
            mode, control_input, powerup = map(int, query(f"OUTMODE? {output}").split(","))
            row[prefix + "mode"] = MODES.get(mode, str(mode))
            row[prefix + "control_input"] = (
                f"output{control_input}" if mode == 6 else INPUTS.get(control_input, str(control_input)))
            row[prefix + "powerup_enable"] = powerup
            p, i, d = map(number, query(f"PID? {output}").split(","))
            row.update({prefix + "P": p, prefix + "I": i, prefix + "D": d})
            row[prefix + "setpoint"] = number(query(f"SETP? {output}"))
            units = row.get(f"units_{row[prefix + 'control_input']}", "unknown")
            row[prefix + "setpoint_units"] = units
            setpoint = row[prefix + "setpoint"]
            row[prefix + "setpoint_K"] = (
                setpoint if units == "K" else setpoint + 273.15 if units == "C" else "")
            row[prefix + "range_code"] = int(query(f"RANGE? {output}"))
            command = "HTR" if output <= 2 else "AOUT"
            row[prefix + "level_percent"] = number(query(f"{command}? {output}"))
            if output <= 2:
                setup = query(f"HTRSET? {output}").split(",")
                if len(setup) != 4:
                    raise ValueError(f"Unexpected heater setup response: {setup!r}")
                row[prefix + "level_basis"] = {1: "current", 2: "power"}[int(setup[3])]
                enabled, rate = query(f"RAMP? {output}").split(",")
                row[prefix + "ramp_enabled"] = int(enabled)
                row[prefix + "ramp_rate_K_per_min"] = number(rate)
                row[prefix + "ramping"] = int(query(f"RAMPST? {output}"))
                status = ""
                if LS_FEATURES["htrst"]:
                    try:
                        status = int(query(f"HTRST? {output}"))
                    except KeyError:            # not in the cached responses
                        pass
                    except (TimeoutError, socket.timeout):    # unanswered: stop asking, keep logging
                        LS_FEATURES["htrst"] = False
                        self.buffer = b""
                        print("Lake Shore: HTRST? not answered; heater fault status disabled", file=sys.stderr)
                row[prefix + "heater_status"] = status
            else:
                row[prefix + "level_basis"] = "analog_full_scale"
        row["sample_end_utc"] = utc_now()
        return row


class DualRateSampler:
    """Fit background reads between the deadlines for the plotted A/B values."""

    def __init__(self, controller, interval):
        self.controller = controller
        self.interval = interval
        self.cache = dict(controller.responses)
        self.fast_queries = self.choose_fast_queries(identity="")
        self.background_queries = tuple(q for q in self.cache if q != "*IDN?" and q not in self.fast_queries)
        self.background = deque(self.background_queries)
        self.fast_due = time.monotonic()
        self.full_due = self.fast_due + FULL_REFRESH_SECONDS
        self.last_fast = None
        self.last_fast_start = None
        self.previous_interval = interval.seconds
        self.full_readback_utc = utc_now()

    def choose_fast_queries(self, identity):
        context = self.controller.sample(identity, self.cache)
        outputs = {associated(context, channel) for channel in ("A", "B")}
        queries = list(FAST_QUERIES[:2])
        for output in sorted(n for n in outputs if n is not None):
            queries += [f"HTR? {output}" if output <= 2 else f"AOUT? {output}", f"SETP? {output}"]
        return tuple(queries)

    def next(self, identity, stop, controls=None):
        self.cache.update(self.controller.responses)  # Includes any explicit Apply readbacks.
        while not stop.is_set():
            if self.interval.seconds >= FULL_REFRESH_SECONDS or (controls is not None and controls.pending.is_set()):
                return None
            now = time.monotonic()
            if self.previous_interval != self.interval.seconds:
                if self.last_fast_start is not None:
                    self.fast_due = self.last_fast_start + self.interval.seconds
                self.previous_interval = self.interval.seconds
            if now >= self.full_due and not self.background and self.last_fast is not None:
                row = self.controller.sample(identity, self.cache)
                row["timestamp_utc"] = self.last_fast["timestamp_utc"]
                row["_fast_mode"] = True
                row["_fast_read_seconds"] = self.last_fast["_fast_read_seconds"]
                self.full_readback_utc = utc_now()
                self.full_due = max(self.full_due + FULL_REFRESH_SECONDS, now + 0.01)
                self.background = deque(self.background_queries)
                return row
            if now >= self.fast_due:
                started = time.monotonic()
                self.last_fast_start = started
                timestamp = utc_now()
                # Resolve the live outputs assigned to A and B from the latest configuration.
                queries = self.choose_fast_queries(identity)
                if queries != self.fast_queries:
                    self.fast_queries = queries
                    self.background_queries = tuple(q for q in self.cache if q != "*IDN?" and q not in queries)
                    self.background = deque(self.background_queries)
                    self.full_due = now + FULL_REFRESH_SECONDS
                for query in queries:
                    self.cache[query] = self.controller.query(query)
                row = self.controller.sample(identity, self.cache)
                row["timestamp_utc"] = timestamp
                row["_fast"] = True
                row["_fast_mode"] = True
                row["_fast_read_seconds"] = time.monotonic() - started
                row["_full_readback_utc"] = self.full_readback_utc
                self.last_fast = row
                self.fast_due = max(self.fast_due + self.interval.seconds,
                                    started + self.interval.seconds)
                return row
            if self.background and now + 0.09 < self.fast_due:
                query = self.background.popleft()
                self.cache[query] = self.controller.query(query)
                continue
            until = self.fast_due - time.monotonic()
            if not self.background:
                until = min(until, self.full_due - time.monotonic())
            stop.wait(min(0.05, max(0.001, until)))
        return None


def fieldnames():
    fields = ["timestamp_utc", "sample_end_utc", "identity", "error"]
    for channel in "ABCD":
        fields += [f"temp_{channel}_K", f"status_{channel}", f"units_{channel}"]
    for output in range(1, 5):
        fields += [f"out{output}_{name}" for name in (
            "mode", "control_input", "powerup_enable", "P", "I", "D",
            "range_code", "level_percent", "level_basis", "setpoint",
            "setpoint_units", "setpoint_K")]
        if output <= 2:
            fields += [f"out{output}_{name}" for name in ("ramp_enabled", "ramp_rate_K_per_min", "ramping",
                                                          "heater_status")]
    return fields


def fast_record(row):
    record = {key: row.get(key, "") for key in ("timestamp_utc", "sample_end_utc", "identity")}
    record["full_readback_utc"] = row.get("_full_readback_utc", "")
    for channel, name in (("A", "bearing"), ("B", "drive")):
        output = associated(row, channel)
        record.update({f"{name}_temperature_K": row.get(f"temp_{channel}_K", ""),
                       f"{name}_status": row.get(f"status_{channel}", ""),
                       f"{name}_output": output if output is not None else "",
                       f"{name}_heater_percent": row.get(f"out{output}_level_percent", ""),
                       f"{name}_setpoint_K": row.get(f"out{output}_setpoint_K", "")})
    return record


def positive_seconds(text):
    value = number(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("Must be greater than zero")
    return value


def validate_controls(values):
    sp, p, i, d = map(number, values)
    if not 0 <= sp <= 999999:
        raise ValueError("Setpoint must be 0–999999 K; controller curve limits also apply")
    if not (0.1 <= p <= 1000 and 0.1 <= i <= 1000 and 0 <= d <= 200):
        raise ValueError("Use P/I 0.1–1000 and D 0–200")
    if any(not math.isclose(v * 10, round(v * 10), abs_tol=1e-6) for v in (p, i)) or not d.is_integer():
        raise ValueError("Use increments of 0.1 for P/I and whole numbers for D")
    return sp, p, i, d


def validate_ramp(value):
    rate = number(value)
    if not 0 <= rate <= 100 or not math.isclose(rate * 10, round(rate * 10), abs_tol=1e-6):
        raise ValueError("Ramp must be 0–100 K/min, in steps of 0.1; 0 turns ramping off")
    return rate


class ControlState:
    def __init__(self):
        self.enabled = False
        self.generation = 0
        self.requests = queue.Queue()
        self.pending = threading.Event()
        self.last_activity = 0.0

    def set_enabled(self, enabled):
        self.generation += 1
        self.enabled = enabled
        self.last_activity = time.monotonic() if enabled else 0.0

    def touch(self):
        if self.enabled:
            self.last_activity = time.monotonic()

    def remaining(self):
        return max(0.0, CONTROL_IDLE_SECONDS - (time.monotonic() - self.last_activity))

    def submit(self, request):
        if not self.enabled or self.remaining() <= 0:
            raise ValueError("Enable Control before applying changes")
        request = dict(request, generation=self.generation)
        self.requests.put(request)
        self.pending.set()

    def check(self, request):
        if not self.enabled or self.remaining() <= 0 or request["generation"] != self.generation:
            raise ValueError("Control disabled; pending change cancelled")


class SamplingInterval:
    """Wake the waiting sampler when an interval edit changes its next deadline."""

    def __init__(self, seconds):
        self.condition = threading.Condition()
        self.seconds = seconds

    def set(self, text):
        seconds = number(text)
        if seconds < MIN_INTERVAL_SECONDS:
            raise ValueError("Use a finite interval of at least {:g} seconds".format(MIN_INTERVAL_SECONDS))
        with self.condition:
            self.seconds = seconds
            self.condition.notify_all()
        return seconds

    def wait(self, started, stop, pending=None):
        with self.condition:
            while not stop.is_set():
                if pending is not None and pending.is_set():
                    break
                remaining = started + self.seconds - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(min(remaining, 0.2))


class LakeShoreLog:
    """Full and fast CSV files in lakeshore336_logs/, rotated every NEW_FILE_EVERY_S."""

    def __init__(self, folder, on_file):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.on_file = on_file
        self.fields = fieldnames()
        self.file = self.writer = self.fast_file = self.fast_writer = None
        self.path = None
        self.started = None

    def _rotate_if_due(self):
        if self.file is not None and time.monotonic() - self.started < NEW_FILE_EVERY_S:
            return
        self.close()
        name = datetime.now(timezone.utc).strftime("lakeshore336_%Y%m%dT%H%M%S_%fZ.csv")
        self.path = self.folder / name
        self.file = self.path.open("a", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=self.fields)
        self.writer.writeheader()
        self.file.flush()
        self.started = time.monotonic()
        print(f"Lake Shore log: {self.path}", file=sys.stderr)
        self.on_file(str(self.path))

    def write_full(self, row):
        self._rotate_if_due()
        self.writer.writerow({key: row.get(key, "") for key in self.fields})
        self.file.flush()

    def write_fast(self, record):
        self._rotate_if_due()
        if self.fast_file is None:
            fast_path = self.path.with_name(self.path.stem + "_fast.csv")
            self.fast_file = fast_path.open("a", newline="", encoding="utf-8")
            self.fast_writer = csv.DictWriter(self.fast_file, fieldnames=list(record))
            self.fast_writer.writeheader()
        self.fast_writer.writerow(record)
        self.fast_file.flush()

    def close(self):
        for handle in (self.file, self.fast_file):
            if handle is not None:
                handle.close()
        self.file = self.fast_file = None


def acquire(args, stop, on_row, interval, controls, on_notice, on_file):
    """Lake Shore acquisition loop (runs in a worker thread)."""
    log = LakeShoreLog(Path(args.base_dir) / LS_LOG_SUBDIR, on_file)
    controller = None
    sampler = None
    identity = ""
    failed = False
    try:
        while not stop.is_set():
            started = time.monotonic()
            timestamp = utc_now()
            try:
                if controller is None:
                    controller = Controller(args.ls_host, args.ls_port, args.timeout)
                    sampler = None
                    identity = controller.query("*IDN?")
                    parts = identity.split(",")
                    if len(parts) < 2 or parts[1].strip().upper() != "MODEL336":
                        raise ValueError(f"Expected MODEL336, received {identity!r}")
                    print(f"Connected: {identity}", file=sys.stderr)
                controls.pending.clear()
                while not controls.requests.empty():
                    request = controls.requests.get_nowait()
                    try:
                        if request.get("all_off"):
                            message = controller.all_heaters_off(request, controls)
                        else:
                            message = controller.apply_control(request, controls)
                    except (OSError, ValueError) as exc:
                        outcome = ("Change sent; readback not confirmed" if
                                   getattr(controller, "control_write_attempted", False)
                                   else "No change sent")
                        message = f"{outcome}: {exc}. Check live values before retrying."
                        print(f"{request['channel']}: {message}", file=sys.stderr)
                        on_notice({"channel": request["channel"], "error": True, "message": message,
                                   "channels": request.get("channels", ())})
                        # Always discard the failed request; transport failures reconnect.
                        if isinstance(exc, OSError):
                            raise
                    else:
                        on_notice({"channel": request["channel"], "error": False, "message": message,
                                   "target_K": getattr(controller, "control_target_K", None),
                                   "active_sp_K": getattr(controller, "control_active_sp_K", None),
                                   "desired_K": request.get("values", (None,))[0],
                                   "output": request.get("output"), "channels": request.get("channels", ())})
                if interval.seconds < FULL_REFRESH_SECONDS and hasattr(controller, "responses"):
                    if sampler is None:
                        row = controller.sample(identity)  # One complete startup snapshot.
                        row["_fast_mode"] = True
                        sampler = DualRateSampler(controller, interval)
                    else:
                        row = sampler.next(identity, stop, controls)
                        if row is None:
                            continue
                else:
                    sampler = None
                    row = controller.sample(identity)
            except (OSError, ValueError, KeyError) as exc:
                failed = True
                controls.set_enabled(False)
                while not controls.requests.empty():
                    cancelled = controls.requests.get_nowait()
                    on_notice({"channel": cancelled["channel"], "error": True,
                               "message": "Disconnected; queued change cancelled",
                               "channels": cancelled.get("channels", ())})
                controls.pending.clear()
                on_notice({"channel": None, "error": True, "message": "Disconnected; Control switched off"})
                row = {"timestamp_utc": timestamp, "sample_end_utc": utc_now(),
                       "identity": identity, "error": f"{type(exc).__name__}: {exc}"}
                print(row["error"], file=sys.stderr)
                if controller is not None:
                    controller.close()
                    controller = None
                identity = ""
                sampler = None
            if row.get("_fast"):
                log.write_fast(fast_record(row))
                on_row(row)
                continue
            log.write_full(row)
            on_row(row)
            if sampler is None:
                interval.wait(started, stop, controls.pending)
    finally:
        if controller is not None:
            controller.close()
        log.close()
    return 1 if failed else 0


def reading_status(row, channel):
    """RDGST code of an input (0 = valid reading); missing counts as 0, as in the original plot."""
    value = number_or_nan(row.get(f"status_{channel}"))
    return int(value) if math.isfinite(value) else 0


def temperature_point(row, epoch):
    """(epoch, T_A, T_B, heater_A %, heater_B %, setpoint_A K, setpoint_B K); NaN where unavailable."""
    if row.get("error"):
        return (epoch, NAN, NAN, NAN, NAN, NAN, NAN)
    temps, heaters, setpoints = [], [], []
    for channel, _, _ in CHANNELS:
        status = number_or_nan(row.get(f"status_{channel}"))
        temps.append(number_or_nan(row.get(f"temp_{channel}_K")) if status == 0 else NAN)
        output = associated(row, channel)
        heaters.append(number_or_nan(row.get(f"out{output}_level_percent")) if output else NAN)
        setpoints.append(number_or_nan(row.get(f"out{output}_setpoint_K")) if output else NAN)
    return tuple([epoch] + temps + heaters + setpoints)


def load_lakeshore_history(folder, since_epoch):
    """Temperature points from the full (not _fast) CSV files in folder."""
    points = []
    if not folder.is_dir():
        return points
    for path in sorted(folder.glob("lakeshore336_*.csv")):
        if path.name.endswith("_fast.csv"):
            continue
        try:
            if path.stat().st_mtime < since_epoch:
                continue
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    try:
                        epoch = parse_iso(row["timestamp_utc"]).timestamp()
                    except (KeyError, TypeError, ValueError, AttributeError):
                        continue
                    if epoch >= since_epoch:
                        points.append(temperature_point(row, epoch))
        except OSError as error:
            print("Could not read {}: {}".format(path, error))
    points.sort(key=lambda item: item[0])
    return points


# ==========================================================================
# AMI Model 1700 nitrogen level meter (heat exchanger)
# ==========================================================================
#
# Reading: GET http://<ip>/get_json.cgi, the same JSON the instrument's own
# web page polls (no login). Writing (fill start/stop only): the documented
# SCPI interface on TCP port 7180 ("CONF:FILL:B <start>", "CONF:FILL:A <stop>"),
# followed by a read-back through get_json.cgi.

AMI_ERRORS = {-1: "LO setpoint out of range", -2: "fill B (start) out of range",
              -3: "fill A (stop) out of range", -4: "HI setpoint out of range",
              -5: "length set in percent mode", -6: "calibration value out of range",
              -7: "interval out of range", -8: "unrecognized command", -9: "invalid argument",
              -10: "calibration factor out of range", -11: "SCPI buffer overflow"}
AMI_FILL_STATES = {0: "AUTOFILL idle", 1: "FILLING", 2: "FILL TIMEOUT", 3: "autofill off"}
# Mode buttons (Off / Fill / Auto). The instrument's remote commands cannot change its fill mode
# (AUTOFILL, M-OPEN, M-CLOSED are front-panel/web only), so the modes are made with the documented
# fill-level commands while the instrument stays in AUTOFILL:
#   Off  = fill start 0.0 % (the manual: "If the START value is set to 0.0% the autofill function
#          will be disabled"); a fill under way is stopped by briefly lowering the stop level.
#   Fill = fill start raised just above the present level: the instrument opens the valve, closes it
#          at its own fill-stop level, and its fill timeout still applies. When the valve has closed
#          again the monitor puts the start level back (to the saved one, or to 0 if it was Off).
#   Auto = the saved fill start.
# The saved start level and the mode live in AMI_MODE_FILE, so a restart of the monitor finishes the job.
AMI_MODE_FILE = "ami1700_mode.json"
AMI_MODES = (("off", "Off"), ("fill", "Fill"), ("auto", "Auto"))
AMI_FILL_MARGIN = 1.0          # Fill: start level = present level + this (percent)
AMI_FILL_MIN_ROOM = 2.0        # Fill needs the level at least this far below the fill stop
AMI_FILL_START_WAIT_S = 180    # Fill: give up if the valve has not opened by then
AMI_FILL_POLL_S = 10           # poll this often while a Fill is under way
AMI_FILL_MODES = {1: "MANUAL valve open", 2: "MANUAL valve closed"}
AMI_SENSOR_ERRORS = {"LOS": "LOSS OF SENSOR", "SHORT": "SENSOR SHORTED", "UNCAL": "UNCALIBRATED"}
AMI_CSV_COLUMNS = [
    "time_local", "unix_time", "ip", "ln2_level", "ln2_level_display", "unit_code",
    "autofill_start", "autofill_stop", "autofill_timeout", "autofill_mode", "autofill_state",
    "valve_open", "alarm", "level_alarm", "timeout_alarm",
    "alarm1_setpoint", "alarm1_active", "alarm2_setpoint", "alarm2_active",
    "instrument_time", "status", "event",
]


def _ami_number(doc, key):
    try:
        value = float(doc.get(key))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _ami_int(doc, key):
    value = _ami_number(doc, key)
    return None if value is None else int(value)


def read_ami(cfg, timeout=5.0):
    """One reading of the AMI 1700 as a flat dict."""
    host = cfg["ip"] if cfg["http_port"] == 80 else "{}:{}".format(cfg["ip"], cfg["http_port"])
    with HTTP.open("http://{}/get_json.cgi".format(host), timeout=timeout) as response:
        doc = json.loads(response.read().decode("utf-8", "replace"))
    reading = {
        "ln2_level": _ami_number(doc, "LN2_Level"),
        "ln2_level_display": str(doc.get("LN2_Level_display", "")).strip(),
        "unit_code": _ami_int(doc, "LN2_Level_display_unit"),
        "ln2_enabled": _ami_int(doc, "LN2_Enabled"),
        "fill_channel": _ami_int(doc, "AutoFillDewar"),
        "autofill_start": _ami_number(doc, "AutoFillStart"),
        "autofill_stop": _ami_number(doc, "AutoFillStop"),
        "autofill_timeout": _ami_number(doc, "AutoFillTimeout"),
        "autofill_mode": _ami_int(doc, "AutoFillMode"),
        "autofill_state": _ami_int(doc, "AutoFillAnnunciator"),
        "valve_open": _ami_int(doc, "hw_Valve_open"),
        "alarm": _ami_int(doc, "AlarmAnnunciator"),
        "level_alarm": _ami_int(doc, "LN2_Level_Annunciator"),
        "timeout_alarm": _ami_int(doc, "LN2_Timeout_Annunciator"),
        "instrument_time": str(doc.get("SysDateTime", "")).strip(),
    }
    for n in (1, 2):
        reading["alarm{}_setpoint".format(n)] = _ami_number(doc, "LN2_Level_SetPoint{}_display".format(n))
        reading["alarm{}_active".format(n)] = _ami_int(doc, "LN2_Level_SetPoint{}_Annunciator".format(n))
        reading["alarm{}_sense".format(n)] = _ami_int(doc, "AlarmRelay{}ComparisonSense".format(n))
    if reading["ln2_level"] is None and reading["ln2_level_display"] not in AMI_SENSOR_ERRORS:
        raise ValueError("no LN2_Level in the instrument's reply")
    return reading


class AmiScpi:
    """One SCPI session on the AMI 1700's TCP port (used only to change the fill setpoints)."""

    def __init__(self, host, port, timeout=3.0):
        self.sock = socket.create_connection((host, port), timeout)
        self.buffer = b""
        self.sock.settimeout(0.5)
        try:                                   # discard a greeting, if the instrument sends one
            while self.sock.recv(4096):
                pass
        except socket.timeout:
            pass
        self.sock.settimeout(timeout)

    def command(self, text):
        """Send one command; return the reply line, or None if the instrument does not reply."""
        self.sock.sendall((text + "\n").encode("ascii"))
        deadline = time.monotonic() + 2.0
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("AMI 1700 closed the connection")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        reply = line.decode("ascii", "replace").strip()
        if re.match(r"^-\d+$", reply):
            code = int(reply)
            raise ValueError("instrument error {} ({}) for '{}'".format(code, AMI_ERRORS.get(code, "?"), text))
        return reply

    def close(self):
        self.sock.close()


def validate_fill(start_text, stop_text):
    try:
        start, stop = number(start_text), number(stop_text)
    except ValueError:
        raise ValueError("Enter numbers for both fill levels")
    if not 0 <= start < stop <= 100:
        raise ValueError("Use 0 <= fill start < fill stop <= 100 %")
    if any(not math.isclose(v * 10, round(v * 10), abs_tol=1e-6) for v in (start, stop)):
        raise ValueError("Use steps of 0.1 % for the fill levels")
    return start, stop


class AmiLog:
    """AMI 1700 CSV output; a new file every NEW_FILE_EVERY_S."""

    def __init__(self, folder, ip):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.ip = ip
        self.handle = self.writer = self.started = None

    def write(self, epoch, reading, status, event=""):
        if self.handle is None or epoch - self.started >= NEW_FILE_EVERY_S:
            self.close()
            path = self.folder / "ami1700_{}.csv".format(datetime.fromtimestamp(epoch).strftime("%Y-%m-%d_%H%M%S"))
            self.handle = open(str(path), "a", newline="")
            self.writer = csv.writer(self.handle)
            if self.handle.tell() == 0:
                self.writer.writerow(AMI_CSV_COLUMNS)
            self.started = epoch
        values = [datetime.fromtimestamp(epoch).isoformat(timespec="seconds"), "{:.3f}".format(epoch), self.ip]
        for key in AMI_CSV_COLUMNS[3:-2]:
            value = reading.get(key)
            values.append("" if value is None else value)
        self.writer.writerow(values + [status, event])
        self.handle.flush()

    def close(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


class AmiPoller(threading.Thread):
    """Reads the AMI 1700 every poll_seconds (and on request) and carries out queued fill-setpoint changes."""

    def __init__(self, cfg, folder, out_queue, controls):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.out_queue = out_queue
        self.controls = controls
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.log = AmiLog(folder, cfg["ip"])
        self.write_attempted = False
        self.mode_path = Path(folder).parent / AMI_MODE_FILE
        self.mode_state = self._load_mode()

    def stop(self):
        self.stop_event.set()
        self.wake.set()

    def poll(self, event=""):
        epoch = time.time()
        try:
            reading, status = read_ami(self.cfg), "ok"
        except Exception as error:
            reading, status = {}, "ERROR: {}: {}".format(type(error).__name__, error)
        if reading:
            note = self.supervise(reading)
            if note:
                event = (event + "; " if event else "") + note
                try:                       # show and log the levels as they are after the change
                    reading = read_ami(self.cfg)
                except Exception:
                    pass
        try:
            self.log.write(epoch, reading, status, event)
        except OSError as error:
            status = "LOG FILE WRITE FAILED: {}".format(error)
        self.out_queue.put(("reading", dict(reading, epoch=epoch, error="" if status == "ok" else status,
                                            mode_state=dict(self.mode_state))))

    # ---- Off / Fill / Auto --------------------------------------------------------------

    def _load_mode(self):
        try:
            state = json.loads(self.mode_path.read_text())
            return state if isinstance(state, dict) and state.get("mode") in ("off", "fill") else {}
        except (OSError, ValueError):
            return {}

    def _save_mode(self, state):
        self.mode_state = state
        try:
            if not state:
                if self.mode_path.exists():
                    self.mode_path.unlink()
                return
            partial = self.mode_path.with_name(self.mode_path.name + ".part")
            partial.write_text(json.dumps(state, indent=1))
            os.replace(str(partial), str(self.mode_path))
        except OSError as error:
            print("AMI 1700: could not save {}: {}".format(self.mode_path, error), file=sys.stderr)

    def _send(self, commands, request=None):
        session = AmiScpi(self.cfg["ip"], self.cfg["scpi_port"])
        try:
            for command in commands:
                if request is not None:
                    self.controls.check(request)
                self.write_attempted = True
                session.command(command)
        finally:
            session.close()

    def _read_back(self, test, what, seconds=8.0):
        deadline = time.monotonic() + seconds
        while True:
            time.sleep(1.0)
            check = read_ami(self.cfg)
            if test(check):
                return check
            if time.monotonic() >= deadline:
                raise ValueError("read-back does not show {} (fill start {:g} %, stop {:g} %, valve {})".format(
                    what, check["autofill_start"], check["autofill_stop"], "open" if check["valve_open"] else "closed"))

    @staticmethod
    def _ready(current):
        if current["unit_code"] != 0:
            raise ValueError("the instrument is not set to percent units")
        if current["fill_channel"] != 1:
            raise ValueError("autofill is not assigned to the nitrogen channel")
        if current["autofill_mode"] in AMI_FILL_MODES:
            raise ValueError("the instrument is in {}; select AUTOFILL on its front panel first".format(
                AMI_FILL_MODES[current["autofill_mode"]]))
        if current["autofill_start"] is None or current["autofill_stop"] is None:
            raise ValueError("the instrument did not report its fill levels")

    def set_mode(self, request):
        self.write_attempted = False
        self.controls.check(request)
        current = read_ami(self.cfg)
        self._ready(current)
        target = request["mode"]
        mode = self.mode_state.get("mode", "auto")
        start, stop, level = current["autofill_start"], current["autofill_stop"], current["ln2_level"]
        normal = self.mode_state.get("saved_start") if mode in ("off", "fill") else start

        if target == "auto":
            if mode == "auto" and start > 0:
                return "Already in Auto"
            if not normal or normal <= 0:
                raise ValueError("no earlier fill start level to return to; enter the fill levels and Apply")
            if normal >= stop:
                raise ValueError("the saved fill start ({:g} %) is not below the fill stop ({:g} %)".format(normal, stop))
            self._send(["CONF:FILL:B {:.1f}".format(normal)], request)
            self._save_mode({})
            self._read_back(lambda c: math.isclose(c["autofill_start"], normal, abs_tol=0.05), "the fill start back")
            return "Auto: fill start back to {:g} % (stop {:g} %)".format(normal, stop)

        if target == "off":
            if mode == "off" and start == 0:
                return "Already off"
            if not normal or normal <= 0:
                normal = None              # it was already 0 at the instrument; Auto will need levels entered
            self._save_mode({"mode": "off", "saved_start": normal, "since": time.time()})   # saved before sending
            self._send(["CONF:FILL:B 0.0"], request)
            check = self._read_back(lambda c: c["autofill_start"] == 0, "fill start 0 %")
            if check["valve_open"]:
                self._stop_running_fill(check)
            return "Off: autofill disabled (fill start 0 %){}".format(
                "; Auto returns to {:g} %".format(normal) if normal else "")

        if target == "fill":
            if mode == "fill":
                return "A fill is already under way"
            if current["autofill_state"] == 2 or current["timeout_alarm"]:
                raise ValueError("the fill-timeout alarm is active; clear it on the instrument first")
            if level is None or current["ln2_level_display"] in AMI_SENSOR_ERRORS:
                raise ValueError("no valid level reading")
            if level > stop - AMI_FILL_MIN_ROOM:
                raise ValueError("the level ({:.1f} %) is already within {:g} % of the fill stop ({:g} %)".format(
                    level, AMI_FILL_MIN_ROOM, stop))
            raised = math.floor((level + AMI_FILL_MARGIN) * 10) / 10
            self._save_mode({"mode": "fill", "saved_start": normal, "raised_start": raised, "since": time.time(),
                             "valve_seen_open": bool(current["valve_open"]), "return_to": mode})
            self._send(["CONF:FILL:B {:.1f}".format(raised)], request)
            self._read_back(lambda c: math.isclose(c["autofill_start"], raised, abs_tol=0.05), "the raised fill start")
            return "Fill: filling to {:g} %; the fill start returns to {} afterwards".format(
                stop, "{:g} %".format(normal) if mode == "auto" else "0 % (Off)")
        raise ValueError("unknown mode {!r}".format(target))

    def _stop_running_fill(self, current):
        """Off while the valve is open: lower the stop level below the present level until the valve closes."""
        stop, level = current["autofill_stop"], current["ln2_level"]
        lowered = math.floor((level - 0.5) * 10) / 10
        if lowered <= 0.1 or lowered >= stop:
            raise ValueError("fill start is 0 % but the valve is still open; close it at the instrument")
        self._send(["CONF:FILL:A {:.1f}".format(lowered)])
        try:
            self._read_back(lambda c: not c["valve_open"], "the valve closed", seconds=15.0)
        finally:
            self._send(["CONF:FILL:A {:.1f}".format(stop)])
        check = self._read_back(lambda c: math.isclose(c["autofill_stop"], stop, abs_tol=0.05), "the fill stop back")
        if check["valve_open"]:
            self._send(["CONF:FILL:A {:.1f}".format(lowered)])
            raise ValueError("the valve reopened; fill stop left at {:g} % to keep it closed".format(lowered))

    def supervise(self, reading):
        """Runs on every reading: finishes a Fill, and notices changes made at the instrument."""
        state = self.mode_state
        mode = state.get("mode")
        if mode is None or reading.get("autofill_start") is None:
            return ""
        start = reading["autofill_start"]
        if mode == "off":
            if start != 0:
                self._save_mode({})
                return "MODE: fill start changed at the instrument ({:g} %); now Auto".format(start)
            return ""
        # mode == "fill"
        if not math.isclose(start, state["raised_start"], abs_tol=0.05):
            self._save_mode({})
            return "MODE: fill start changed at the instrument ({:g} %); Fill abandoned".format(start)
        if reading["valve_open"] and not state.get("valve_seen_open"):
            state["valve_seen_open"] = True
            self._save_mode(state)
            return "MODE: Fill under way (valve open)"
        reason = None
        if state.get("valve_seen_open") and not reading["valve_open"]:
            reason = "Fill finished at {:.1f} %".format(reading["ln2_level"] or float("nan"))
        elif not state.get("valve_seen_open") and time.time() - state["since"] > AMI_FILL_START_WAIT_S:
            reason = "Fill: the valve did not open within {} s".format(AMI_FILL_START_WAIT_S)
        elif reading["autofill_mode"] in AMI_FILL_MODES:
            reason = "Fill: the instrument was switched to {}".format(AMI_FILL_MODES[reading["autofill_mode"]])
        elif reading["autofill_state"] == 2 or reading["timeout_alarm"]:
            reason = "Fill stopped by the instrument's FILL TIMEOUT"
        if reason is None:
            return ""
        back_to_off = state.get("return_to") == "off" or not state.get("saved_start")
        target = 0.0 if back_to_off else state["saved_start"]
        try:          # idempotent (sets a level), so it is simply tried again at the next reading if it fails
            self._send(["CONF:FILL:B {:.1f}".format(target)])
            self._read_back(lambda c: math.isclose(c["autofill_start"], target, abs_tol=0.05), "the fill start restored")
        except Exception as error:
            message = "{}; restoring the fill start to {:g} % failed ({}); trying again".format(reason, target, error)
            self.out_queue.put(("notice", {"error": True, "message": message}))
            return "MODE: " + message
        self._save_mode({"mode": "off", "saved_start": state.get("saved_start"), "since": time.time()}
                        if back_to_off else {})
        message = "{}; fill start back to {:g} % ({})".format(reason, target, "Off" if back_to_off else "Auto")
        self.out_queue.put(("notice", {"error": "TIMEOUT" in reason or "did not" in reason, "message": message,
                                       "mode_done": True}))
        print("AMI 1700: " + message, file=sys.stderr)
        return "MODE: " + message

    def apply(self, request):
        self.write_attempted = False
        self.controls.check(request)
        if self.mode_state.get("mode"):
            raise ValueError("switch the Mode to Auto before changing the fill levels")
        current = read_ami(self.cfg)
        if current["unit_code"] != 0:
            raise ValueError("the instrument is not set to percent units")
        if current["fill_channel"] != 1:
            raise ValueError("autofill is not assigned to the nitrogen channel")
        old_start, old_stop = current["autofill_start"], current["autofill_stop"]
        base_start, base_stop = request["baseline"]
        if not (math.isclose(old_start, base_start, abs_tol=0.005) and math.isclose(old_stop, base_stop, abs_tol=0.005)):
            raise ValueError("fill levels changed at the instrument; switch Control off/on to reload")
        start, stop = request["values"]
        # Keep start < stop after every single command
        steps = [("CONF:FILL:A {:.1f}".format(stop), not math.isclose(stop, old_stop, abs_tol=0.005)),
                 ("CONF:FILL:B {:.1f}".format(start), not math.isclose(start, old_start, abs_tol=0.005))]
        if stop < old_stop:
            steps.reverse()
        commands = [command for command, needed in steps if needed]
        if not commands:
            return "No changes to apply"
        session = AmiScpi(self.cfg["ip"], self.cfg["scpi_port"])
        try:
            for command in commands:
                self.controls.check(request)
                self.write_attempted = True
                session.command(command)
        finally:
            session.close()
        deadline = time.monotonic() + 8.0
        while True:            # read back; never repeat the commands
            time.sleep(1.0)
            check = read_ami(self.cfg)
            if (math.isclose(check["autofill_start"], start, abs_tol=0.05)
                    and math.isclose(check["autofill_stop"], stop, abs_tol=0.05)):
                return "Applied and read back: fill start {:g} %, stop {:g} %".format(start, stop)
            if time.monotonic() >= deadline:
                raise ValueError("read-back shows start {:g} %, stop {:g} % (requested {:g}, {:g})".format(
                    check["autofill_start"], check["autofill_stop"], start, stop))

    def run(self):
        next_poll = time.monotonic()
        try:
            while not self.stop_event.is_set():
                event = ""
                while not self.controls.requests.empty():
                    request = self.controls.requests.get_nowait()
                    is_mode = request.get("kind") == "mode"
                    try:
                        message, error = (self.set_mode(request) if is_mode else self.apply(request)), False
                    except Exception as exc:
                        outcome = "Change sent; read-back not confirmed" if self.write_attempted else "No change sent"
                        message, error = "{}: {}. Check the instrument before retrying.".format(outcome, exc), True
                    print("AMI 1700: " + message, file=sys.stderr)
                    event = ("MODE {}: {}".format(request["mode"], message) if is_mode else
                             "SET fill {} -> {}: {}".format(request["baseline"], request["values"], message))
                    self.out_queue.put(("notice", {"error": error, "message": message}))
                    next_poll = 0      # read back the result now
                self.controls.pending.clear()
                if time.monotonic() >= next_poll or self.wake.is_set():
                    self.wake.clear()
                    self.poll(event)
                    every = AMI_FILL_POLL_S if self.mode_state.get("mode") == "fill" else self.cfg["poll_seconds"]
                    next_poll = time.monotonic() + min(every, self.cfg["poll_seconds"])
                self.wake.wait(max(0.05, min(1.0, next_poll - time.monotonic())))
        finally:
            self.log.close()


# ==========================================================================
# Log housekeeping: gzip closed CSV files after COMPRESS_AFTER_DAYS, delete
# CSV files (plain or gzipped) older than DELETE_AFTER_DAYS. Age is the time
# of the file's last write. Only files that match the monitor's own log-name
# patterns, inside its own log folders, are ever touched.
# ==========================================================================

LOG_FILE_PATTERNS = (
    (MAS_LOG_SUBDIR + "/*", re.compile(r"^[A-Za-z0-9_.-]+_\d{4}-\d\d-\d\d_\d{6}\.csv(\.gz)?$")),
    (LS_LOG_SUBDIR, re.compile(r"^lakeshore336_\d{8}T\d{6}_\d{6}Z(_fast)?\.csv(\.gz)?$")),
    (AMI_LOG_SUBDIR, re.compile(r"^ami1700_\d{4}-\d\d-\d\d_\d{6}\.csv(\.gz)?$")),
)


def log_files(base_dir):
    base = Path(base_dir)
    for folder_glob, pattern in LOG_FILE_PATTERNS:
        for folder in base.glob(folder_glob):
            if not folder.is_dir() or folder.is_symlink():
                continue
            for path in folder.iterdir():
                if pattern.match(path.name) and path.is_file() and not path.is_symlink():
                    yield path


def gzip_file(path):
    """Compress path to path.gz, verify the copy byte for byte (CRC and length), keep its time stamp, remove path."""
    target = path.with_name(path.name + ".gz")
    partial = path.with_name(path.name + ".gz.part")
    if target.exists():
        return 0
    stat = path.stat()
    crc, size = 0, 0
    with open(str(path), "rb") as source, gzip.open(str(partial), "wb", compresslevel=6) as sink:
        for block in iter(lambda: source.read(1 << 20), b""):
            crc, size = zlib.crc32(block, crc), size + len(block)
            sink.write(block)
    check_crc, check_size = 0, 0
    with gzip.open(str(partial), "rb") as check:
        for block in iter(lambda: check.read(1 << 20), b""):
            check_crc, check_size = zlib.crc32(block, check_crc), check_size + len(block)
    if (check_crc, check_size) != (crc, size) or path.stat().st_mtime != stat.st_mtime:
        partial.unlink()           # changed while compressing, or a bad copy: leave the original alone
        raise OSError("verification failed for {}".format(path))
    os.utime(str(partial), (stat.st_atime, stat.st_mtime))
    os.replace(str(partial), str(target))
    path.unlink()
    return stat.st_size - target.stat().st_size


def housekeeping(base_dir, now=None):
    """One pass. Returns a dict of counts (and prints problems; never raises)."""
    now = time.time() if now is None else now
    summary = {"compressed": 0, "deleted": 0, "freed_bytes": 0, "errors": 0}
    for leftover in Path(base_dir).glob("*/**/*.gz.part"):    # interrupted earlier runs
        try:
            if now - leftover.stat().st_mtime > 86400:
                leftover.unlink()
        except OSError:
            pass
    for path in sorted(log_files(base_dir)):
        try:
            age_days = (now - path.stat().st_mtime) / 86400
            if age_days > DELETE_AFTER_DAYS:
                size = path.stat().st_size
                path.unlink()
                summary["deleted"] += 1
                summary["freed_bytes"] += size
            elif path.suffix == ".csv" and age_days > COMPRESS_AFTER_DAYS:
                summary["freed_bytes"] += gzip_file(path)
                summary["compressed"] += 1
        except OSError as error:
            summary["errors"] += 1
            print("Housekeeping: {}: {}".format(path, error), file=sys.stderr)
    return summary


class Housekeeper(threading.Thread):
    """Runs housekeeping() HOUSEKEEPING_FIRST_S after start-up and then every HOUSEKEEPING_EVERY_S."""

    def __init__(self, base_dir):
        super().__init__(daemon=True)
        self.base_dir = base_dir
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        delay = HOUSEKEEPING_FIRST_S
        while not self.stop_event.wait(delay):
            delay = HOUSEKEEPING_EVERY_S
            started = time.time()
            summary = housekeeping(self.base_dir)
            line = "{} housekeeping: {} compressed, {} deleted (older than {} days), {:.1f} MB freed, {} errors, {:.1f} s".format(
                datetime.now().isoformat(timespec="seconds"), summary["compressed"], summary["deleted"],
                DELETE_AFTER_DAYS, summary["freed_bytes"] / 1e6, summary["errors"], time.time() - started)
            print(line, file=sys.stderr)
            if summary["compressed"] or summary["deleted"] or summary["errors"]:
                try:
                    with open(str(Path(self.base_dir) / "housekeeping.log"), "a") as handle:
                        handle.write(line + "\n")
                except OSError:
                    pass


# ==========================================================================
# Tk widgets
# ==========================================================================

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


CHECKBOX_IMAGES = []


def paint_checkbox_images(empty, ticked, size=24):
    border = "#c9d4e2" if THEME["dark"] else INK
    for image, fill in ((empty, "#0f141a" if THEME["dark"] else "white"), (ticked, OK_GREEN)):
        image.put(border, to=(0, 0, size, size))
        image.put(fill, to=(2, 2, size - 2, size - 2))
    # Tick mark: two thick strokes
    for (x0, y0), (x1, y1) in (((5, 12), (10, 17)), ((10, 17), (19, 6))):
        steps = 40
        for k in range(steps + 1):
            x = round(x0 + (x1 - x0) * k / steps)
            y = round(y0 + (y1 - y0) * k / steps)
            ticked.put("white", to=(x - 1, y - 1, x + 2, y + 2))


def make_checkbox_images(master, size=24):
    """A clear square check box (empty / ticked), drawn as images so it looks the same everywhere."""
    empty = tk.PhotoImage(master=master, width=size, height=size)
    ticked = tk.PhotoImage(master=master, width=size, height=size)
    paint_checkbox_images(empty, ticked, size)
    CHECKBOX_IMAGES.append((empty, ticked, size))
    return empty, ticked


class Field:
    """A Tk entry with the small interface the Lake Shore control code expects."""

    def __init__(self, parent, width, on_activity, on_change=None, on_submit=None):
        self.value = tk.StringVar(master=parent)
        self.entry = tk.Entry(parent, textvariable=self.value, width=width, font=(UI_FONT, 12),
                              relief="solid", borderwidth=1, justify="right",
                              disabledbackground=DISABLED_BG, disabledforeground=MUTED)
        self.active = True
        if on_change is not None:
            self.value.trace_add("write", lambda *a: on_change(self.text))
        self.entry.bind("<KeyPress>", lambda event: on_activity())
        self.entry.bind("<Button-1>", lambda event: on_activity())
        self.entry.bind("<Control-a>", self._select_all)
        if on_submit is not None:
            self.entry.bind("<Return>", lambda event: on_submit(self.text))

    @property
    def text(self):
        return self.value.get()

    def _select_all(self, event):
        self.entry.select_range(0, "end")
        self.entry.icursor("end")
        return "break"

    def set_val(self, value):
        value = str(value)
        if self.text != value:
            self.value.set(value)

    def set_active(self, active):
        if self.active != active:
            self.active = active
            self.entry.configure(state="normal" if active else "disabled",
                                 background="white" if active else DISABLED_BG)

    def set_changed(self, changed):
        """Amber background while the field holds an edit that has not been applied."""
        if self.active:
            background = PENDING_BG if changed else "white"
            if self.entry.cget("background") != background:
                self.entry.configure(background=background)


# ==========================================================================
# Plot area with toolbar and "Follow live"
# ==========================================================================

class PlotCanvas:
    """
    A matplotlib figure in a Tk frame, with the zoom/pan toolbar and a
    "Follow live" switch. Turning it off (or zooming/panning with the toolbar)
    freezes the axis limits; it switches itself back on FOLLOW_RESUME_S after
    the last such action.
    """

    def __init__(self, app, parent, nrows, ncols, margins, width_ratios=None, figsize=(8, 3)):
        self.app = app
        self.nrows, self.ncols = nrows, ncols
        self.margins = margins          # pixels: left, right, top, bottom, gap_x, gap_y
        self.frame = tk.Frame(parent, bg="white")
        self.figure = Figure(figsize=figsize, dpi=100, facecolor="white")
        self.grid = GridSpec(nrows, ncols, figure=self.figure, width_ratios=width_ratios)
        self.axes = [self.figure.add_subplot(self.grid[r, c]) for r in range(nrows) for c in range(ncols)]
        for ax in self.axes:
            ax.grid(True, alpha=0.3)
            ax.tick_params(labelsize=8)
            locator = mdates.AutoDateLocator(minticks=3, maxticks=6, tz=LOCAL_TZ)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(
                locator, tz=LOCAL_TZ, zero_formats=["", "%Y", "%b", "%d %b", "%H:%M", "%H:%M"],
                offset_formats=["", "%Y", "%b %Y", "%d %b %Y", "%d %b %Y", "%d %b %Y"]))
            ax.xaxis.get_offset_text().set_x(0.5)          # date centred under the plot,
            ax.xaxis.get_offset_text().set_horizontalalignment("center")   # not under the last tick
            ax.ticklabel_format(axis="y", useOffset=False, style="plain")
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.frame)

        bar = tk.Frame(self.frame, bg=PANEL_BG)
        bar.pack(side="bottom", fill="x")
        self.bar = bar
        self.trace_vars = OrderedDict()
        self.traces_back_at = None
        # Pack the right-hand items first so the toolbar's coordinate readout cannot squeeze them
        self.follow = tk.BooleanVar(master=self.frame, value=True)
        tk.Checkbutton(bar, text="Follow live", variable=self.follow, command=self._follow_clicked,
                       bg=PANEL_BG, font=(UI_FONT, 10, "bold")).pack(side="right", padx=(4, 8))
        self.resume_label = tk.Label(bar, text="", fg=ERROR_RED, bg=PANEL_BG, font=(UI_FONT, 9))
        self.resume_label.pack(side="right")
        self.resume_at = None
        try:
            self.toolbar = NavigationToolbar2Tk(self.canvas, bar, pack_toolbar=False)
        except TypeError:  # matplotlib < 3.3
            self.toolbar = NavigationToolbar2Tk(self.canvas, bar)
        self.toolbar.update()
        self.toolbar.pack(side="left", fill="x", expand=True)

        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self.canvas.mpl_connect("resize_event", self._apply_margins)
        self.canvas.mpl_connect("button_press_event", self._pressed)
        self._apply_margins()

    @property
    def follow_live(self):
        return bool(self.follow.get())

    def pause(self):
        self.follow.set(False)
        self.resume_at = time.monotonic() + FOLLOW_RESUME_S

    def _follow_clicked(self):
        if self.follow.get():
            self.resume_at = None
            self.resume_label.configure(text="")
            self.app.request_redraw()
        else:
            self.pause()

    def _pressed(self, event):
        mode = getattr(self.toolbar, "mode", "")
        if getattr(mode, "value", mode):      # zoom or pan tool active
            self.pause()

    def add_trace_toggles(self, items):
        """Checkboxes on the toolbar row that hide traces; after TRACE_HIDE_S they all come back by themselves."""
        box = tk.Frame(self.bar, bg=PANEL_BG)
        box.pack(side="right", padx=(0, 8), before=self.toolbar)
        self.trace_label = tk.Label(box, text="Show:", width=13, anchor="e", fg=MUTED, bg=PANEL_BG, font=(UI_FONT, 9))
        self.trace_label.pack(side="left", padx=(0, 2))
        for key, text, color in items:
            var = tk.BooleanVar(master=box, value=True)
            tk.Checkbutton(box, text=text, variable=var, command=self._traces_changed, fg=color, activeforeground=color,
                           bg=PANEL_BG, activebackground=PANEL_BG, font=(UI_FONT, 9, "bold"), padx=0, pady=0,
                           highlightthickness=0, cursor="hand2").pack(side="left")
            self.trace_vars[key] = var

    def trace_shown(self, key):
        var = self.trace_vars.get(key)
        return True if var is None else bool(var.get())

    def _traces_changed(self):
        hidden = any(not var.get() for var in self.trace_vars.values())
        self.traces_back_at = time.monotonic() + TRACE_HIDE_S if hidden else None
        if not hidden:
            self.trace_label.configure(text="Show:", fg=MUTED)
        self.app.request_redraw()

    def tick(self):
        if self.traces_back_at is not None:
            left = self.traces_back_at - time.monotonic()
            if left <= 0:
                self.traces_back_at = None
                for var in self.trace_vars.values():
                    var.set(True)
                self.trace_label.configure(text="Show:", fg=MUTED)
                self.app.request_redraw()
            else:
                self.trace_label.configure(text="back in {} s".format(int(math.ceil(left))), fg=ERROR_RED)
        if self.resume_at is None:
            return
        remaining = self.resume_at - time.monotonic()
        if remaining <= 0:
            self.resume_at = None
            self.follow.set(True)
            self.resume_label.configure(text="")
            self.app.request_redraw()
        else:
            self.resume_label.configure(text="Live view resumes in {} s".format(int(math.ceil(remaining))))

    def _apply_margins(self, event=None):
        width, height = self.figure.get_size_inches() * self.figure.dpi
        left, right, top, bottom, gap_x, gap_y = self.margins
        axes_width = (width - left - right - gap_x * (self.ncols - 1)) / self.ncols
        axes_height = (height - top - bottom - gap_y * (self.nrows - 1)) / self.nrows
        if axes_width < 50 or axes_height < 40:
            return
        self.figure.subplots_adjust(left=left / width, right=1 - right / width,
                                    top=1 - top / height, bottom=bottom / height,
                                    wspace=gap_x / axes_width, hspace=gap_y / axes_height)
        # The y label of the left-hand plots sits at a fixed distance from the window edge, so wide
        # tick labels (spin rates of 100000 Hz) cannot push it out of the window.
        for index, ax in enumerate(self.axes):
            if index % self.ncols == 0:
                ax_width = ax.get_position().width * width       # in pixels (the columns may differ in width)
                ax.yaxis.set_label_coords(-(ax.get_position().x0 * width - YLABEL_EDGE_PX) / ax_width, 0.5)


# ==========================================================================
# MAS panel (one per controller)
# ==========================================================================

class MasPanel:

    def __init__(self, app, parent, name, cfg):
        self.app = app
        self.name = name
        self.cfg = cfg
        self.color = cfg["color"]
        self.folder = Path(app.args.base_dir) / MAS_LOG_SUBDIR / name
        self.queue = queue.Queue()
        self.data = deque()
        self.latest = None
        self.last_valid_epoch = None
        self.log_error = ""

        self.frame = tk.Frame(parent, relief="groove", borderwidth=2, bg=PANEL_BG)

        # Every label has a fixed size (characters/lines) so nothing moves when values change.
        # Labels whose text can grow get width=1 and stretch to the panel width (long text is clipped).
        banner = tk.Frame(self.frame, bg=self.color, padx=10, pady=4)
        banner.pack(fill="x")
        tk.Label(banner, text="MAS:  " + name, font=(UI_FONT, 15, "bold"), fg="white",
                 bg=self.color).pack(side="left")
        self.banner_detail = tk.Label(banner, font=(UI_FONT, 9), fg="white", bg=self.color, anchor="e", width=1,
                                      text="IP {}    log folder: {}".format(cfg["ip"], self.folder))
        self.banner_detail.pack(side="right", fill="x", expand=True, padx=(12, 0))

        readout = tk.Frame(self.frame, padx=8, pady=4, bg=PANEL_BG)
        readout.pack(fill="x")

        # The frame's highlight ring turns red on a controller fault (always 3 px, so nothing moves)
        box = tk.Frame(readout, relief="groove", borderwidth=2, padx=8, bg="white",
                       highlightthickness=3, highlightbackground="white", highlightcolor="white")
        box.pack(side="left", fill="y")
        self.spin_box = box
        tk.Label(box, text="Spin rate", font=(UI_FONT, 11), bg="white").pack(anchor="e")
        self.spin_label = tk.Label(box, text="---", width=10, anchor="e", bg="white", fg=self.color,
                                   font=(UI_FONT, 33, "bold"))
        self.spin_label.pack()
        self.fault_label = tk.Label(box, text="", anchor="e", bg="white", fg=ERROR_RED,
                                    font=(UI_FONT, 11, "bold"), width=1)
        self.fault_label.pack(fill="x")

        pressures = tk.Frame(readout, relief="groove", borderwidth=2, padx=8, bg="white")
        pressures.pack(side="left", fill="y", padx=(6, 0))
        self.pressure_labels = {}
        layout = ((0, "bearing_mbar", "Bearing (mbar)", (UI_FONT, 10), (UI_FONT, 22, "bold"), 6),
                  (1, "drive_mbar", "Drive (mbar)", (UI_FONT, 10), (UI_FONT, 22, "bold"), 6),
                  (0, "bearing_sense_mbar", "Bearing sense (mbar)", (UI_FONT, 9), (UI_FONT, 12, "bold"), 6),
                  (1, "frame_cooling", "Frame cooling (mbar)", (UI_FONT, 9), (UI_FONT, 12, "bold"), 14))
        for index, (column, key, title, title_font, value_font, width) in enumerate(layout):
            row = 2 * (index // 2)
            pad = (0, 0) if column == 0 else (16, 0)
            tk.Label(pressures, text=title, font=title_font, fg=INK if row == 0 else MUTED, bg="white",
                     anchor="e").grid(row=row, column=column, sticky="ew", padx=pad, pady=(2 if row else 0, 0))
            value = tk.Label(pressures, text="---", width=width, anchor="e", bg="white", fg=INK, font=value_font)
            value.grid(row=row + 1, column=column, sticky="ew", padx=pad)
            self.pressure_labels[key] = value
        for column in (0, 1):
            pressures.columnconfigure(column, uniform="pressure", minsize=120)

        stats = tk.Frame(readout, padx=8, bg=PANEL_BG)
        stats.pack(side="left", fill="y")
        tk.Label(stats, text="Spin-rate RMSD", font=(UI_FONT, 10), bg=PANEL_BG).grid(row=0, column=0, columnspan=2, sticky="w")
        self.rmsd_labels = []
        for row, window in enumerate(RMSD_WINDOWS_S, start=1):
            title = "{} s".format(window) if window < 60 else "{:g} min".format(window / 60)
            tk.Label(stats, text=title, font=(UI_FONT, 11), bg=PANEL_BG, width=5, anchor="w").grid(
                row=2 * row - 1, column=0, sticky="w")
            value = tk.Label(stats, text="---", width=8, anchor="e", font=(UI_FONT, 14, "bold"), bg=PANEL_BG)
            value.grid(row=2 * row - 1, column=1, sticky="e")
            detail = tk.Label(stats, text="", font=(UI_FONT, 8), fg=MUTED, bg=PANEL_BG, width=27, anchor="e")
            detail.grid(row=2 * row, column=0, columnspan=2, sticky="e")
            self.rmsd_labels.append((window, value, detail))

        self.status_label = tk.Label(self.frame, text="Waiting for the first reading ...", anchor="w",
                                     font=(UI_FONT, 10), padx=8, bg=PANEL_BG, width=1)
        self.status_label.pack(fill="x")

        self.plot = PlotCanvas(app, self.frame, 1, 2, margins=(80, 26, 22, 38, 68, 0),
                               width_ratios=[2, 1], figsize=(8, 2.6))
        self.plot.frame.pack(fill="both", expand=True)
        self.ax_long, self.ax_short = self.plot.axes
        self.line_long, = self.ax_long.plot([], [], color=self.color, linewidth=1)
        self.line_short, = self.ax_short.plot([], [], color=self.color, linewidth=1)
        self.ax_long.set_title("Spin rate, past 24 h", fontsize=10, fontweight="bold", color=self.color, loc="left")
        self.ax_short.set_title("Past 30 min", fontsize=10, fontweight="bold", color=self.color, loc="left")
        self.ax_long.set_ylabel("Spin rate (Hz)", fontsize=9)

        history, foreign = load_mas_history(self.folder, name, time.time() - LONG_SPAN_S)
        if history:
            times = to_plot_times([t for t, _ in history])
            previous = None
            for (epoch, spin), plot_time in zip(history, times):
                if previous is not None and epoch - previous > MAS_GAP_S:
                    self.data.append((previous + 0.001, to_plot_time(previous + 0.001), NAN))
                self.data.append((epoch, plot_time, spin))
                previous = epoch
            # Break the line between the saved history and this run
            self.data.append((previous + 0.001, to_plot_time(previous + 0.001), NAN))
        n_valid = sum(1 for _, s in history if not math.isnan(s))
        self.history_note = ("24 h history at start-up: {} readings".format(n_valid) if n_valid
                             else "no 24 h history at start-up")
        if foreign:
            self.history_note += " (WARNING: skipped {} rows of another controller)".format(foreign)
        self.banner_detail.configure(text="IP {}    {}".format(cfg["ip"], self.history_note))

        self.poller = MasPoller(name, cfg, self.folder, self.queue)
        self.poller.start()
        print("MAS: logging {} ({}) into {}{}".format(
            name, cfg["host"], self.folder, "" if cfg["read_pressures"] else " (pressures off)"), file=sys.stderr)

    def stop(self):
        self.poller.stop()

    # ---- periodic -------------------------------------------------------------

    def tick(self):
        got_new = False
        while True:
            try:
                kind, _, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "reading":
                self._add(payload)
                got_new = True
            elif kind == "file":
                self.log_error = ""
                self.banner_detail.configure(text="IP {}    log: {}    {}".format(
                    self.cfg["ip"], Path(payload).name, self.history_note))
            elif kind == "log_error":
                self.log_error = payload
        self._update_readout()
        return got_new

    def _add(self, reading):
        spin = reading["spin_hz"] if reading["spin_hz"] is not None else NAN
        epoch = reading["epoch"]
        self.data.append((epoch, to_plot_time(epoch), spin))
        while self.data and self.data[0][0] < epoch - LONG_SPAN_S:
            self.data.popleft()
        if reading["error"] and (self.latest is None or not self.latest["error"]):
            print("MAS {} {}: {}".format(self.name, datetime.fromtimestamp(epoch).isoformat(timespec="seconds"),
                                         reading["error"]), file=sys.stderr)
        self.latest = reading
        if not reading["error"]:
            self.last_valid_epoch = epoch

    def _update_readout(self):
        now = time.time()
        latest = self.latest
        fresh = self.last_valid_epoch is not None and now - self.last_valid_epoch <= MAS_STALE_AFTER_S
        fault = ""
        if fresh and latest is not None and not latest["error"]:
            # Only the controller's own error message counts as a fault. The Manual Rotation
            # "Rotation state" reads Error/Pending during normal manual-mode spinning, so it is ignored.
            if latest.get("status_error"):
                fault = latest["status"] or "controller error"
            self.spin_label.configure(text="{:,.0f} Hz".format(latest["spin_hz"]),
                                      fg="#9aa5b1" if fault else self.color)
        elif latest is None:
            self.spin_label.configure(text="---", fg="#888888")
        else:
            self.spin_label.configure(text="NO DATA", fg="#888888")
            fault = "not reachable"
        if self.fault_label.cget("text") != fault:
            self.fault_label.configure(text=fault)
            self.spin_box.configure(highlightbackground=ERROR_RED if fault else "white",
                                    highlightcolor=ERROR_RED if fault else "white")

        current = latest if (fresh and latest is not None) else {}
        for key in ("bearing_mbar", "drive_mbar", "bearing_sense_mbar"):
            value = current.get(key)
            self.pressure_labels[key].configure(text="---" if value is None else "{:.0f}".format(value))
        frame_state, frame_set = current.get("frame_cooling"), current.get("frame_cooling_set_mbar")
        if frame_state:
            frame = frame_state + ("" if frame_set is None else " \u00b7 set {:.0f}".format(frame_set))
        else:
            frame = "---"
        self.pressure_labels["frame_cooling"].configure(text=frame)
        pressure_error = (latest or {}).get("pressure_error", "") if fresh else ""

        for window, value_label, detail_label in self.rmsd_labels:
            rmsd, n, mean = rmsd_about_mean(self.data, now, window)
            if rmsd is None:
                value_label.configure(text="---")
                detail_label.configure(text="n = {} (need {})".format(n, RMSD_MIN_POINTS))
            else:
                value_label.configure(text="{:.1f} Hz".format(rmsd))
                detail_label.configure(text="n = {},  mean {:,.1f} Hz".format(n, mean))

        if self.log_error:
            self.status_label.configure(text="MAS LOG FILE WRITE FAILED: " + self.log_error, fg=ERROR_RED)
            return
        if latest is None:
            return
        stamp = datetime.fromtimestamp(latest["epoch"]).strftime("%H:%M:%S")
        if latest["error"]:
            self.status_label.configure(fg=ERROR_RED, text="{}  Controller not reachable: {}".format(
                stamp, latest["error"][:110]))
            return
        if pressure_error:
            self.status_label.configure(fg=ERROR_RED, text="{}  Pressures unavailable: {}".format(
                stamp, pressure_error[:110]))
            return
        parts = ["{}  {}".format(stamp, latest["status"] or "(no status text)")]
        if latest["signal_pct"] is not None:
            note = " - " + latest["signal_note"] if latest["signal_note"] else ""
            parts.append("Signal {:g}%{}".format(latest["signal_pct"], note))
        if latest["gain"] is not None:
            parts.append("Gain {}".format(latest["gain"]))
        self.status_label.configure(fg="black", text="   |   ".join(parts))

    def update_plots(self, long, short, now):
        follow = self.plot.follow_live
        for do, ax, line, span, max_points in ((long, self.ax_long, self.line_long, LONG_SPAN_S, LONG_MAX_POINTS),
                                               (short, self.ax_short, self.line_short, SHORT_SPAN_S, None)):
            if not do:
                continue
            epochs, xs, ys = recent_columns(self.data, now - span, 3)
            keep, left, right = visible_limits(epochs, now, span)
            x, y = xs[keep], ys[keep]
            if max_points:
                x, y = envelope(x, y, max_points)
            line.set_data(x, y)
            if follow:
                ax.set_xlim(left, right)
                set_y_limits(ax, y, 2.0, floor=0.0)


# ==========================================================================
# AMI 1700 panel (readout box beside the Lake Shore temperatures, and a
# small control row for the autofill start/stop levels)
# ==========================================================================

AMI_COLOR = "#0f7f8c"


class AmiPanel:

    def __init__(self, app, readouts, column, control_parent):
        self.app = app
        self.cfg = app.args.ami
        self.controls = ControlState()
        self.queue = queue.Queue()
        self.latest = None
        self.baseline = None
        self.awaiting = False
        self.refill = True
        self.syncing = False
        self._editable = None
        self._can_apply = None
        self.mode_awaiting = None
        self._mode_styles = {}
        self.stale_after = 2.5 * self.cfg["poll_seconds"]

        # Readout box (same row as the bearing and drive temperatures)
        box = tk.Frame(readouts, relief="groove", borderwidth=2, padx=8, pady=1, bg="white")
        box.grid(row=0, column=column, sticky="nsew", padx=(10, 0))
        tk.Label(box, text="LN2 level, every {:g} s".format(self.cfg["poll_seconds"]),
                 font=(UI_FONT, 11), bg="white").pack(anchor="e")
        self.big = tk.Label(box, text="---", anchor="e", font=(UI_FONT, 24, "bold"), fg=AMI_COLOR, bg="white", width=8)
        self.big.pack(fill="x")
        self.lines = []
        for _ in range(3):
            label = tk.Label(box, text="", anchor="e", font=(UI_FONT, 9), fg=MUTED, bg="white", width=1)
            label.pack(fill="x")
            self.lines.append(label)

        # Control row
        frame = tk.LabelFrame(control_parent, text=" LN2 autofill (AMI 1700, {}) ".format(self.cfg["ip"]),
                              font=(UI_FONT, 10, "bold"), fg=INK, bg=PANEL_BG, padx=8, pady=0)
        frame.pack(fill="x", padx=10, pady=(0, 4))
        row = tk.Frame(frame, bg=PANEL_BG)
        row.pack(fill="x")
        self.box_images = make_checkbox_images(frame)
        self.control_var = tk.BooleanVar(master=frame, value=False)
        self.control_toggle = tk.Checkbutton(
            row, text="  Control", variable=self.control_var, command=self.toggle_control,
            image=self.box_images[0], selectimage=self.box_images[1], compound="left", indicatoron=False,
            font=(UI_FONT, 12, "bold"), fg=INK, bg=PANEL_BG, activebackground=PANEL_BG, activeforeground=INK,
            selectcolor=PANEL_BG, relief="flat", offrelief="flat", overrelief="flat", borderwidth=0,
            highlightthickness=0, cursor="hand2")
        self.control_toggle.pack(side="left")
        self.lock_label = tk.Label(row, text="Locked", font=(UI_FONT, 10), fg=MUTED, bg=PANEL_BG, width=12, anchor="w")
        self.lock_label.pack(side="left", padx=(8, 0))
        self.fields = {}
        for key, title in (("start", "Fill start (%)"), ("stop", "Fill stop (%)")):
            tk.Label(row, text=title, font=(UI_FONT, 10), fg=MUTED, bg=PANEL_BG).pack(side="left", padx=(10, 4))
            field = Field(row, 6, on_activity=self.field_activity, on_change=lambda text: self.field_activity())
            field.set_active(False)
            field.entry.pack(side="left")
            self.fields[key] = field
        self.apply_button = tk.Button(row, text="Apply", font=(UI_FONT, 11, "bold"), width=6, state="disabled",
                                      bg=DISABLED_BG, command=self.apply)
        self.apply_button.pack(side="left", padx=(12, 0))
        tk.Label(row, text="Mode", font=(UI_FONT, 10), fg=MUTED, bg=PANEL_BG).pack(side="left", padx=(18, 4))
        segment = tk.Frame(row, bg=PANEL_BG)
        segment.pack(side="left")
        self.mode_var = tk.StringVar(master=frame, value="")
        self.mode_buttons = []
        for key, text in AMI_MODES:
            radio = tk.Radiobutton(segment, text=text, variable=self.mode_var, value=key, indicatoron=False, width=4,
                                   font=(UI_FONT, 10, "bold"), fg=ERROR_RED if key == "off" else INK,
                                   selectcolor=LOCKED_SELECTED, bg=DISABLED_BG, state="disabled",
                                   highlightthickness=2, highlightbackground=PANEL_BG, highlightcolor=INK,
                                   command=self.mode_clicked, cursor="hand2")
            radio.pack(side="left", padx=1)
            self.mode_buttons.append((key, radio))
        self.note = tk.Label(frame, text="Control off · values update every {:g} s · locks after {} s without edits".format(
            self.cfg["poll_seconds"], CONTROL_IDLE_SECONDS), anchor="w", font=(UI_FONT, 9), fg=MUTED, bg=PANEL_BG, width=1)
        self.note.pack(fill="x")

        self.poller = AmiPoller(self.cfg, Path(app.args.base_dir) / AMI_LOG_SUBDIR, self.queue, self.controls)
        self.poller.start()
        print("AMI 1700: logging {} every {:g} s into {}".format(
            self.cfg["ip"], self.cfg["poll_seconds"], Path(app.args.base_dir) / AMI_LOG_SUBDIR), file=sys.stderr)

    def stop(self):
        self.controls.set_enabled(False)
        self.poller.stop()

    # ---- periodic -------------------------------------------------------------------

    def tick(self):
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "reading":
                self.latest = payload
            elif kind == "notice":
                if payload.get("mode_done"):          # the end of a Fill, reported by the poller
                    self.message(payload["message"], payload["error"])
                    continue
                self.awaiting = False
                self.mode_awaiting = None
                self.refill = True
                self.message(payload["message"], payload["error"])
        self.expire()
        self.refresh_controls()
        self.update_readout()

    def fresh(self):
        latest = self.latest
        return latest is not None and not latest["error"] and time.time() - latest["epoch"] <= self.stale_after

    def update_readout(self):
        latest = self.latest
        if latest is None:
            self.big.configure(text="---", fg="#888888")
            texts = ("connecting to {}".format(self.cfg["ip"]), "", "")
            colors = (MUTED, MUTED, MUTED)
        elif not self.fresh():
            self.big.configure(text="NO DATA", fg="#888888")
            error = latest["error"]          # full text is in the CSV; show a short reason
            for pattern, short in (("timed out", "timed out"), ("refused", "connection refused"),
                                   ("No route", "no route to host"), ("unreachable", "network unreachable"),
                                   ("JSON", "unexpected reply"), ("Expecting", "unexpected reply")):
                if pattern in error:
                    error = short
                    break
            else:
                error = error[-32:] if error else "no reading for {:.0f} s".format(time.time() - latest["epoch"])
            texts = ("not reachable", error, "")
            colors = (ERROR_RED, ERROR_RED, MUTED)
        else:
            unit = "%" if latest["unit_code"] == 0 else ""
            shown = latest["ln2_level_display"]
            if shown in AMI_SENSOR_ERRORS:
                self.big.configure(text=shown, fg=ERROR_RED)
                level_text = AMI_SENSOR_ERRORS[shown]
            elif shown[:1] in "<>" and shown:
                self.big.configure(text="{} {}".format(shown, unit), fg=AMI_COLOR)
                level_text = "reading {:.1f} {}".format(latest["ln2_level"], unit)
            else:
                self.big.configure(text="{:.1f} {}".format(latest["ln2_level"], unit), fg=AMI_COLOR)
                level_text = ""
            fill = "fill {:g} to {:g} {}".format(latest["autofill_start"], latest["autofill_stop"], unit) \
                if latest["autofill_start"] is not None else "fill levels ?"
            mode, _why = self.shown_mode()
            saved = (latest.get("mode_state") or {}).get("saved_start")
            if mode == "off":
                fill = "autofill OFF" + (" (Auto: {:g} to {:g} {})".format(saved, latest["autofill_stop"], unit)
                                         if saved else "")
            elif mode == "fill":
                then_off = (latest.get("mode_state") or {}).get("return_to") == "off" or not saved
                fill = "FILL to {:g} {}, then {}".format(
                    latest["autofill_stop"], unit, "Off" if then_off else "Auto ({:g} {})".format(saved, unit))
            state = AMI_FILL_MODES.get(latest["autofill_mode"]) or AMI_FILL_STATES.get(latest["autofill_state"], "?")
            valve = "valve open" if latest["valve_open"] else "valve closed"
            alarms = []
            for n in (1, 2):
                if latest.get("alarm{}_active".format(n)):
                    sign = ">=" if latest.get("alarm{}_sense".format(n)) else "<="
                    alarms.append("ALARM level {} {:g} {}".format(sign, latest["alarm{}_setpoint".format(n)], unit))
            if latest["timeout_alarm"]:
                alarms.append("FILL TIMEOUT")
            stamp = datetime.fromtimestamp(latest["epoch"]).strftime("%H:%M:%S")
            texts = ("   ".join(t for t in (level_text, fill) if t), "{} · {}".format(state, valve),
                     " · ".join(alarms) if alarms else "updated " + stamp)
            colors = (MUTED, ERROR_RED if latest["autofill_state"] == 2 else MUTED, ERROR_RED if alarms else MUTED)
            if latest["unit_code"] != 0:
                texts = (texts[0], texts[1], "instrument not in % units; control off")
                colors = (MUTED, colors[1], ERROR_RED)
        for label, text, color in zip(self.lines, texts, colors):
            label.configure(text=text, fg=color)

    # ---- control ---------------------------------------------------------------------

    def message(self, text, error=False):
        self.note.configure(text=text, fg=ERROR_RED if error else MUTED)

    def field_activity(self):
        if not self.syncing:
            self.controls.touch()

    def toggle_control(self):
        enabled = bool(self.control_var.get())
        self.controls.set_enabled(enabled)
        self.refill = True
        if enabled:
            self.poller.wake.set()       # fresh values before editing
        self.refresh_controls()
        self.message("Control on · edit the fill levels and Apply, or click a Mode (acts at once)" if enabled
                     else "Control off · unapplied edits discarded")

    def expire(self):
        if self.controls.enabled and self.controls.remaining() <= 0:
            self.controls.set_enabled(False)
            self.control_var.set(False)
            self.refill = True
            self.message("Control locked after {} seconds without edits".format(CONTROL_IDLE_SECONDS))
        label = "Locks in {} s".format(math.ceil(self.controls.remaining())) if self.controls.enabled else "Locked"
        if self.lock_label.cget("text") != label:
            self.lock_label.configure(text=label)

    def shown_mode(self):
        """(mode key or None, reason when None) as it stands at the instrument and in the monitor's mode file."""
        latest = self.latest
        if not self.fresh():
            return None, "no fresh reading"
        if latest["autofill_mode"] in AMI_FILL_MODES:
            return None, "instrument in {}; Mode needs AUTOFILL on its front panel".format(
                AMI_FILL_MODES[latest["autofill_mode"]])
        if latest["autofill_start"] is None:
            return None, "fill levels not reported"
        state = latest.get("mode_state") or {}
        if state.get("mode") == "fill":
            return "fill", ""
        if state.get("mode") == "off" or latest["autofill_start"] == 0:
            return "off", ""
        return "auto", ""

    def mode_clicked(self):
        target = self.mode_var.get()
        mode, why = self.shown_mode()
        try:
            if not self.controls.enabled or self.awaiting or self.mode_awaiting:
                raise ValueError("Enable Control and wait for any pending change")
            if mode is None:
                raise ValueError(why)
            if target == mode:
                return
            self.controls.touch()
            self.controls.submit({"kind": "mode", "mode": target})
            self.mode_awaiting = target
            self.poller.wake.set()
            self.message("{}: sending and reading back ...".format(dict(AMI_MODES)[target]))
        except ValueError as exc:
            self.message(str(exc), error=True)
        self.refresh_controls()

    def style_mode_buttons(self, mode, editable):
        """Live mode: solid fill (grey while locked); a mode being sent: amber."""
        selected = self.mode_awaiting or mode
        if self.mode_var.get() != (selected or ""):
            self.mode_var.set(selected or "")
        for key, radio in self.mode_buttons:
            is_selected = key == selected
            fill = PENDING_DARK if self.mode_awaiting else (INK if editable else LOCKED_SELECTED)
            style = {
                "state": "normal" if editable else "disabled",
                "selectcolor": fill,
                "fg": "white" if is_selected else (ERROR_RED if key == "off" else INK),
                "activeforeground": "white" if is_selected else (ERROR_RED if key == "off" else INK),
                "disabledforeground": "#f2f4f7" if is_selected else "#a3adb8",
                "highlightbackground": INK if key == mode else PANEL_BG,
                "bg": "white" if editable else DISABLED_BG,
            }
            if self._mode_styles.get(radio) != style:
                self._mode_styles[radio] = style
                radio.configure(**style)

    def refresh_controls(self):
        latest = self.latest
        mode, _why = self.shown_mode()
        self.style_mode_buttons(mode, bool(mode and self.controls.enabled and not self.awaiting
                                           and not self.mode_awaiting))
        valid = (self.fresh() and latest["unit_code"] == 0 and latest["fill_channel"] == 1
                 and latest["autofill_start"] is not None and latest["autofill_stop"] is not None
                 and mode == "auto" and not self.mode_awaiting)    # fill levels are edited in Auto only
        if mode in ("off", "fill"):          # show the normal levels (the instrument's start is 0 or raised)
            saved = (latest.get("mode_state") or {}).get("saved_start")
            shown = ("{:g}".format(saved) if saved else "", "{:g}".format(latest["autofill_stop"]))
            if shown != getattr(self, "_shown_saved", None):
                self._shown_saved = shown
                self.syncing = True
                try:
                    self.fields["start"].set_val(shown[0])
                    self.fields["stop"].set_val(shown[1])
                finally:
                    self.syncing = False
                self.refill = True
        else:
            self._shown_saved = None
        if valid and (not self.controls.enabled or self.refill or self.baseline is None):
            self.baseline = (latest["autofill_start"], latest["autofill_stop"])
            self.syncing = True
            try:
                self.fields["start"].set_val("{:g}".format(self.baseline[0]))
                self.fields["stop"].set_val("{:g}".format(self.baseline[1]))
            finally:
                self.syncing = False
            self.refill = False
        editable = bool(valid and self.controls.enabled and not self.awaiting)
        if editable != self._editable:
            self._editable = editable
            for field in self.fields.values():
                field.set_active(editable)
        changed = False
        if editable and self.baseline is not None:
            for key, live in zip(("start", "stop"), self.baseline):
                field_changed = differs(self.fields[key].text, live)
                self.fields[key].set_changed(field_changed)
                changed = changed or field_changed
        can_apply = editable and changed
        if can_apply != self._can_apply:
            self._can_apply = can_apply
            self.apply_button.configure(state="normal" if can_apply else "disabled",
                                        bg="#dcecf8" if can_apply else DISABLED_BG)

    def apply(self):
        try:
            if not self.controls.enabled or self.awaiting:
                raise ValueError("Enable Control and wait for any pending Apply")
            if not self.fresh() or self.baseline is None:
                raise ValueError("Wait for a fresh reading from the instrument")
            values = validate_fill(self.fields["start"].text, self.fields["stop"].text)
            self.controls.submit({"values": values, "baseline": self.baseline})
            self.awaiting = True
            self.refresh_controls()
            self.poller.wake.set()
            self.message("Apply queued; sending and reading back ...")
        except (ValueError, KeyError) as exc:
            self.message(str(exc), error=True)


# ==========================================================================
# Lake Shore panel
# ==========================================================================

class LakeShorePanel:

    def __init__(self, app, parent):
        self.app = app
        args = app.args
        self.interval = SamplingInterval(args.interval)
        self.controls = ControlState()
        self.live_row = None
        self.live_received = 0.0
        self.drafts = {}
        self.requested_targets = {}
        self.control_fields = {}
        self.apply_buttons = {}
        self.pid_labels = {}
        self.range_vars = {}
        self.range_buttons = {}
        self._range_styles = {}
        self._apply_states = {}
        self._all_off_state = None
        self.awaiting = set()
        self.refill = set()
        self.refill_next = set()
        self.syncing_fields = False
        self._editable_states = {}
        self.data = deque()     # temperature_point tuples with plot time inserted at index 1
        self.log_path = ""
        self.updates = queue.Queue()
        self.stop_event = threading.Event()
        self.result = [0]

        self._build(parent)
        self.ami = AmiPanel(app, self.readouts_frame, 2, self.frame) if args.ami["enabled"] else None
        self.plot = PlotCanvas(app, self.frame, 2, 1, margins=(64, 58, 24, 40, 0, 70), figsize=(8, 5))
        self.plot.frame.pack(fill="both", expand=True)
        self._build_plots(*self.plot.axes)
        self.plot.add_trace_toggles([("A", "bearing", CHANNELS[0][2]), ("B", "drive", CHANNELS[1][2]),
                                     ("temp", "temp", INK), ("setpoint", "setpt", INK), ("heater", "heater", INK)])

        folder = Path(args.base_dir) / LS_LOG_SUBDIR
        history = load_lakeshore_history(folder, time.time() - LONG_SPAN_S)
        gap = max(15.0, 3 * self.interval.seconds)
        if history:
            times = to_plot_times([p[0] for p in history])
            previous = None
            for point, plot_time in zip(history, times):
                if previous is not None and point[0] - previous > gap:
                    self.data.append((previous + 0.001, to_plot_time(previous + 0.001)) + (NAN,) * 6)
                self.data.append((point[0], plot_time) + point[1:])
                previous = point[0]
            # Break the lines between the saved history and this run
            self.data.append((previous + 0.001, to_plot_time(previous + 0.001)) + (NAN,) * 6)
        self.history_note = ("24 h history at start-up: {} readings".format(len(history))
                             if history else "no 24 h history at start-up")
        self.status_label.configure(text="Connecting to Lake Shore 336 at {}:{} ...".format(args.ls_host, args.ls_port))

        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    # ---- layout -----------------------------------------------------------------

    def _build(self, parent):
        self.frame = tk.Frame(parent, relief="groove", borderwidth=2, bg=PANEL_BG)
        args = self.app.args

        banner = tk.Frame(self.frame, bg=INK, padx=10, pady=4)
        banner.pack(fill="x")
        tk.Label(banner, text="LAKE SHORE 336", font=(UI_FONT, 17, "bold"), fg="white", bg=INK).pack(side="left")
        tk.Label(banner, text="  bearing (A) / drive (B)    {}:{}".format(args.ls_host, args.ls_port),
                 font=(UI_FONT, 10), fg="white", bg=INK).pack(side="left", pady=(4, 0))
        right = tk.Frame(banner, bg=INK)
        right.pack(side="right")
        tk.Label(right, text="Temperature interval (s)", font=(UI_FONT, 11), fg="white", bg=INK).grid(row=0, column=0, sticky="e")
        self.interval_box = Field(right, 5, on_activity=lambda: None, on_submit=self.change_interval)
        self.interval_box.set_val(f"{self.interval.seconds:g}")
        self.interval_box.entry.grid(row=0, column=1, padx=(6, 0))
        self.interval_note = tk.Label(right, text="Enter to apply", font=(UI_FONT, 8), fg="#c9d4e2", bg=INK,
                                      width=22, anchor="e")
        self.interval_note.grid(row=1, column=0, columnspan=2, sticky="e")

        readouts = tk.Frame(self.frame, padx=10, pady=4, bg=PANEL_BG)
        readouts.pack(fill="x")
        self.readouts_frame = readouts
        if args.ami["enabled"]:               # third column: AMI 1700 LN2 level (AmiPanel)
            readouts.columnconfigure(2, weight=2, uniform="readout")
        self.readouts = {}
        self.heater_badges = {}
        for column, (channel, name, color) in enumerate(CHANNELS):
            box = tk.Frame(readouts, relief="groove", borderwidth=2, padx=10, pady=1, bg="white")
            box.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 10, 0))
            readouts.columnconfigure(column, weight=3, uniform="readout")
            title_row = tk.Frame(box, bg="white")
            title_row.pack(fill="x")
            badge = tk.Label(title_row, text="", font=(UI_FONT, 9, "bold"), width=13, bg="white", fg=MUTED)
            badge.pack(side="left", pady=(2, 0))
            tk.Label(title_row, text="{} temperature ({})".format(name.capitalize(), channel),
                     font=(UI_FONT, 11), bg="white").pack(side="right")
            big = tk.Label(box, text="---", anchor="e", font=(UI_FONT, 34, "bold"), fg=color, bg="white", width=9)
            big.pack(fill="x")
            sub = tk.Label(box, text="", anchor="e", font=(UI_FONT, 10), fg=MUTED, bg="white", width=1,
                           height=2, justify="right")
            sub.pack(fill="x")
            self.readouts[channel] = (big, sub, color)
            self.heater_badges[channel] = badge

        status_row = tk.Frame(self.frame, bg=PANEL_BG, padx=10)
        status_row.pack(fill="x")
        self.live_badge = tk.Label(status_row, text="", font=(UI_FONT, 9, "bold"), width=7, bg=PANEL_BG, fg="white")
        self.live_badge.pack(side="left", padx=(0, 8))
        self.status_label = tk.Label(status_row, text="", anchor="w", font=(UI_FONT, 10),
                                     bg=PANEL_BG, justify="left", width=1)
        self.status_label.pack(side="left", fill="x", expand=True)
        self.timing_label = tk.Label(self.frame, text="", anchor="nw", font=(UI_FONT, 8), fg=MUTED,
                                     padx=10, bg=PANEL_BG, justify="left", wraplength=820, width=1, height=2)
        self.timing_label.pack(fill="x")

        # Setpoint / ramp / PID controls, with the Control switch that unlocks them
        box = tk.LabelFrame(self.frame, text=" Setpoint / ramp / PID ", font=(UI_FONT, 11, "bold"),
                            fg=INK, bg=PANEL_BG, padx=8, pady=2)
        box.pack(fill="x", padx=10, pady=(4, 4))
        header = tk.Frame(box, bg=PANEL_BG)
        header.pack(fill="x")
        self.box_images = make_checkbox_images(self.frame)
        self.control_var = tk.BooleanVar(master=self.frame, value=False)
        self.control_toggle = tk.Checkbutton(
            header, text="  Control", variable=self.control_var, command=self.toggle_control,
            image=self.box_images[0], selectimage=self.box_images[1], compound="left", indicatoron=False,
            font=(UI_FONT, 13, "bold"), fg=INK, bg=PANEL_BG, activebackground=PANEL_BG, activeforeground=INK,
            selectcolor=PANEL_BG, relief="flat", offrelief="flat", overrelief="flat", borderwidth=0,
            highlightthickness=0, cursor="hand2")
        self.control_toggle.pack(side="left")
        self.lock_timer_label = tk.Label(header, text="Locked", font=(UI_FONT, 10), fg=MUTED, bg=PANEL_BG,
                                         width=14, anchor="w")
        self.lock_timer_label.pack(side="left", padx=(8, 0))
        tk.Label(header, text="locks after 30 s without edits · ramp in K/min, 0 = off · range sent with Apply",
                 font=(UI_FONT, 8), fg=MUTED, bg=PANEL_BG).pack(side="right")

        grid = tk.Frame(box, bg=PANEL_BG)
        grid.pack(fill="x", pady=(2, 0))
        headings = (("Target (K)", 8), ("Ramp (K/min)", 7), ("P", 6), ("I", 6), ("D", 5))
        for column, (heading, _) in enumerate(headings, start=1):
            tk.Label(grid, text=heading, font=(UI_FONT, 10), fg=MUTED, bg=PANEL_BG, padx=0).grid(
                row=0, column=column, sticky="e", padx=(4, 7))       # flush with the digits, not the border
        tk.Label(grid, text="Heater range", font=(UI_FONT, 10), fg=MUTED, bg=PANEL_BG).grid(row=0, column=6, padx=(8, 0))
        for row, (channel, name, color) in enumerate(CHANNELS, start=1):
            self.pid_labels[channel] = tk.Label(grid, text=f"{name} · awaiting controller", fg=color, bg=PANEL_BG,
                                                font=(UI_FONT, 9), justify="left", anchor="nw", width=26, height=3)
            self.pid_labels[channel].grid(row=row, column=0, sticky="w", pady=2)
            self.control_fields[channel] = {}
            for column, (key, (_, width)) in enumerate(zip(("SP", "R", "P", "I", "D"), headings), start=1):
                widget = Field(grid, width, on_activity=self.field_activity,
                               on_change=lambda text: self.field_activity())
                widget.set_active(False)
                widget.entry.grid(row=row, column=column, padx=4, sticky="e")
                self.control_fields[channel][key] = widget
            var = tk.IntVar(master=grid, value=-1)
            segment = tk.Frame(grid, bg=PANEL_BG)
            segment.grid(row=row, column=6, padx=(8, 0))
            buttons = []
            for code, text in HEATER_RANGES:
                radio = tk.Radiobutton(segment, text=text, variable=var, value=code, indicatoron=False, width=4,
                                       font=(UI_FONT, 10, "bold"), fg=ERROR_RED if code == 0 else INK,
                                       selectcolor=LOCKED_SELECTED, bg=DISABLED_BG, state="disabled",
                                       highlightthickness=2, highlightbackground=PANEL_BG, highlightcolor=INK,
                                       command=self.range_clicked, cursor="hand2")
                radio.pack(side="left", padx=1)
                buttons.append(radio)
            self.range_vars[channel] = var
            self.range_buttons[channel] = buttons
            button = tk.Button(grid, text="Apply", font=(UI_FONT, 11, "bold"), width=6, state="disabled",
                               bg=DISABLED_BG, command=lambda c=channel: self.apply_channel(c))
            button.grid(row=row, column=7, padx=(8, 0))
            self.apply_buttons[channel] = button
        # Styled after the 336's front-panel ALL OFF key; works only while Control is on
        self.all_off_button = tk.Button(
            grid, text="ALL OFF", font=(UI_FONT, 11, "bold"), fg="white", bg=ALL_OFF_DIM,
            activebackground=ALL_OFF_PRESSED, activeforeground="white", disabledforeground="#fbe3e1",
            relief="raised", borderwidth=3, pady=1, state="disabled", cursor="hand2", command=self.all_off)
        self.all_off_button.grid(row=len(CHANNELS) + 1, column=6, sticky="ew", padx=(8, 0), pady=(2, 0))

        self.control_note = tk.Label(box, text="Control off · values update automatically",
                                     anchor="nw", font=(UI_FONT, 10), fg=MUTED, bg=PANEL_BG,
                                     wraplength=780, justify="left", width=1, height=2)
        self.control_note.pack(fill="x", pady=(2, 0))

    def _build_plots(self, ax_long, ax_short):
        self.panels = []
        for ax, title in ((ax_long, "Bearing (A) / drive (B), past 24 h"),
                          (ax_short, "Past 30 min")):
            heater_ax = ax.twinx()
            heater_ax.tick_params(labelsize=8)
            ax.set_zorder(heater_ax.get_zorder() + 1)   # temperatures drawn over the heater traces
            ax.patch.set_visible(False)
            ax.set_title(title, fontsize=10, fontweight="bold", color=INK, loc="center")
            ax.set_title("solid: temperature   dashed: setpoint", fontsize=8, color=MUTED, loc="left")
            ax.set_title("faint: heater % (right axis)", fontsize=8, color=MUTED, loc="right")
            ax.set_ylabel("Temperature (K)", fontsize=9)
            heater_ax.set_ylabel("Heater (%)", fontsize=9)
            traces = {}
            for channel, name, color in CHANNELS:
                temp, = ax.plot([], [], color=color, linewidth=1.8)
                setpoint, = ax.plot([], [], color=color, linestyle=(0, (6, 4)), alpha=0.7,
                                    linewidth=1.3, drawstyle="steps-post")
                heater, = heater_ax.plot([], [], color=color, linewidth=0.8, alpha=0.3)
                traces[channel] = (temp, setpoint, heater)
            self.panels.append((ax, heater_ax, traces))

    # ---- worker -------------------------------------------------------------------

    def _worker(self):
        try:
            self.result[0] = acquire(self.app.args, self.stop_event, self.updates.put, self.interval,
                                     self.controls, lambda notice: self.updates.put({"_notice": notice}),
                                     lambda path: self.updates.put({"_file": path}))
        except Exception as exc:
            self.result[0] = 1
            print(f"Lake Shore logging stopped: {exc}", file=sys.stderr)
            self.updates.put({"timestamp_utc": utc_now(), "error": f"Logging stopped: {exc}"})

    def stop(self):
        self.controls.set_enabled(False)
        self.stop_event.set()

    # ---- periodic -------------------------------------------------------------------

    def tick(self):
        changed = False
        while True:
            try:
                item = self.updates.get_nowait()
            except queue.Empty:
                break
            if "_notice" in item:
                self.handle_notice(item["_notice"])
            elif "_file" in item:
                self.log_path = item["_file"]
            else:
                self.add(item)
                changed = True
        self.refresh_controls()
        self.expire_controls()
        self.update_readouts()
        return changed

    def add(self, row):
        self.awaiting.difference_update(self.refill_next)
        self.refill.update(self.refill_next)
        self.refill_next.clear()
        self.live_row = row
        self.live_received = time.monotonic()
        self.update_timing()
        self.refresh_controls()
        try:
            epoch = parse_iso(row["timestamp_utc"]).timestamp()
        except (KeyError, ValueError):
            epoch = time.time()
        point = temperature_point(row, epoch)
        entry = (epoch, to_plot_time(epoch)) + point[1:]
        if self.data and self.data[-1][0] == epoch:
            self.data[-1] = entry
        else:
            self.data.append(entry)
        while self.data and self.data[0][0] < epoch - LONG_SPAN_S:
            self.data.popleft()

    def fresh(self):
        row = self.live_row
        return row is not None and not row.get("error") and (
            time.monotonic() - self.live_received <= max(15, self.interval.seconds * 2))

    def update_readouts(self):
        row = self.live_row
        fresh = self.fresh()
        for channel, name, color in CHANNELS:
            big, sub, color = self.readouts[channel]
            self.update_badge(channel, row if fresh else None)
            if row is None:
                big.configure(text="---", fg="#888888")
                sub.configure(text="waiting for the controller\n")
                continue
            if not fresh:
                big.configure(text="NO DATA", fg="#888888")
                sub.configure(text="no fresh reading\n")
                continue
            status = reading_status(row, channel)
            if status:
                big.configure(text="INVALID", fg=ERROR_RED)
            else:
                big.configure(text="{:.2f} K".format(number_or_nan(row.get(f"temp_{channel}_K"))), fg=color)
            output = associated(row, channel)
            first, second = [], []
            if status:
                second.append("sensor status code {}".format(status))
            if output:
                setpoint = number_or_nan(row.get(f"out{output}_setpoint_K"))
                level = number_or_nan(row.get(f"out{output}_level_percent"))
                if math.isfinite(setpoint):
                    first.append("setpoint {:g} K".format(setpoint))
                if math.isfinite(level):
                    first.append("heater {:.1f} %".format(level))
                second.append("output {} ({})".format(output, row.get(f"out{output}_mode", "?")))
                if number_or_nan(row.get(f"out{output}_ramping")) == 1:
                    second.append("ramping")
            sub.configure(text="   ".join(first) + "\n" + "   ".join(second))

        if row is None:
            return
        if row.get("error"):
            badge, badge_bg, text, colour = "ERROR", ERROR_RED, row["error"], ERROR_RED
        elif not fresh:
            badge, badge_bg, text, colour = "STALE", ERROR_RED, "no fresh reading", ERROR_RED
        else:
            badge, badge_bg, text, colour = "LIVE", LIVE_GREEN, "", "black"
            if any(reading_status(row, c) for c in "AB"):
                text, colour = "sensor status warning; invalid temperatures hidden", ERROR_RED
        if not self.thread.is_alive():
            badge, badge_bg, colour = "STOPPED", ERROR_RED, ERROR_RED
            text = "logging stopped - restart the program"
        try:
            stamp = parse_iso(row["timestamp_utc"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            stamp = "?"
        if self.live_badge.cget("text") != badge:
            self.live_badge.configure(text=badge, bg=badge_bg)
        self.status_label.configure(text="Last sample: {}    {}".format(stamp, text), fg=colour)

    def update_badge(self, channel, row):
        """Heater state in the temperature box: OFF / LOW / MED / HIGH, or a heater fault."""
        badge = self.heater_badges[channel]
        channel_color = dict((c, colour) for c, _, colour in CHANNELS)[channel]
        output = associated(row, channel) if row else None
        code = number_or_nan(row.get(f"out{output}_range_code")) if output in (1, 2) else NAN
        fault = number_or_nan(row.get(f"out{output}_heater_status")) if output in (1, 2) else NAN
        if math.isfinite(fault) and int(fault) in HEATER_FAULTS:
            text, fg, bg = "HEATER " + HEATER_FAULTS[int(fault)], "white", ERROR_RED
        elif not math.isfinite(code):
            text, fg, bg = "", MUTED, "white"
        elif int(code) == 0:
            text, fg, bg = "HEATER OFF", "white", ERROR_RED
        else:
            text, fg, bg = "HEATER " + dict(HEATER_RANGES).get(int(code), "?").upper(), "white", channel_color
        if badge.cget("text") != text:
            badge.configure(text=text, fg=fg, bg=bg)

    def update_plots(self, long, short, now, follow):
        for do, (ax, heater_ax, traces), span, max_points in ((long, self.panels[0], LONG_SPAN_S, LONG_MAX_POINTS),
                                                               (short, self.panels[1], SHORT_SPAN_S, None)):
            if not do:
                continue
            columns = recent_columns(self.data, now - span, 8)
            epochs, xs = columns[0], columns[1]
            series = {"A": (columns[2], columns[6], columns[4]), "B": (columns[3], columns[7], columns[5])}
            keep, left, right = visible_limits(epochs, now, span)
            temps_in_view, levels_in_view = [], []
            for channel, (temp_line, setpoint_line, heater_line) in traces.items():
                for kind, line, values in zip(("temp", "setpoint", "heater"), (temp_line, setpoint_line, heater_line),
                                              series[channel]):
                    shown = self.plot.trace_shown(channel) and self.plot.trace_shown(kind)
                    if line.get_visible() != shown:
                        line.set_visible(shown)
                    if not shown:
                        continue       # hidden traces do not count for the y range either
                    x, y = xs[keep], values[keep]
                    if max_points:
                        x, y = envelope(x, y, max_points)
                    line.set_data(x, y)
                    (levels_in_view if line is heater_line else temps_in_view).append(y)
            if follow:
                ax.set_xlim(left, right)
                if temps_in_view:
                    set_y_limits(ax, np.concatenate(temps_in_view), 0.5)
                levels = np.concatenate(levels_in_view) if levels_in_view else np.zeros(0)
                levels = levels[np.isfinite(levels)]
                if levels.size:
                    heater_ax.set_ylim(min(0, math.floor(levels.min() / 10) * 10),
                                       max(1, math.ceil(levels.max() / 10) * 10))

    # ---- controls (logic unchanged from lakeshore336_logger.py) -----------------------

    def control_message(self, text, error=False):
        self.control_note.configure(text=text, fg=ERROR_RED if error else MUTED)

    def toggle_control(self):
        enabled = bool(self.control_var.get())
        self.controls.set_enabled(enabled)
        self.refill.update(("A", "B"))
        self.refresh_controls()
        self.control_message("Control on · edit fields, then Apply per channel" if enabled
                             else "Control off · unapplied edits discarded")

    def field_activity(self):
        if not self.syncing_fields:
            self.controls.touch()

    def range_clicked(self):
        self.field_activity()
        self.refresh_controls()       # restyle the selector at once

    def expire_controls(self):
        if self.controls.enabled and self.controls.remaining() <= 0:
            self.controls.set_enabled(False)
            self.control_var.set(False)
            self.control_message("Control locked after 30 seconds of field inactivity")
        label = f"Locks in {math.ceil(self.controls.remaining())} s" if self.controls.enabled else "Locked"
        if self.lock_timer_label.cget("text") != label:
            self.lock_timer_label.configure(text=label)

    def refresh_controls(self):
        row = self.live_row
        fresh = self.fresh()
        for channel, name, _ in CHANNELS:
            output = associated(row, channel) if fresh else None
            prefix = f"out{output}_"
            valid = fresh and output in (1, 2) and row.get(prefix + "setpoint_units") in ("K", "C")
            if valid:
                values = tuple(number(row[prefix + key]) for key in ("setpoint_K", "P", "I", "D"))
                rate = number(row.get(prefix + "ramp_rate_K_per_min", 0)) if int(row.get(prefix + "ramp_enabled", 0)) else 0.0
                requested = self.requested_targets.get(channel)
                if requested is not None and (requested["output"] != output or
                        math.isclose(values[0], requested["value"], abs_tol=0.001)):
                    self.requested_targets.pop(channel, None)
                    requested = None
                # Only rows read after the Apply can show that a ramp stopped (fixes a false
                # "ramp stopped" message from the last pre-Apply row in the original script).
                if (requested is not None and self.live_received > requested["since"]
                        and not int(row.get(prefix + "ramping", 0))):
                    self.control_message(f"{name}: ramp stopped at {values[0]:g} K; requested target was {requested['value']:g} K", error=True)
                    self.requested_targets.pop(channel, None)
                    self.refill.add(channel)
                    requested = None
                label = f"{name} · out {output}\nLive P {values[1]:g}   I {values[2]:g}   D {values[3]:g}"
                if int(row.get(prefix + "ramping", 0)):
                    label += f"\nActive {values[0]:g} K"
                    if requested is not None:
                        label += f" to {requested['value']:g} K"
                    else:                # started elsewhere: the 336 does not report the final target
                        label += ", ramping"
                if self.pid_labels[channel].cget("text") != label:
                    self.pid_labels[channel].configure(text=label)
                if not self.controls.enabled or channel not in self.drafts or channel in self.refill:
                    draft_values = (requested["value"] if requested is not None else values[0],) + values[1:]
                    range_code = int(number_or_nan(row.get(prefix + "range_code"))) \
                        if math.isfinite(number_or_nan(row.get(prefix + "range_code"))) else None
                    self.drafts[channel] = {"channel": channel, "output": output,
                                            "units": 1 if row[prefix + "setpoint_units"] == "K" else 2,
                                            "baseline": draft_values, "ramp_baseline": rate,
                                            "range_baseline": range_code}
                    self.range_vars[channel].set(-1 if range_code is None else range_code)
                    for key, value in zip(("SP", "P", "I", "D", "R"), draft_values + (rate,)):
                        self.syncing_fields = True
                        try:
                            self.control_fields[channel][key].set_val(f"{value:g}")
                        finally:
                            self.syncing_fields = False
                    self.refill.discard(channel)
            else:
                label = f"{name} · awaiting fresh heater readback"
                if self.pid_labels[channel].cget("text") != label:
                    self.pid_labels[channel].configure(text=label)
            editable = bool(valid and self.controls.enabled and channel not in self.awaiting)
            if self._editable_states.get(channel) != editable:
                self._editable_states[channel] = editable
                for widget in self.control_fields[channel].values():
                    widget.set_active(editable)
                for radio in self.range_buttons[channel]:
                    radio.configure(state="normal" if editable else "disabled")
            # Mark edits that have not been applied; Apply is offered only when there is one
            draft = self.drafts.get(channel) if valid else None
            live_range = draft.get("range_baseline") if draft else None
            changed = False
            if editable and draft:
                live = dict(zip(("SP", "P", "I", "D"), draft["baseline"]), R=draft["ramp_baseline"])
                for key, widget in self.control_fields[channel].items():
                    field_changed = differs(widget.text, live[key])
                    widget.set_changed(field_changed)
                    changed = changed or field_changed
                changed = changed or self.range_vars[channel].get() != live_range
            can_apply = editable and changed
            if self._apply_states.get(channel) != can_apply:
                self._apply_states[channel] = can_apply
                self.apply_buttons[channel].configure(state="normal" if can_apply else "disabled",
                                                      bg="#dcecf8" if can_apply else DISABLED_BG)
            self.style_range_buttons(channel, live_range, editable)
        all_off = bool(self.controls.enabled and self.fresh() and not self.awaiting)
        if all_off != self._all_off_state:
            self._all_off_state = all_off
            self.all_off_button.configure(state="normal" if all_off else "disabled",
                                          bg=ALL_OFF_RED if all_off else ALL_OFF_DIM)

    def style_range_buttons(self, channel, live_range, editable):
        """Selected range: solid fill with white text (amber if not yet applied); live range: dark outline."""
        selected = self.range_vars[channel].get()
        for (code, _), radio in zip(HEATER_RANGES, self.range_buttons[channel]):
            is_selected = code == selected
            if not editable:
                fill = LOCKED_SELECTED
            elif live_range is not None and selected != live_range:
                fill = PENDING_DARK
            else:
                fill = INK
            style = {
                "selectcolor": fill,
                "fg": "white" if is_selected else (ERROR_RED if code == 0 else INK),
                "activeforeground": "white" if is_selected else (ERROR_RED if code == 0 else INK),
                "disabledforeground": "#f2f4f7" if is_selected else "#a3adb8",
                "highlightbackground": INK if code == live_range else PANEL_BG,
                "bg": "white" if editable else DISABLED_BG,
            }
            if self._range_styles.get(radio) != style:
                self._range_styles[radio] = style
                radio.configure(**style)

    def apply_channel(self, channel):
        try:
            if not self.controls.enabled or channel in self.awaiting:
                raise ValueError("Enable Control and wait for any pending Apply")
            if not self.fresh():
                raise ValueError("Wait for fresh controller readings")
            draft = self.drafts[channel]
            if associated(self.live_row, channel) != draft["output"]:
                raise ValueError("Output assignment changed; switch Control off/on")
            values = validate_controls([self.control_fields[channel][key].text for key in ("SP", "P", "I", "D")])
            ramp_rate = validate_ramp(self.control_fields[channel]["R"].text)
            heater_range = self.range_vars[channel].get()
            if heater_range not in (0, 1, 2, 3):
                raise ValueError("Choose a heater range (Off, Low, Med, or High)")
            self.controls.submit(dict(draft, values=values, ramp_rate=ramp_rate, range=heater_range))
            self.awaiting.add(channel)
            self.refresh_controls()
            self.control_message(f"{channel}: Apply queued; waiting for readback")
        except (ValueError, KeyError) as exc:
            self.control_message(str(exc), error=True)

    def all_off(self):
        try:
            if not self.controls.enabled:
                raise ValueError("Enable Control first")
            if self.awaiting:
                raise ValueError("Wait for the pending Apply to finish")
            self.controls.touch()
            self.controls.submit({"channel": None, "channels": ("A", "B"), "all_off": True})
            self.awaiting.update(("A", "B"))
            self.refresh_controls()
            self.control_message("ALL OFF queued: switching heater outputs 1 and 2 off ...")
        except ValueError as exc:
            self.control_message(str(exc), error=True)

    def handle_notice(self, notice):
        for other in notice.get("channels", ()):
            self.refill_next.add(other)
        channel = notice["channel"]
        if channel is not None:
            self.refill_next.add(channel)
            if not notice["error"] and notice.get("target_K") is not None:
                self.requested_targets[channel] = {"value": notice["target_K"], "output": notice["output"],
                                                   "since": time.monotonic()}
            elif (not notice["error"] and notice.get("active_sp_K") is not None
                  and notice.get("desired_K") is not None
                  and math.isclose(notice["active_sp_K"], notice["desired_K"], abs_tol=0.001)):
                self.requested_targets.pop(channel, None)
        if not self.controls.enabled and self.control_var.get():
            self.control_var.set(False)
        self.control_message((f"{channel}: " if channel else "") + notice["message"], notice["error"])

    def update_timing(self):
        row = self.live_row or {}
        duration = "—"
        if row.get("timestamp_utc") and row.get("sample_end_utc"):
            try:
                seconds = (parse_iso(row["sample_end_utc"]) - parse_iso(row["timestamp_utc"])).total_seconds()
                duration = f"{seconds:.2f} s"
            except ValueError:
                pass
        if self.interval.seconds < FULL_REFRESH_SECONDS:
            fast_duration = row.get("_fast_read_seconds")
            fast_text = f"{fast_duration:.2f} s" if fast_duration is not None else duration
            text = f"Fast: {self.interval.seconds:g} s · Full: {FULL_REFRESH_SECONDS:g} s · Last read: {fast_text}"
        else:
            text = f"Requested interval: {self.interval.seconds:g} s · Last scan: {duration}"
        log = "    Log: {}".format(Path(self.log_path).name) if self.log_path else ""
        self.timing_label.configure(text=text + log + "    " + self.history_note)

    def change_interval(self, text):
        try:
            seconds = self.interval.set(text)
        except ValueError:
            self.interval_note.configure(text="Enter a number of at least 2 s", fg="#ffb4a8")
        else:
            self.interval_note.configure(text=f"Applied: {seconds:g} s", fg="#a7e3c4")
        self.update_timing()


# ==========================================================================
# The window
# ==========================================================================

class MonitorApp:

    def dark_clicked(self):
        self.set_dark(bool(self.dark_var.get()))
        save_theme(THEME["dark"])

    def set_dark(self, dark):
        if THEME["dark"] == dark:
            return
        THEME["dark"] = dark
        recolor_widgets(self.root, dark)
        for empty, ticked, size in CHECKBOX_IMAGES:
            paint_checkbox_images(empty, ticked, size)
        for plot in self.plots:
            recolor_toolbar(plot.toolbar, dark)
            recolor_figure(plot.figure, dark)
            plot.canvas.draw_idle()

    def open_log_viewer(self):
        """Start dnp_logviewer.py (next to this file) as its own process; it only reads the logs."""
        viewer = Path(__file__).resolve().with_name("dnp_logviewer.py")
        if not viewer.exists():
            self.viewer_note.configure(text="dnp_logviewer.py not found in {}".format(viewer.parent), fg="#ffb4a8")
            return
        try:
            subprocess.Popen([sys.executable, str(viewer), "--base-dir", str(self.args.base_dir)],
                             start_new_session=True, stdin=subprocess.DEVNULL)
        except OSError as error:
            self.viewer_note.configure(text="Could not start the log viewer: {}".format(error), fg="#ffb4a8")
            return
        self.viewer_button.configure(state="disabled", text="Opening the log viewer ...")
        self.viewer_note.configure(text="the log viewer opens in a separate window (a few seconds)", fg="#c9d4e2")
        self.root.after(4000, self._viewer_button_ready)

    def _viewer_button_ready(self):
        self.viewer_button.configure(state="normal", text="Open log viewer:  MAS3, Lake Shore 336, and LN2")
        self.viewer_note.configure(text="opens a separate window with the saved logs, any time range", fg="#c9d4e2")

    def __init__(self, root, args, lock_handle):
        self.root = root
        self.args = args
        self.lock_handle = lock_handle
        self.closing = False
        self.force_long = self.force_short = True
        self.last_long = self.last_short = 0.0

        root.title("DNP monitor - MAS3, Lake Shore 336, and AMI 1700 (bruk800wb)")
        if args.geometry:
            root.geometry(args.geometry)
        else:
            root.geometry("1600x950")
            try:
                root.attributes("-zoomed", True)   # fill the screen (X11)
            except tk.TclError:
                pass
        root.configure(bg=PANEL_BG)
        root.protocol("WM_DELETE_WINDOW", self.close)

        top_bar = tk.Frame(root, bg=INK)
        top_bar.pack(side="top", fill="x")
        # three columns; the outer two share the spare width equally, so the button sits in the centre
        top_bar.columnconfigure(0, weight=1, uniform="side")
        top_bar.columnconfigure(2, weight=1, uniform="side")
        left_side = tk.Frame(top_bar, bg=INK)
        left_side.grid(row=0, column=0, sticky="ew")
        self.dark_var = tk.BooleanVar(master=root, value=False)
        tk.Checkbutton(left_side, text="Dark mode", variable=self.dark_var, command=self.dark_clicked,
                       bg=INK, fg="#e6edf3", activebackground=INK, activeforeground="white", selectcolor=INK,
                       font=(UI_FONT, 9, "bold"), highlightthickness=0, cursor="hand2").pack(side="left", padx=(6, 0))
        self.viewer_note = tk.Label(left_side, text="opens a separate window with the saved logs, any time range",
                                    bg=INK, fg="#c9d4e2", font=(UI_FONT, 9))
        self.viewer_note.pack(side="right", padx=(8, 10))
        self.viewer_button = tk.Button(
            top_bar, text="Open log viewer:  MAS3, Lake Shore 336, and LN2", command=self.open_log_viewer,
            font=(UI_FONT, 10, "bold"), bg="white", fg=INK, activebackground="#e4ebf4", relief="flat", bd=0,
            padx=14, pady=1, highlightthickness=1, highlightbackground="#c9d4e2", cursor="hand2", width=44)
        self.viewer_button.grid(row=0, column=1, pady=3)
        tk.Label(top_bar, text="Logs: " + str(Path(args.base_dir)), bg=INK, fg="#c9d4e2",
                 font=(UI_FONT, 9)).grid(row=0, column=2, sticky="e", padx=8)

        body = tk.Frame(root, bg=PANEL_BG)
        body.pack(fill="both", expand=True, padx=4, pady=4)
        body.columnconfigure(0, weight=1, uniform="column")
        body.columnconfigure(1, weight=1, uniform="column")
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=PANEL_BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        left.columnconfigure(0, weight=1)
        self.mas = []
        for row, (name, cfg) in enumerate(args.mas.items()):
            panel = MasPanel(self, left, name, cfg)
            panel.frame.grid(row=row, column=0, sticky="nsew", pady=(0 if row == 0 else 3, 0))
            left.rowconfigure(row, weight=1, uniform="mas")
            self.mas.append(panel)

        self.ls = LakeShorePanel(self, body)
        self.ls.frame.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        self.ami = self.ls.ami
        self.plots = [panel.plot for panel in self.mas] + [self.ls.plot]
        if load_theme():
            self.dark_var.set(True)
            self.set_dark(True)
        self.housekeeper = Housekeeper(args.base_dir)
        self.housekeeper.start()

        root.after(UI_TICK_MS, self._tick)

    def request_redraw(self):
        self.force_long = self.force_short = True

    def _tick(self):
        if self.closing:
            return
        new = any([panel.tick() for panel in self.mas])
        new = self.ls.tick() or new
        if self.ami is not None:
            self.ami.tick()
        for plot in self.plots:
            plot.tick()
        now = time.monotonic()
        long = self.force_long or now - self.last_long >= LONG_REDRAW_S
        short = long or self.force_short or (new and now - self.last_short >= SHORT_REDRAW_S)
        if long or short:
            epoch = time.time()
            for panel in self.mas:
                panel.update_plots(long, short, epoch)
            self.ls.update_plots(long, short, epoch, self.ls.plot.follow_live)
            for plot in self.plots:
                plot.canvas.draw_idle()
            if long:
                self.last_long = now
            self.last_short = now
            self.force_long = self.force_short = False
        self.root.after(UI_TICK_MS, self._tick)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.housekeeper.stop()
        self.ls.stop()
        if self.ami is not None:
            self.ami.stop()
        for panel in self.mas:
            panel.stop()
        self.ls.thread.join(timeout=self.args.timeout + 3)
        for panel in self.mas:
            panel.poller.join(timeout=2 * MAS_REQUEST_TIMEOUT_S + 2)   # includes the logout
        if self.ami is not None:
            self.ami.poller.join(timeout=12)
        if self.lock_handle is not None:
            self.lock_handle.close()
            self.lock_handle = None
        print("Stopped.", file=sys.stderr)
        self.root.destroy()


# ==========================================================================

def acquire_lock(base_dir):
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    handle = open(str(Path(base_dir) / LOCK_NAME), "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.seek(0)
        owner = handle.read().strip()
        handle.close()
        return None, owner
    handle.seek(0)
    handle.truncate()
    handle.write("pid {} started {}\n".format(os.getpid(), datetime.now().isoformat(timespec="seconds")))
    handle.flush()
    return handle, ""


def parse_args():
    parser = argparse.ArgumentParser(description="MAS3 and Lake Shore 336 monitor.")
    parser.add_argument("--base-dir", default=BASE_DIR, help="folder for logs and config (default: %(default)s)")
    parser.add_argument("--config", default=None,
                        help="config file (default: <base-dir>/{})".format(CONFIG_NAME))
    parser.add_argument("--interval", type=positive_seconds, default=DEFAULT_INTERVAL_SECONDS,
                        help="Lake Shore fast interval in seconds (default 3, minimum 2; full refresh minimum: 5)")
    parser.add_argument("--timeout", type=positive_seconds, default=5.0, help="Lake Shore socket timeout (s)")
    parser.add_argument("--geometry", default="", help="window size, e.g. 1700x950 (default: fill the screen)")
    args = parser.parse_args()
    if args.interval < MIN_INTERVAL_SECONDS:
        parser.error("--interval must be at least {:g} seconds".format(MIN_INTERVAL_SECONDS))
    args.config = args.config or str(Path(args.base_dir) / CONFIG_NAME)
    return args


def main():
    args = parse_args()
    root = tk.Tk()
    try:
        args.mas, lakeshore, args.ami, created, ami_added = load_config(args.config)
    except ConfigError as error:
        print("Configuration error: {}".format(error), file=sys.stderr)
        root.withdraw()
        messagebox.showerror("DNP monitor - configuration error",
                             "{}\n\nFix the file and start the monitor again.".format(error))
        root.destroy()
        return 2
    args.ls_host, args.ls_port = lakeshore["host"], lakeshore["port"]
    if created:
        print("Wrote a default configuration file: {}".format(args.config), file=sys.stderr)
    elif ami_added:
        print("Added an [AMI1700] section to {}".format(args.config), file=sys.stderr)

    lock_handle, owner = acquire_lock(args.base_dir)
    if lock_handle is None:
        root.withdraw()
        messagebox.showerror("DNP monitor already running",
                             "Another copy of the DNP monitor is already running ({}).\n\n"
                             "Close that window first; only one copy may log at a time.".format(owner or "owner unknown"))
        root.destroy()
        return 1
    app = MonitorApp(root, args, lock_handle)

    def on_signal(signum, frame):
        root.after(0, app.close)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    root.mainloop()
    return app.ls.result[0]


if __name__ == "__main__":
    sys.exit(main())
