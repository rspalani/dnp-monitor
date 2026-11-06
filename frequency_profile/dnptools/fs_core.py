# -*- coding: utf-8 -*-
"""
fs_core.py  -  shared acquisition code for the DNP frequency-profile scripts
(TopSpin / Jython)

Not run directly. The TopSpin script fs.py (in TopSpin's py/user folder) runs
    execfile("/opt/dnptools/fs_core.py")
    run_settings(sys.argv[1:])
execfile is used instead of import so that TopSpin always runs the current
version of this file; an imported module can stay cached in TopSpin's Jython
until TopSpin is restarted.

Settings files: one per kind of experiment, in /opt/nmrdata/fs_settings, named
settings_<name>.py; a new one is made by copying settings_template.py there.
'fs bdpa' (or 'fs settings_bdpa') on TopSpin's command line uses
settings_bdpa.py; 'fs' alone lists the settings files to choose from, which is
also what happens if TopSpin does not pass the name on to the script. A
settings file is Python: plain assignments, run with frange() available. Its
UPPERCASE names are settings (list and defaults in SETTINGS below); an
UPPERCASE name that is not in the list stops the script, because it is
usually a typo. Lowercase names, such as frequency segments, are ignored.
RUN_LABEL defaults to <name>. settings_template.py itself is not run.

Dataset and template: DATA_DIR, DATA_NAME and TEMPLATE_EXPNO set in the
settings file are used. If DATA_DIR and DATA_NAME are both empty, the dataset open in TopSpin
when the script starts is used; if TEMPLATE_EXPNO is empty (None), the expno
open in TopSpin is the template, and it must belong to the run's dataset. The
confirmation dialog shows the dataset, the new expnos and the template in large
type, with where each came from. Before the dialog, and again after OK, the
script checks that none of the planned expnos exists yet; if some do, it stops
and names the first START_EXPNO with enough free expnos.

Run plan: REPEATS sets. Each set is an optional OFF reference, one ON record
per frequency in FREQS, and an optional final OFF reference, selected with
OFF_MODE. Every set occupies a fixed block of expnos from START_EXPNO on; a
point that cannot be set on the AWG is skipped and its expno is left empty.

Records: each run gets a folder inside the dataset,
    <DATA_DIR>/<DATA_NAME>/fs_runs/<YYYYMMDD-HHMMSS>_<RUN_LABEL>_e<START_EXPNO>/
named after the time the run started. It holds run.txt (one line per finished
record, read by fs_plot.py and fs_rephase.py), log.txt (every step,
time-stamped), a copy of the settings file, settings.txt (every setting as
used, including the full frequency list), and the viewer's files (viewer.log, plot.png, values.tsv,
phase.txt). Because the folder is inside the dataset, it is copied with it.
One line is also appended to the common index /opt/nmrdata/fs_runs.tsv when a
run starts and one when it ends.

Live plot: the viewer fs_plot.py (system Python 3) is started in the
background. It reads run.txt and the processed spectra (pdata/1/1r, 1i) and
plots the intensity per scan, or I_on/I_off - 1 when start OFFs are recorded,
against frequency, one series per set. Closing the viewer does not affect the
run; it can be reopened at any time with the command printed in the log, e.g.
    python3 /opt/dnptools/fs_plot.py <run folder>/run.txt
With RESPAWN_VIEWER = True, each time a record is added to run.txt, pgrep is
used to check whether a viewer for this run is running, and one is started if
not; a viewer closed during a record reappears once that record has been
added. A viewer opened by hand with the command above counts as running.

XCMD("zg", wait=WAIT_TILL_DONE) returns before the acquisition has finished on
this spectrometer, so each record is timed here:
  1. After zg the script sleeps until (NS+DS)*D1 has elapsed; the acquisition
     cannot finish earlier than that.
  2. It then checks the expno every POLL_INTERVAL s until audita.txt has been
     written after that point (TopSpin writes it when the acquisition ends).
  3. It processes the record with PROCESS_CMDS (default: efp, absn), waits
     POST_ACQ_PAD s, and only then sends the next AWG command.
Polling continues up to a deadline of
    (NS+DS)*(D1+SCAN_OVERHEAD) + MAX_EXTRA_WAIT   s after zg,
where the first term is the expected duration of the record. The record is
accepted whenever audita.txt appears before the deadline, including after
the expected duration. Only if it has not appeared by the deadline does the
script send 'stop' to the AWG, show an error box, and end without starting
further records.

If the script is stopped from TopSpin, mm-wave 'stop' is sent and run.txt
ends with '# end: stopped: interrupted ...'.
"""
import os
import re
import time
import subprocess

# TopSpin's Jython environment rebinds the name Exception (an IOError went
# straight through such a handler in TopSpin 3.6.2), so the handlers here use
# CATCH: Python's own base class, taken from the builtins module, plus
# java.lang.Exception for errors raised on TopSpin's Java side. Stopping the
# script from TopSpin raises java.lang.ThreadDeath, an Error, which is
# deliberately not caught.
try:
    import __builtin__ as _builtins
except ImportError:
    import builtins as _builtins
try:
    from java.lang import Exception as _JavaException
    CATCH = (_builtins.Exception, _JavaException)
except ImportError:
    CATCH = (_builtins.Exception,)


class RunAbort(_builtins.Exception):
    pass


# ---- Installation -----------------------------------------------------------
DNPTOOLS      = "/opt/dnptools"
AWG_PYTHON    = "python"                        # interpreter that runs awg_cmd.py
AWG_CMD_PATH  = DNPTOOLS + "/awg_cmd.py"
VIEWER_PYTHON = "/usr/bin/python3"
VIEWER_PATH   = DNPTOOLS + "/fs_plot.py"
INDEX_PATH    = "/opt/nmrdata/fs_runs.tsv"      # common index, one line per run start and end
RUNS_SUBDIR   = "fs_runs"                       # run folders, inside each dataset
SETTINGS_DIR  = "/opt/nmrdata/fs_settings"      # settings_<name>.py files

# ---- Settings: (name, default) ------------------------------------------------
REQUIRED = "<required>"
SETTINGS = [
    ("RUN_LABEL",        REQUIRED),   # short name in the run id; default: <name> of settings_<name>.py
    ("SAMPLE",           ""),
    ("MAS_INFO",         ""),
    ("DATA_DIR",         ""),         # "" (with DATA_NAME "") = the dataset open in TopSpin
    ("DATA_NAME",        ""),
    ("POWER",            REQUIRED),
    ("START_EXPNO",      REQUIRED),
    ("TEMPLATE_EXPNO",   None),       # None = the expno open in TopSpin
    ("REPEATS",          1),
    ("OFF_MODE",         "both"),     # "start", "end", "both" or "none"
    ("FREQS",            REQUIRED),   # list of frequencies (GHz), in acquisition order
    ("D1",               REQUIRED),
    ("DS",               0),
    ("PROFILE_NS",       REQUIRED),
    ("OFF_SCANS",        REQUIRED),
    ("AWG_SETTLE",       2),
    ("SCAN_OVERHEAD",    5),
    ("POLL_INTERVAL",    5),
    ("MAX_EXTRA_WAIT",   300),
    ("POST_ACQ_PAD",     5),
    ("EST_OVERHEAD",     5),
    ("AWG_RETRIES",      3),
    ("MAX_CONSEC_SKIPS", 3),
    ("PROCESS_CMDS",     ["efp", "absn"]),
    ("PEAK_PPM",         None),       # None = whole spectrum
    ("PEAK_WINDOW_PPM",  10.0),
    ("INTENSITY_MODE",   "extreme"),  # "extreme", "max" or "sum"
    ("LAUNCH_VIEWER",    True),
    ("RESPAWN_VIEWER",   True),
]


def frange(start, stop, step):
    result = []
    current = start
    while current <= stop + (step / 2.0):
        result.append(current)
        current += step
    return result


def settings_files():
    """Names of the settings files that can be run, without settings_template.py."""
    try:
        names = os.listdir(SETTINGS_DIR)
    except CATCH:
        return []
    return sorted([n for n in names if n.startswith("settings_") and n.endswith(".py")
                   and n != "settings_template.py"])


def choose_settings():
    """Lets the user pick a settings file; returns its name or None."""
    names = settings_files()
    if not names:
        ERRMSG("fs: there are no settings files in %s.\nCopy settings_template.py there to "
               "settings_<name>.py and fill it in." % SETTINGS_DIR)
        return None
    from javax.swing import JOptionPane
    try:
        from jarray import array
        from java.lang import Object
        options = array(names, Object)
    except CATCH:
        options = names
    choice = JOptionPane.showInputDialog(
        None, "Settings file to run (in %s):" % SETTINGS_DIR, "fs: choose the settings",
        JOptionPane.QUESTION_MESSAGE, None, options, options[0])
    if choice is None:
        return None
    return str(choice)


def settings_path(name):
    """Path of the settings file meant by name: a path, 'settings_bdpa(.py)' or 'bdpa'."""
    name = str(name).strip()
    if os.sep in name or name.endswith(".py"):
        p = name if os.path.isabs(name) else os.path.join(SETTINGS_DIR, name)
        if not p.endswith(".py"):
            p += ".py"
        return p
    for cand in (name + ".py", "settings_" + name + ".py"):
        p = os.path.join(SETTINGS_DIR, cand)
        if os.path.isfile(p):
            return p
    return os.path.join(SETTINGS_DIR, "settings_" + name + ".py")


def run_settings(args=None):
    """Entry point of fs.py. args: the words after 'fs' on TopSpin's command line."""
    args = [str(a) for a in (args or []) if str(a).strip()]
    name = args[0] if args else choose_settings()
    if not name:
        MSG("fs: no settings file chosen; nothing was started.")
        return
    path = settings_path(name)
    base = os.path.basename(path)
    if base == "settings_template.py":
        ERRMSG("fs: settings_template.py is the template and is not run.\nCopy it to "
               "%s/settings_<name>.py, fill it in, and run 'fs <name>'." % SETTINGS_DIR)
        return
    if not os.path.isfile(path):
        avail = ", ".join([n[len("settings_"):-3] for n in settings_files()]) or "none"
        ERRMSG("fs: settings file %s not found.\nAvailable in %s: %s" % (path, SETTINGS_DIR, avail))
        return
    ns = {"frange": frange}
    try:
        execfile(path, ns)
    except CATCH as ex:
        ERRMSG("fs: error in the settings file %s:\n%s\nNothing was started." % (path, ex))
        return
    S = dict([(k, v) for k, v in ns.items() if k.isupper()])
    if "RUN_LABEL" not in S:
        stem = base[:-3]
        S["RUN_LABEL"] = stem[len("settings_"):] if stem.startswith("settings_") else stem
    run_profile(S, path)


def run_profile(S, source=None):
    """Runs the profile described by the settings dict S; source: the settings file, if any."""
    # ---- Settings ------------------------------------------------------------
    names = [n for n, d in SETTINGS]
    unknown = sorted([k for k in S.keys() if k.isupper() and k not in names])
    missing = [n for n, d in SETTINGS
               if d == REQUIRED and (n not in S or S[n] is None or S[n] == "")]
    if unknown or missing:
        lines = []
        if unknown:
            lines.append("Unknown setting(s): %s" % ", ".join(unknown))
        if missing:
            lines.append("Missing setting(s): %s" % ", ".join(missing))
        ERRMSG("fs_core.py: %s.\nNothing was started." % ".\n".join(lines))
        return
    c = {}
    for n, d in SETTINGS:
        if n in S:
            c[n] = S[n]
        elif isinstance(d, list):
            c[n] = list(d)
        else:
            c[n] = d

    RUN_LABEL        = str(c["RUN_LABEL"]).strip()
    SAMPLE           = c["SAMPLE"]
    MAS_INFO         = c["MAS_INFO"]
    DATA_DIR         = c["DATA_DIR"]
    DATA_NAME        = c["DATA_NAME"]
    POWER            = c["POWER"]
    START_EXPNO      = c["START_EXPNO"]
    TEMPLATE_EXPNO   = c["TEMPLATE_EXPNO"]
    REPEATS          = c["REPEATS"]
    OFF_MODE         = str(c["OFF_MODE"]).strip().lower()
    D1               = c["D1"]
    DS               = c["DS"]
    PROFILE_NS       = c["PROFILE_NS"]
    OFF_SCANS        = c["OFF_SCANS"]
    AWG_SETTLE       = c["AWG_SETTLE"]
    SCAN_OVERHEAD    = c["SCAN_OVERHEAD"]
    POLL_INTERVAL    = c["POLL_INTERVAL"]
    MAX_EXTRA_WAIT   = c["MAX_EXTRA_WAIT"]
    POST_ACQ_PAD     = c["POST_ACQ_PAD"]
    EST_OVERHEAD     = c["EST_OVERHEAD"]
    AWG_RETRIES      = c["AWG_RETRIES"]
    MAX_CONSEC_SKIPS = c["MAX_CONSEC_SKIPS"]
    PROCESS_CMDS     = list(c["PROCESS_CMDS"])
    PEAK_PPM         = c["PEAK_PPM"]
    PEAK_WINDOW_PPM  = c["PEAK_WINDOW_PPM"]
    INTENSITY_MODE   = str(c["INTENSITY_MODE"]).strip().lower()
    LAUNCH_VIEWER    = c["LAUNCH_VIEWER"]
    RESPAWN_VIEWER   = c["RESPAWN_VIEWER"]

    def fail(msg):
        ERRMSG("fs_core.py (%s): %s\nNothing was started." % (RUN_LABEL, msg))

    if not re.match(r"^[A-Za-z0-9_-]+$", RUN_LABEL):
        fail("RUN_LABEL may contain only letters, digits, '-' and '_' (got '%s')." % RUN_LABEL)
        return
    if OFF_MODE not in ("start", "end", "both", "none"):
        fail("OFF_MODE must be 'start', 'end', 'both' or 'none' (got '%s')." % OFF_MODE)
        return
    if INTENSITY_MODE not in ("extreme", "max", "sum"):
        fail("INTENSITY_MODE must be 'extreme', 'max' or 'sum' (got '%s')." % INTENSITY_MODE)
        return
    if not isinstance(REPEATS, int) or REPEATS < 1:
        fail("REPEATS must be a positive integer.")
        return
    try:
        freqs = [float(f) for f in c["FREQS"]]
    except CATCH:
        fail("FREQS must be a list of frequencies in GHz.")
        return
    if not freqs:
        fail("FREQS is empty.")
        return

    # ---- Dataset and template: from the script, or else from TopSpin ----------
    def topspin_current():
        """((dir, name, expno), '') of the dataset open in TopSpin, or (None, reason)."""
        try:
            cd = CURDATA()                       # [NAME, EXPNO, PROCNO, DIR]
        except CATCH as ex:
            return None, "the dataset open in TopSpin could not be read (%s)" % ex
        if cd is None or len(cd) < 4:
            return None, "no dataset is open in TopSpin"
        try:
            return (str(cd[3]), str(cd[0]), int(str(cd[1]))), ""
        except CATCH as ex:
            return None, "TopSpin returned an unexpected dataset %s (%s)" % (cd, ex)

    src_name = os.path.basename(source) if source else "the script"
    ds_from = "set in %s" % src_name
    if DATA_DIR and DATA_NAME:
        pass
    elif not DATA_DIR and not DATA_NAME:
        cur, why = topspin_current()
        if cur is None:
            fail("DATA_DIR and DATA_NAME are empty, so the dataset open in TopSpin would be used, "
                 "but %s." % why)
            return
        DATA_DIR, DATA_NAME = cur[0], cur[1]
        ds_from = "taken from TopSpin: the dataset open when the script started"
    else:
        fail("set both DATA_DIR and DATA_NAME, or leave both empty to use the dataset open in TopSpin.")
        return
    DATA_DIR, DATA_NAME = str(DATA_DIR), str(DATA_NAME)
    ds_root = os.path.join(DATA_DIR, DATA_NAME)
    if not os.path.isdir(ds_root):
        fail("the dataset folder %s does not exist." % ds_root)
        return

    tmpl_from = "set in %s" % src_name
    if TEMPLATE_EXPNO is None or TEMPLATE_EXPNO == "":
        cur, why = topspin_current()
        if cur is None:
            fail("TEMPLATE_EXPNO is empty, so the expno open in TopSpin would be the template, "
                 "but %s." % why)
            return
        if os.path.normpath(os.path.join(cur[0], cur[1])) != os.path.normpath(ds_root):
            fail("TEMPLATE_EXPNO is empty, so the expno open in TopSpin would be the template, but "
                 "TopSpin shows %s (expno %d), not this run's dataset %s.\nOpen the template expno "
                 "of %s in TopSpin, or set TEMPLATE_EXPNO."
                 % (os.path.join(cur[0], cur[1]), cur[2], ds_root, ds_root))
            return
        TEMPLATE_EXPNO = cur[2]
        tmpl_from = "taken from TopSpin: the expno open when the script started"
    try:
        TEMPLATE_EXPNO, START_EXPNO = int(TEMPLATE_EXPNO), int(START_EXPNO)
    except CATCH:
        fail("TEMPLATE_EXPNO and START_EXPNO must be expno numbers.")
        return
    if not os.path.isdir(os.path.join(ds_root, str(TEMPLATE_EXPNO))):
        fail("the template expno %s/%d does not exist." % (ds_root, TEMPLATE_EXPNO))
        return

    def acqus_param(expno, key):
        try:
            fh = open(os.path.join(ds_root, str(expno), "acqus"), "r")
            try:
                txt = fh.read()
            finally:
                fh.close()
            m = re.search(r"^##\$%s=\s*(.*)$" % key, txt, re.M)
            if m:
                return m.group(1).strip().strip("<>")
        except CATCH:
            pass
        return ""
    tmpl_pulprog = acqus_param(TEMPLATE_EXPNO, "PULPROG")

    # ---- Run plan: (expno, set, "OFF", label) / (expno, set, "ON", freq) -------
    per_set = []
    if OFF_MODE in ("start", "both"):
        per_set.append(("OFF", "start"))
    for f in freqs:
        per_set.append(("ON", f))
    if OFF_MODE in ("end", "both"):
        per_set.append(("OFF", "end"))
    points_per_set  = len(freqs)
    records_per_set = len(per_set)
    n_off_per_set   = records_per_set - points_per_set
    plan = []
    for set_number in range(1, REPEATS + 1):
        base = START_EXPNO + (set_number - 1) * records_per_set
        for i in range(records_per_set):
            kind, val = per_set[i]
            plan.append((base + i, set_number, kind, val))
    planned_last = plan[-1][0]

    n_records = len(plan)

    def taken(first):
        return [x for x in range(first, first + n_records)
                if os.path.exists(os.path.join(ds_root, str(x)))]

    def next_free(first):
        s = first
        while s < first + 100000:
            t = taken(s)
            if not t:
                return s
            s = max(t) + 1
        return None

    def expno_list(xs):
        if len(xs) <= 6:
            return ", ".join([str(x) for x in xs])
        return ", ".join([str(x) for x in xs[:5]]) + ", ... %d" % xs[-1]

    existing = taken(START_EXPNO)
    if existing:
        fail("%d of the %d planned expnos %d..%d already exist in %s (%s).\n"
             "The first START_EXPNO with %d free expnos after it is %s."
             % (len(existing), n_records, START_EXPNO, planned_last, ds_root,
                expno_list(existing), n_records, next_free(START_EXPNO)))
        return

    # ---- Helpers ---------------------------------------------------------------
    paths = {"log": None}

    def fmt_hms(total_seconds):
        total_seconds = int(round(total_seconds))
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        return "%dh %02dm %02ds" % (h, m, s)

    def now_str(t=None):
        if t is None:
            t = time.time()
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))

    def log(msg):
        line = "[%s] %s" % (now_str(), msg)
        print(line)
        if paths["log"] is None:
            return
        try:
            fh = open(paths["log"], 'a')
            try:
                fh.write(line + "\n")
            finally:
                fh.close()
        except CATCH:
            pass

    def confirm_dialog(message, title):
        try:
            from javax.swing import JOptionPane
            choice = JOptionPane.showConfirmDialog(
                None, message, title,
                JOptionPane.OK_CANCEL_OPTION, JOptionPane.PLAIN_MESSAGE)
            return choice == JOptionPane.OK_OPTION
        except CATCH as ex:
            ERRMSG("Could not display confirmation dialog: %s" % ex)
            return False

    def record_time(ns):
        return AWG_SETTLE + EST_OVERHEAD + (ns + DS) * (D1 + SCAN_OVERHEAD) + POST_ACQ_PAD

    per_point_time = record_time(PROFILE_NS)
    off_time       = record_time(OFF_SCANS)
    total_time     = REPEATS * (per_point_time * points_per_set + off_time * n_off_per_set)

    # ---- Confirmation --------------------------------------------------------
    def fmt_dur(sec):
        sec = int(round(sec))
        if sec >= 3600:
            return "%d h %02d min" % (sec // 3600, (sec % 3600) // 60)
        if sec >= 60:
            return "%d min %02d s" % (sec // 60, sec % 60)
        return "%d s" % sec

    def h(x):
        return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    if PEAK_PPM is None:
        window_desc = "whole spectrum"
        peak_str = "none"
    else:
        window_desc = "window %.1f +/- %.1f ppm" % (PEAK_PPM, PEAK_WINDOW_PPM / 2.0)
        peak_str = repr(float(PEAK_PPM))
    if not LAUNCH_VIEWER:
        viewer_desc = "not started automatically (command in the log)"
    elif RESPAWN_VIEWER:
        viewer_desc = "opens automatically, and again after a record if closed"
    else:
        viewer_desc = "opens automatically"

    def set_line(set_number):
        recs = [p for p in plan if p[1] == set_number]
        offs = [p[0] for p in recs if p[2] == "OFF"]
        ons  = [p[0] for p in recs if p[2] == "ON"]
        parts = []
        if OFF_MODE in ("start", "both"):
            parts.append("OFF %d" % offs[0])
        parts.append("ON %d&#8211;%d" % (ons[0], ons[-1]))
        if OFF_MODE in ("end", "both"):
            parts.append("OFF %d" % offs[-1])
        pre = ("set %d: " % set_number) if REPEATS > 1 else ""
        return pre + ", then ".join(parts)

    shown = list(range(1, REPEATS + 1))
    if REPEATS > 6:
        shown = [1, 2, 3, None, REPEATS]
    plan_html = "<br>".join([("..." if n is None else set_line(n)) for n in shown])

    sf = sorted(freqs)
    gaps = [round((b - a) * 1000.0, 3) for a, b in zip(sf[:-1], sf[1:])]
    if not gaps:
        spacing = ""
    elif min(gaps) == max(gaps):
        spacing = ", %g MHz apart" % gaps[0]
    else:
        spacing = ", %g&#8211;%g MHz apart" % (min(gaps), max(gaps))
    freq_html = "%d per set, %.3f&#8211;%.3f GHz%s" % (points_per_set, sf[0], sf[-1], spacing)
    t_end = time.time() + total_time
    if time.strftime("%Y%m%d", time.localtime(t_end)) == time.strftime("%Y%m%d"):
        end_str = time.strftime("%H:%M", time.localtime(t_end))
    else:
        end_str = time.strftime("%a %H:%M", time.localtime(t_end))
    grey = "<font color='#5a5a5a'>%s</font>"
    big = "<span style='font-size:17pt'><b>%s</b></span>"
    summary = (
        "<html><body style='width:640px'>"
        "<p><span style='font-size:14pt'><b>Start the '%s' frequency profile?</b></span></p>"
        "<table cellpadding='5' cellspacing='0' bgcolor='#e8eef8' width='100%%'>"
        "<tr><td valign='top' width='100' nowrap>Dataset</td><td>%s<br>%s</td></tr>"
        "<tr><td valign='top' width='100' nowrap>New expnos</td><td>%s<br>%s</td></tr>"
        "<tr><td valign='top' width='100' nowrap>Template</td><td>%s<br>%s</td></tr>"
        "</table>"
        "<table cellpadding='3' cellspacing='0'>"
        "<tr><td valign='top' width='100' nowrap><b>Sample</b></td><td>%s<br>%s</td></tr>"
        "<tr><td valign='top'><b>Plan</b></td><td>%s</td></tr>"
        "<tr><td valign='top'><b>Frequencies</b></td><td>%s</td></tr>"
        "<tr><td valign='top'><b>Scans</b></td><td>ON records NS %d, OFF records NS %d; "
        "D1 %s s, DS %d; power %.2f</td></tr>"
        "<tr><td valign='top'><b>Time</b></td><td><b>about %s</b>, ending around %s<br>%s</td></tr>"
        "<tr><td valign='top'><b>Records</b></td><td>%s</td></tr>"
        "<tr><td valign='top'><b>Live plot</b></td><td>%s, %s; the viewer %s</td></tr>"
        "</table>"
        "<p style='margin-top:8px'>%s</p>"
        "<p style='margin-top:10px'><span style='font-size:13pt'><b>OK</b> starts the run. "
        "<b>Cancel</b> creates nothing.</span></p>"
        "</body></html>"
        % (h(RUN_LABEL),
           big % h(ds_root), grey % h(ds_from),
           big % ("%d &#8211; %d" % (START_EXPNO, planned_last)),
           grey % ("%d records, none of them exists yet" % n_records),
           big % ("expno %d" % TEMPLATE_EXPNO) + ("&nbsp;&nbsp;%s" % h(tmpl_pulprog) if tmpl_pulprog else ""),
           grey % h(tmpl_from),
           h(SAMPLE), grey % h(MAS_INFO),
           plan_html, freq_html,
           PROFILE_NS, OFF_SCANS, h(D1), DS, POWER,
           fmt_dur(total_time), end_str,
           grey % ("ON ~%s per point, OFF ~%s each" % (fmt_dur(per_point_time), fmt_dur(off_time))
                   if n_off_per_set else "ON ~%s per point" % fmt_dur(per_point_time)),
           h(os.path.join(ds_root, RUNS_SUBDIR, "<start time>_%s_e%d" % (RUN_LABEL, START_EXPNO))),
           h(window_desc), h(INTENSITY_MODE), viewer_desc,
           grey % ("Timing: scan ~ D1 + %s s; poll every %s s; stop if a record runs %s s past its "
                   "expected end; %s s pad before each AWG change." % (SCAN_OVERHEAD, POLL_INTERVAL,
                                                                     MAX_EXTRA_WAIT, POST_ACQ_PAD)))
    )
    if not confirm_dialog(summary, "Confirm '%s' run" % RUN_LABEL):
        MSG("%s: run cancelled by user before start." % RUN_LABEL)
        return
    existing = taken(START_EXPNO)
    if existing:
        ERRMSG("%s: expno(s) %s of the planned %d..%d appeared after the dialog was shown. "
               "Nothing was started." % (RUN_LABEL, expno_list(existing), START_EXPNO, planned_last))
        return

    # ---- Run folder ------------------------------------------------------------
    run_id  = "%s_%s_e%d" % (time.strftime("%Y%m%d-%H%M%S"), RUN_LABEL, START_EXPNO)
    run_dir = os.path.join(ds_root, RUNS_SUBDIR, run_id)
    try:
        os.makedirs(run_dir)
    except CATCH as ex:
        ERRMSG("%s: could not create the run folder %s (%s). Nothing was started."
               % (RUN_LABEL, run_dir, ex))
        return
    RUN_PATH   = os.path.join(run_dir, "run.txt")
    VIEWER_LOG = os.path.join(run_dir, "viewer.log")
    paths["log"] = os.path.join(run_dir, "log.txt")
    used = dict(c)
    used.update(RUN_LABEL=RUN_LABEL, DATA_DIR=DATA_DIR, DATA_NAME=DATA_NAME,
                TEMPLATE_EXPNO=TEMPLATE_EXPNO, START_EXPNO=START_EXPNO, OFF_MODE=OFF_MODE,
                INTENSITY_MODE=INTENSITY_MODE, FREQS=freqs, PROCESS_CMDS=PROCESS_CMDS)
    try:
        fh = open(os.path.join(run_dir, "settings.txt"), "w")
        try:
            fh.write("# settings of run %s, as used (written by fs_core.py)\n" % run_id)
            fh.write("# dataset: %s, %s\n" % (ds_root, ds_from))
            fh.write("# template: expno %d (%s), %s\n" % (TEMPLATE_EXPNO, tmpl_pulprog or "?", tmpl_from))
            fh.write("# expnos: %d..%d\n" % (START_EXPNO, planned_last))
            fh.write("# settings file: %s\n" % (source or "-"))
            for n, d in SETTINGS:
                fh.write("%s = %r\n" % (n, used[n]))
        finally:
            fh.close()
    except CATCH as ex:
        print("could not write settings.txt [%s]" % ex)
    if source:
        try:
            import shutil
            shutil.copyfile(source, os.path.join(run_dir, os.path.basename(source)))
        except CATCH as ex:
            print("could not copy %s into the run folder [%s]" % (source, ex))
    viewer_cmd = "%s %s %s" % (VIEWER_PYTHON, VIEWER_PATH, RUN_PATH)

    def run_file_write(text, mode='a'):
        """Write to run.txt. A failure is logged but does not stop the run."""
        try:
            fh = open(RUN_PATH, mode)
            try:
                fh.write(text)
            finally:
                fh.close()
        except CATCH as ex:
            log("Could not write run file %s [%s]" % (RUN_PATH, ex))

    def run_file_header():
        run_file_write(
            "# fs run file (read by fs_plot.py and fs_rephase.py)\n"
            "# run_id = %s\n"
            "# label = %s\n"
            "# sample = %s\n"
            "# conditions = %s\n"
            "# dataset_dir = %s\n"
            "# off_mode = %s\n"
            "# peak_ppm = %s\n"
            "# window_ppm = %s\n"
            "# mode = %s\n"
            "# power = %.2f\n"
            "# d1 = %s\n"
            "# repeats = %d\n"
            "# started = %s\n"
            "# columns: expno, kind, label, freq_GHz, ns, finished, set\n"
            % (run_id, RUN_LABEL, SAMPLE, MAS_INFO, ds_root, OFF_MODE, peak_str,
               repr(float(PEAK_WINDOW_PPM)), INTENSITY_MODE, POWER, D1, REPEATS, now_str()),
            'w')

    def run_file_row(expno, kind, label, freq, ns, t_fin, set_number):
        if freq is None:
            fstr = "-"
        else:
            fstr = "%.4f" % freq
        run_file_write("%d\t%s\t%s\t%s\t%d\t%s\t%d\n"
                       % (expno, kind, label, fstr, ns, now_str(t_fin), set_number))

    def clean(x):
        return str(x).replace("\t", " ").replace("\n", " ")

    def index_event(event, status):
        """One line in the common index. A failure is logged but does not stop the run."""
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or "?"
        line = "\t".join([now_str(), event, clean(status), run_id, RUN_LABEL, clean(SAMPLE),
                          ds_root, "%d-%d" % (START_EXPNO, planned_last), run_dir, user])
        try:
            new = (not os.path.exists(INDEX_PATH)) or os.path.getsize(INDEX_PATH) == 0
            fh = open(INDEX_PATH, 'a')
            try:
                if new:
                    fh.write("# time\tevent\tstatus\trun_id\tlabel\tsample\tdataset\texpnos"
                             "\trun_folder\tuser\n")
                fh.write(line + "\n")
            finally:
                fh.close()
        except CATCH as ex:
            log("Could not write to the run index %s [%s]" % (INDEX_PATH, ex))

    def re_abs(expno):
        XCMD("re %s %d 1 %s" % (DATA_NAME, expno, DATA_DIR),
             wait=WAIT_TILL_DONE)

    def set_title(expno, title):
        try:
            path = os.path.join(ds_root, str(expno), 'pdata', '1', 'title')
            tdir = os.path.dirname(path)
            if not os.path.exists(tdir):
                os.makedirs(tdir)
            fh = open(path, 'w')
            try:
                fh.write(title)
            finally:
                fh.close()
        except CATCH:
            pass

    def new_record(expno, ns, title):
        re_abs(TEMPLATE_EXPNO)
        XCMD("wrpa " + str(expno), wait=WAIT_TILL_DONE)
        re_abs(expno)
        XCMD("d1 " + str(D1))
        XCMD("ns " + str(ns))
        XCMD("ds " + str(DS))
        set_title(expno, title)

    def awg(cmdstr):
        """Send a command to the AWG, with retries. Returns True on success."""
        for attempt in range(1, AWG_RETRIES + 1):
            log("AWG -> '%s'%s" % (cmdstr, "" if attempt == 1 else "  (attempt %d)" % attempt))
            try:
                subprocess.check_call([AWG_PYTHON, AWG_CMD_PATH, cmdstr])
                return True
            except CATCH as ex:
                log("AWG command failed: '%s'  [%s]" % (cmdstr, ex))
                if attempt < AWG_RETRIES:
                    SLEEP(5)
        return False

    def audita_time(expno, threshold):
        """mtime of the expno's audita.txt if it is later than threshold, else None."""
        p = os.path.join(ds_root, str(expno), 'audita.txt')
        try:
            if os.path.exists(p):
                m = os.path.getmtime(p)
                if m > threshold:
                    return m
        except CATCH:
            pass
        return None

    def process(expno):
        """Run PROCESS_CMDS on the finished record. A failure is logged but does
        not stop the run."""
        if not PROCESS_CMDS:
            return
        try:
            re_abs(expno)
            for cmd in PROCESS_CMDS:
                XCMD(cmd, wait=WAIT_TILL_DONE)
            log("expno %d: processed (%s)" % (expno, "; ".join(PROCESS_CMDS)))
        except CATCH as ex:
            log("expno %d: processing failed (%s)  [%s]" % (expno, "; ".join(PROCESS_CMDS), ex))

    def acquire(expno, ns, label):
        """Start zg and return only once the acquisition has finished.
        Raises RunAbort if it has not finished MAX_EXTRA_WAIT s past the expected end."""
        lower    = (ns + DS) * D1                       # hard lower bound on the duration
        expected = (ns + DS) * (D1 + SCAN_OVERHEAD)
        t_zg = time.time()
        log("expno %d: zg  [%s, NS=%d, DS=%d, D1=%s s, expected ~%d s]"
            % (expno, label, ns, DS, D1, expected))
        XCMD("zg", wait=WAIT_TILL_DONE)
        t_ret = time.time()
        if t_zg + lower > t_ret:
            SLEEP(int(t_zg + lower - t_ret + 0.999))
        threshold = t_zg + lower
        deadline  = t_zg + expected + MAX_EXTRA_WAIT
        while True:
            t_fin = audita_time(expno, threshold)
            if t_fin is not None:
                log("expno %d: finished %d s after zg (expected ~%d s; zg returned after %d s)"
                    % (expno, int(round(t_fin - t_zg)), expected, int(round(t_ret - t_zg))))
                process(expno)
                if POST_ACQ_PAD > 0:
                    SLEEP(POST_ACQ_PAD)
                return t_fin
            if time.time() >= deadline:
                raise RunAbort(
                    "expno %d (%s) had not finished %d s after zg (expected ~%d s). "
                    "The acquisition itself was not halted; check its status in TopSpin"
                    % (expno, label, int(round(time.time() - t_zg)), expected))
            SLEEP(POLL_INTERVAL)

    def set_tag(set_number):
        return ("set %d | " % set_number) if REPEATS > 1 else ""

    def run_off(expno, set_number, label):
        if not awg('stop'):
            raise RunAbort("could not send 'stop' to the AWG before the %sOFF %s (expno %d)"
                           % (set_tag(set_number), label, expno))
        SLEEP(AWG_SETTLE)
        title = ("OFF (%s) | %s%s | %s | microwave off | D1 = %s s | %d scans"
                 % (label, set_tag(set_number), SAMPLE, MAS_INFO, D1, OFF_SCANS))
        new_record(expno, OFF_SCANS, title)
        return acquire(expno, OFF_SCANS, "%sOFF %s" % (set_tag(set_number), label))

    def run_on(expno, set_number, freq):
        """Returns the finish time if the point was acquired, None if the AWG
        could not be set (point skipped, expno left empty)."""
        cmdstr = 'cw %.3f %.2f' % (freq, POWER)
        if not awg(cmdstr):
            return None
        SLEEP(AWG_SETTLE)
        title = ("freq profile | %s%s | %s | %s | D1 = %s s | %d scan(s)"
                 % (set_tag(set_number), SAMPLE, MAS_INFO, cmdstr, D1, PROFILE_NS))
        new_record(expno, PROFILE_NS, title)
        return acquire(expno, PROFILE_NS, "%sON %.3f GHz" % (set_tag(set_number), freq))

    # ---- Viewer -------------------------------------------------------------------
    def launch_viewer():
        """Start fs_plot.py detached from TopSpin, with the Python variables of
        TopSpin's Jython removed from its environment. Output goes to viewer.log.
        Returns True if the start command was issued, False otherwise."""
        def q(x):
            return "'" + str(x).replace("'", "'\\''") + "'"
        shell_cmd = ("nohup env -u PYTHONPATH -u PYTHONHOME %s %s %s >> %s 2>&1 &"
                     % (q(VIEWER_PYTHON), q(VIEWER_PATH), q(RUN_PATH), q(VIEWER_LOG)))
        try:
            if not os.path.exists(VIEWER_PATH):
                raise IOError("%s not found" % VIEWER_PATH)
            subprocess.Popen(['/bin/sh', '-c', shell_cmd])
            log("Viewer started (output in %s)" % VIEWER_LOG)
            return True
        except CATCH as ex:
            log("Viewer could not be started [%s]" % ex)
            return False

    def ere_escape(s):
        """s as a literal string in a POSIX extended regular expression (for pgrep)."""
        special = '.[]()*+?{}|^$\\'
        return "".join([("\\" + ch) if ch in special else ch for ch in s])

    # A viewer for this run is any process whose command line contains the file
    # name of fs_plot.py followed by <run id>/run.txt; this also matches a viewer
    # opened by hand with an absolute path or a path relative to the dataset.
    viewer_pattern = (ere_escape(os.path.basename(VIEWER_PATH)) + ".*"
                      + ere_escape(run_id + "/run.txt"))
    viewer_state = {"respawn": bool(LAUNCH_VIEWER and RESPAWN_VIEWER)}

    def viewer_running():
        """True if a viewer for this run is running, False if none is,
        None if pgrep could not be run or reported an error."""
        try:
            p = subprocess.Popen(['pgrep', '-f', viewer_pattern],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p.communicate()
        except CATCH as ex:
            log("Could not check whether the viewer is running [%s]" % ex)
            return None
        if p.returncode == 0:
            return True
        if p.returncode == 1:
            return False
        log("Could not check whether the viewer is running [pgrep exit status %s]"
            % p.returncode)
        return None

    def respawn_viewer(expno):
        """Called after a record has been added to run.txt: start the viewer
        again if none is running. A failure is logged and ends the restarts for
        the rest of the run; it does not stop the run."""
        if not viewer_state["respawn"]:
            return
        try:
            running = viewer_running()
            if running is None:
                viewer_state["respawn"] = False
            elif not running:
                log("No viewer running after expno %d; starting it again" % expno)
                if not launch_viewer():
                    viewer_state["respawn"] = False
            if not viewer_state["respawn"]:
                log("The viewer will not be restarted during this run; reopen it with: %s"
                    % viewer_cmd)
        except CATCH as ex:
            viewer_state["respawn"] = False
            log("Viewer check failed [%s]; the viewer will not be restarted during this run"
                % ex)

    # ---- Main loop over the plan -------------------------------------------------
    log("=== %s start: %s / %s, %d set(s), OFF mode %s, %d ON points per set, "
        "expno %d..%d, estimated %s ===" % (RUN_LABEL, DATA_NAME, DATA_DIR, REPEATS, OFF_MODE,
                                            points_per_set, START_EXPNO, planned_last,
                                            fmt_hms(total_time)))
    log("Run folder: %s" % run_dir)
    run_file_header()
    index_event("start", "running")
    log("Viewer command: %s" % viewer_cmd)
    if LAUNCH_VIEWER:
        running = viewer_running()
        if running:
            log("A viewer for this run is already running; not starting another")
        else:
            if running is None:
                viewer_state["respawn"] = False
                log("The viewer will not be restarted during this run; reopen it with: %s"
                    % viewer_cmd)
            if not launch_viewer():
                viewer_state["respawn"] = False

    n_on_done = 0
    n_off_done = 0
    last_expno = None
    skipped = []
    consec_skips = 0
    abort_reason = None
    stop_ok = False
    plan_done = False

    try:
        for expno, set_number, kind, val in plan:
            if kind == "OFF":
                t_fin = run_off(expno, set_number, val)
                run_file_row(expno, "OFF", val, None, OFF_SCANS, t_fin, set_number)
                respawn_viewer(expno)
                n_off_done += 1
                last_expno = expno
            else:
                t_fin = run_on(expno, set_number, val)
                if t_fin is not None:
                    run_file_row(expno, "ON", "on", val, PROFILE_NS, t_fin, set_number)
                    respawn_viewer(expno)
                    n_on_done += 1
                    last_expno = expno
                    consec_skips = 0
                else:
                    skipped.append((set_number, val, expno))
                    consec_skips += 1
                    log("Skipped %s%.3f GHz (expno %d left empty)"
                        % (set_tag(set_number), val, expno))
                    if consec_skips >= MAX_CONSEC_SKIPS:
                        raise RunAbort("%d ON points in a row could not be set on the AWG "
                                       "(last: %.3f GHz)" % (consec_skips, val))
        plan_done = True
    except RunAbort as ex:
        abort_reason = str(ex)
    except CATCH as ex:
        abort_reason = "unexpected error: %s" % ex
    finally:
        # Also reached if the script is stopped from TopSpin, as far as the
        # interrupt allows; then neither handler above runs and plan_done is False.
        if abort_reason:
            log("STOPPED: %s" % abort_reason)
            status = "stopped: %s" % abort_reason.replace("\n", " ")
        elif plan_done:
            status = "complete"
        else:
            log("STOPPED: interrupted before the end of the plan (script stopped from TopSpin?)")
            status = "stopped: interrupted before the end of the plan"
        stop_ok = awg('stop')
        run_file_write("# end: %s\n" % status)
        index_event("end", status)
        if not abort_reason and not plan_done:
            log("=== interrupted; final 'stop' %s ===" % ("sent" if stop_ok else "FAILED"))

    done = ("%d ON and %d OFF records acquired, last at expno %s"
            % (n_on_done, n_off_done, last_expno))
    if skipped:
        done += "; skipped %d point(s), expno %s left empty" % (
            len(skipped), ", ".join([str(s[2]) for s in skipped]))
    log("=== %s end: %s; final 'stop' %s ===" % (RUN_LABEL, done, "sent" if stop_ok else "FAILED"))

    if abort_reason:
        ERRMSG("%s STOPPED: %s.\n\nmm-wave 'stop' %s.\nCompleted: %s.\nRun folder: %s"
               % (RUN_LABEL, abort_reason,
                  "sent" if stop_ok else "COULD NOT BE SENT - CHECK THE SOURCE",
                  done, run_dir))
    elif not stop_ok:
        ERRMSG("%s finished, but the final 'stop' could not be sent - CHECK THE SOURCE.\n"
               "%s.\nRun folder: %s" % (RUN_LABEL, done, run_dir))
    else:
        MSG("%s complete: %d set(s), OFF mode %s. %s. 'stop' sent to AWG.\nRun folder: %s\n"
            "Plot: %s" % (RUN_LABEL, REPEATS, OFF_MODE, done, run_dir, viewer_cmd))
