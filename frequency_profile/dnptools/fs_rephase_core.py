# -*- coding: utf-8 -*-
"""
fs_rephase_core.py  -  code of fs_rephase.py: apply the phase correction set
in fs_plot.py to the TopSpin data of one run (TopSpin / Jython)

Not run directly: the TopSpin script fs_rephase.py (in TopSpin's py/user
folder) runs
    execfile("/opt/dnptools/fs_rephase_core.py")
    run_rephase(RUN_FILE)

fs_plot.py corrects the phase only in the viewer; TopSpin's spectra are not
changed. This script reprocesses the records of one run with that phase.
Run it only when no acquisition script is running: it changes TopSpin's
current dataset with 're', which would disturb a running script.

Input: the run file <dataset>/fs_runs/<run id>/run.txt (RUN_FILE in
fs_rephase.py, or chosen in a file dialog) and phase.txt next to it, which
fs_plot.py writes when 'Apply to all records' is pressed (for a run file of the
earlier scripts, <run file without .txt>_phase.txt). The phase there is a correction on top of
the phase the records were processed with (PHC0 = base_phc0, PHC1 =
base_phc1); records processed with other values are skipped. The viewer's
baseline correction is not transferred; PROCESS_CMDS (default efp, absn) are
run as in the acquisition scripts.

fs_plot.py and TopSpin need not define the phase with the same sign or the
same reference point for the first-order term, so the script measures
TopSpin's convention on the first matching record instead of assuming it:
  1. It runs efp on that record with its original PHC0/PHC1, with PHC0 +
     CAL_STEP, and with PHC1 + CAL_STEP, and compares 1r + i*1i point by point
     (all points with a magnitude above 1e-4 of the largest). Changing PHC0
     must rotate every point by the same angle, and changing PHC1 by an angle
     linear in the point index; otherwise the script stops.
  2. From this it computes the PHC0/PHC1 that reproduce the viewer's phase,
     processes the record with them (efp), and checks that the result equals
     the viewer's phase applied to the original data to within VERIFY_TOL_DEG
     at every one of those points.
  3. After a second confirmation it sets PHC0/PHC1 and runs PROCESS_CMDS on
     every matching record, checking procs afterwards.
  4. When all records are done, it rewrites the phase file with the new values
     as the base and a zero correction, so that fs_plot.py shows the
     reprocessed spectra as they are.
If the calibration or the check fails, or the second dialog is cancelled, the
first record is processed again with its original PHC0/PHC1 and PROCESS_CMDS,
and nothing else is changed. If processing fails part way, the records done so
far keep the new phase and the phase file is left unchanged; fs_plot.py then
shows those records as processed and corrects only the others, and running
this script again continues with the others.

The expnos are looked for in the dataset that contains the fs_runs folder, so
a dataset moved or copied with its fs_runs folder is processed where it is now.
Every step is time-stamped in rephase.log in the run folder (for an older run
file, in <dataset>/fs_rephase_log.txt), and one line is appended to the common
index /opt/nmrdata/fs_runs.tsv when the TopSpin data have been changed.
"""
import os
import re
import time
import math
import struct

# TopSpin's Jython environment rebinds the name Exception, so the handlers in
# this script use CATCH: Python's own base class, taken from the builtins
# module, plus java.lang.Exception for errors raised on TopSpin's Java side.
try:
    import __builtin__ as _builtins
except ImportError:
    import builtins as _builtins
try:
    from java.lang import Exception as _JavaException
    CATCH = (_builtins.Exception, _JavaException)
except ImportError:
    CATCH = (_builtins.Exception,)


class RephaseAbort(_builtins.Exception):
    pass


def wrap180(x):
    return (x + 180.0) % 360.0 - 180.0


def wrap_pi(x):
    return (x + math.pi) % (2.0 * math.pi) - math.pi


def fmt_num(x):
    s = ("%.6f" % x).rstrip("0").rstrip(".")
    if s in ("", "-", "-0"):
        s = "0"
    return s


def read_params(path, keys):
    fh = open(path, "r")
    try:
        txt = fh.read()
    finally:
        fh.close()
    out = {}
    for k in keys:
        m = re.search(r"^##\$%s=\s*(\S+)" % re.escape(k), txt, re.M)
        if m:
            out[k] = m.group(1)
    return out


def read_run(path):
    """Returns (meta, rows, ended); rows are (expno, kind, label)."""
    meta, rows, ended = {}, [], None
    fh = open(path, "r")
    try:
        lines = fh.readlines()
    finally:
        fh.close()
    for line in lines:
        line = line.rstrip("\r\n")
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
            rows.append((int(parts[0]), parts[1], parts[2]))
        except ValueError:
            continue
    return meta, rows, ended


def read_phase(path):
    vals = {}
    fh = open(path, "r")
    try:
        for line in fh.readlines():
            line = line.split("#", 1)[0].strip()
            m = re.match(r"(\w+)\s*=\s*(\S+)$", line)
            if m:
                vals[m.group(1)] = m.group(2)
    finally:
        fh.close()

    def num(key, default):
        v = vals.get(key)
        if v is None or v.lower() == "none":
            return default
        return float(v)
    known = ("ph0", "ph1", "pivot_ppm", "base_phc0", "base_phc1", "baseline", "baseline_order")
    extra = [(k, vals[k]) for k in sorted(vals.keys()) if k not in known]
    return {"ph0": num("ph0", 0.0), "ph1": num("ph1", 0.0), "pivot": num("pivot_ppm", None),
            "base0": num("base_phc0", None), "base1": num("base_phc1", None),
            "baseline": int(num("baseline", 0)), "order": int(num("baseline_order", 3)),
            "extra": extra}


def write_phase(path, ph, comment):
    def v(x):
        if x is None:
            return "none"
        return repr(float(x))
    text = (
        "# phase settings, written by fs_rephase.py at %s\n"
        "# %s\n"
        "# fs_plot.py multiplies 1r + i*1i of every record processed with PHC0 = base_phc0\n"
        "# and PHC1 = base_phc1 by exp(i*phi), phi = ph0 + ph1*(k/SI - u_pivot) (deg),\n"
        "# k = 0 at OFFSET, u_pivot = (OFFSET - pivot_ppm)*SF/SW_p, and with baseline = 1\n"
        "# subtracts a polynomial of order baseline_order.\n"
        "ph0 = %s\nph1 = %s\npivot_ppm = %s\nbase_phc0 = %s\nbase_phc1 = %s\n"
        "baseline = %d\nbaseline_order = %d\n"
        % (time.strftime("%Y-%m-%d %H:%M:%S"), comment,
           v(ph["ph0"]), v(ph["ph1"]), v(ph["pivot"]), v(ph["base0"]), v(ph["base1"]),
           int(ph["baseline"]), int(ph["order"])))
    # the viewer's other settings (window, mode, magnitude) are kept as they were
    text += "".join(["%s = %s\n" % (k, x) for k, x in ph.get("extra", [])])
    fh = open(path, "w")
    try:
        fh.write(text)
    finally:
        fh.close()


INDEX_PATH = "/opt/nmrdata/fs_runs.tsv"
RUN_FILE_NAME = "run.txt"


def run_paths(run_path, meta):
    """(dataset folder, phase file, log file) for a run file; see the header."""
    if os.path.basename(run_path) == RUN_FILE_NAME:
        run_dir = os.path.dirname(os.path.abspath(run_path))
        ds_root = os.path.dirname(os.path.dirname(run_dir))
        if not os.path.isdir(ds_root):
            ds_root = meta.get("dataset_dir", "")
        return (ds_root, os.path.join(run_dir, "phase.txt"), os.path.join(run_dir, "rephase.log"))
    ds_root = meta.get("dataset_dir", "")
    if not os.path.isdir(ds_root):
        ds_root = os.path.dirname(os.path.abspath(run_path))
    base_name = run_path[:-4] if run_path.endswith(".txt") else run_path
    return (ds_root, base_name + "_phase.txt", os.path.join(ds_root, "fs_rephase_log.txt"))


def index_line(fields):
    """Appends one line to the common index; returns '' or an error text."""
    try:
        new = (not os.path.exists(INDEX_PATH)) or os.path.getsize(INDEX_PATH) == 0
        fh = open(INDEX_PATH, "a")
        try:
            if new:
                fh.write("# time\tevent\tstatus\trun_id\tlabel\tsample\tdataset\texpnos"
                         "\trun_folder\tuser\n")
            fh.write("\t".join([str(f).replace("\t", " ").replace("\n", " ") for f in fields]) + "\n")
        finally:
            fh.close()
        return ""
    except CATCH as ex:
        return str(ex)


def choose_file(start_dir):
    from javax.swing import JFileChooser
    from javax.swing.filechooser import FileNameExtensionFilter
    fc = JFileChooser(start_dir)
    fc.setDialogTitle("fs_rephase.py: choose the run file (fs_runs/<run id>/run.txt)")
    fc.setFileFilter(FileNameExtensionFilter("run files (run.txt)", "txt"))
    if fc.showOpenDialog(None) == JFileChooser.APPROVE_OPTION:
        return str(fc.getSelectedFile().getAbsolutePath())
    return None


def run_rephase(RUN_FILE=""):
    """RUN_FILE: full path of the run file; "" = choose it in a dialog."""
    # ======================= SETTINGS ====================================
    CHOOSER_DIR    = "/opt/nmrdata"    # where the file dialog starts
    PROCESS_CMDS   = ["efp", "absn"]   # as in the acquisition scripts; they must apply PHC0/PHC1
                                       # (efp, or ef and pk) and must not phase automatically (apk)
    CAL_STEP       = 30.0              # deg added to PHC0, then to PHC1, for the calibration
    VERIFY_TOL_DEG = 0.5               # largest deviation allowed in the check (deg)
    # ===================================================================

    # ---- Run file and phase file ----------------------------------------
    run_path = (RUN_FILE or "").strip()
    if not run_path:
        try:
            run_path = choose_file(CHOOSER_DIR)
        except CATCH as ex:
            ERRMSG("fs_rephase.py: could not show the file dialog (%s). Set RUN_FILE at the top "
                   "of the script." % ex)
            return
        if not run_path:
            MSG("fs_rephase.py: cancelled.")
            return
    if not os.path.isfile(run_path):
        ERRMSG("fs_rephase.py: run file not found: %s" % run_path)
        return
    meta, rows, ended = read_run(run_path)
    ds_root, phase_path, LOG_PATH = run_paths(run_path, meta)
    if not os.path.isdir(ds_root):
        ERRMSG("fs_rephase.py: the dataset of %s was not found." % run_path)
        return
    if not os.path.isfile(phase_path):
        ERRMSG("fs_rephase.py: no phase file %s.\nSet the phase in fs_plot.py and press "
               "'Apply to all records' first." % phase_path)
        return
    for c in PROCESS_CMDS:
        if c.strip().lower().startswith("apk"):
            ERRMSG("fs_rephase.py: PROCESS_CMDS contains '%s', which would replace the phase." % c)
            return

    DATA_DIR, DATA_NAME = os.path.dirname(ds_root), os.path.basename(ds_root)

    try:
        ph = read_phase(phase_path)
    except CATCH as ex:
        ERRMSG("fs_rephase.py: could not read %s (%s)" % (phase_path, ex))
        return
    if ph["ph0"] == 0.0 and ph["ph1"] == 0.0:
        MSG("fs_rephase.py: the phase file has no phase correction (PH0 = PH1 = 0); nothing to do.\n%s"
            % phase_path)
        return
    if ph["base0"] is None or ph["base1"] is None or ph["pivot"] is None:
        ERRMSG("fs_rephase.py: %s has no base_phc0/base_phc1/pivot_ppm." % phase_path)
        return

    # ---- Helpers ------------------------------------------------------
    def now_str():
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def log(msg):
        line = "[%s] %s" % (now_str(), msg)
        print(line)
        try:
            fh = open(LOG_PATH, "a")
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

    def pdir(expno):
        return os.path.join(ds_root, str(expno), "pdata", "1")

    def procs_of(expno):
        return read_params(os.path.join(pdir(expno), "procs"),
                           ["SI", "OFFSET", "SW_p", "SF", "BYTORDP", "DTYPP", "PHC0", "PHC1"])

    def re_abs(expno):
        XCMD("re %s %d 1 %s" % (DATA_NAME, expno, DATA_DIR), wait=WAIT_TILL_DONE)

    def set_phc(p0, p1):
        XCMD("phc0 " + fmt_num(p0))
        XCMD("phc1 " + fmt_num(p1))

    def check_phc(expno, p0, p1):
        p = procs_of(expno)
        got0, got1 = float(p.get("PHC0", "nan")), float(p.get("PHC1", "nan"))
        if not (abs(wrap180(got0 - p0)) < 0.0015 and abs(got1 - p1) < 0.0015):
            raise RephaseAbort("expno %d: after processing, procs has PHC0 = %s, PHC1 = %s instead of "
                               "%s, %s" % (expno, p.get("PHC0"), p.get("PHC1"), fmt_num(p0), fmt_num(p1)))
        return got0, got1

    def read_z(expno):
        """(re, im, procs) of the expno's 1r and 1i."""
        p = procs_of(expno)
        si = int(p["SI"])
        endian = ">" if int(p.get("BYTORDP", "0")) == 1 else "<"
        code, size = ("i", 4) if int(p.get("DTYPP", "0")) == 0 else ("d", 8)
        out = []
        for name in ("1r", "1i"):
            path = os.path.join(pdir(expno), name)
            if not os.path.exists(path):
                raise RephaseAbort("expno %d has no %s" % (expno, name))
            fh = open(path, "rb")
            try:
                data = fh.read(si * size)
            finally:
                fh.close()
            if len(data) != si * size:
                raise RephaseAbort("expno %d: %s is shorter than SI = %d points" % (expno, name, si))
            out.append(struct.unpack("%s%d%s" % (endian, si, code), data))
        return out[0], out[1], p

    def efp_and_read(expno, p0, p1):
        re_abs(expno)
        set_phc(p0, p1)
        XCMD("efp", wait=WAIT_TILL_DONE)
        check_phc(expno, p0, p1)
        return read_z(expno)

    def rotations(A, B):
        """Angle (rad) of B[k] * conj(A[k]) for every point used, and the points' u = k/SI."""
        ar, ai, br, bi = A[0], A[1], B[0], B[1]
        n = len(ar)
        m2 = 0.0
        for k in range(n):
            v = ar[k] * ar[k] + ai[k] * ai[k]
            if v > m2:
                m2 = v
        thr = m2 * 1e-8                       # |A| above 1e-4 of the largest
        us, angs, sr, sim = [], [], 0.0, 0.0
        for k in range(n):
            a2 = ar[k] * ar[k] + ai[k] * ai[k]
            if a2 <= thr:
                continue
            re_ = float(br[k]) * ar[k] + float(bi[k]) * ai[k]
            im_ = float(bi[k]) * ar[k] - float(br[k]) * ai[k]
            if re_ == 0.0 and im_ == 0.0:
                continue
            sr += re_ / math.sqrt(a2)
            sim += im_ / math.sqrt(a2)
            us.append(float(k) / n)
            angs.append(math.atan2(im_, re_))
        if len(angs) < 100:
            raise RephaseAbort("too few points with signal for the comparison (%d)" % len(angs))
        mean = math.atan2(sim, sr)
        angs = [mean + wrap_pi(x - mean) for x in angs]   # continuous around the mean
        return us, angs, mean

    def line_fit(us, angs):
        n = float(len(us))
        su, sa = sum(us), sum(angs)
        suu = sum([u * u for u in us])
        sua = sum([u * a for u, a in zip(us, angs)])
        den = n * suu - su * su
        b = (n * sua - su * sa) / den
        a = (sa - b * su) / n
        dev = max([abs(x - (a + b * u)) for u, x in zip(us, angs)])
        return a, b, dev

    def restore(expno, p0, p1):
        try:
            re_abs(expno)
            set_phc(p0, p1)
            for c in PROCESS_CMDS:
                XCMD(c, wait=WAIT_TILL_DONE)
            check_phc(expno, p0, p1)
            log("expno %d restored to PHC0 = %s, PHC1 = %s (%s)"
                % (expno, fmt_num(p0), fmt_num(p1), "; ".join(PROCESS_CMDS)))
            return "expno %d was processed again with its original PHC0/PHC1." % expno
        except CATCH as ex:
            log("expno %d could not be restored [%s]" % (expno, ex))
            return ("expno %d could NOT be restored to PHC0 = %s, PHC1 = %s (%s); process it by hand."
                    % (expno, fmt_num(p0), fmt_num(p1), ex))

    # ---- Records --------------------------------------------------------
    expnos = []
    for e, kind, label in rows:
        if e not in expnos:
            expnos.append(e)
    todo, skipped = [], []
    for e in expnos:
        try:
            p = procs_of(e)
            p0, p1 = float(p["PHC0"]), float(p["PHC1"])
        except CATCH:
            skipped.append((e, "no processed data"))
            continue
        if abs(wrap180(p0 - ph["base0"])) < 5e-4 and abs(p1 - ph["base1"]) < 5e-4:
            todo.append(e)
        else:
            skipped.append((e, "PHC0 %s, PHC1 %s" % (fmt_num(p0), fmt_num(p1))))
    if not todo:
        ERRMSG("fs_rephase.py: no record of %s was processed with PHC0 = %s, PHC1 = %s, the values "
               "the phase file is for. Nothing was changed."
               % (os.path.basename(run_path), fmt_num(ph["base0"]), fmt_num(ph["base1"])))
        return
    cal = todo[0]
    cal_p = procs_of(cal)
    b0, b1 = float(cal_p["PHC0"]), float(cal_p["PHC1"])

    if skipped:
        skip_line = "Skipped      : %d record(s) processed with other values (first: expno %d, %s)\n" % (
            len(skipped), skipped[0][0], skipped[0][1])
    else:
        skip_line = ""
    warn = ""
    if ended is None:
        warn = ("\nThe run file has no end line: the run may still be in progress.\n"
                "Continue only if no acquisition script is running.\n")
    summary = (
        "About to apply the viewer's phase to the TopSpin data (fs_rephase.py)\n\n"
        "Run file     : %s\n"
        "Dataset      : %s / %s\n"
        "Phase        : PH0 %+.2f, PH1 %+.2f deg, pivot %.3f ppm (fs_plot.py),\n"
        "               on top of PHC0 = %s, PHC1 = %s\n"
        "Records      : %d (expno %d..%d)\n"
        "%s"
        "Processing   : phc0/phc1, then %s\n%s\n"
        "First, expno %d is processed (efp) four times to measure TopSpin's phase\n"
        "convention and to check the result; you then confirm the new PHC0/PHC1.\n\n"
        "Click OK to continue, Cancel to abort."
        % (run_path, DATA_NAME, DATA_DIR, ph["ph0"], ph["ph1"], ph["pivot"],
           fmt_num(ph["base0"]), fmt_num(ph["base1"]), len(todo), todo[0], todo[-1],
           skip_line, "; ".join(PROCESS_CMDS), warn, cal))
    if not confirm_dialog(summary, "Confirm fs_rephase.py"):
        MSG("fs_rephase.py: cancelled before any change.")
        return

    log("=== fs_rephase.py start: %s, %d record(s), viewer PH0 %+.3f, PH1 %+.3f deg, pivot %.4f ppm, "
        "base PHC0 %s, PHC1 %s ===" % (run_path, len(todo), ph["ph0"], ph["ph1"], ph["pivot"],
                                       fmt_num(ph["base0"]), fmt_num(ph["base1"])))
    for e, why in skipped:
        log("expno %d skipped (%s)" % (e, why))

    # ---- Calibration on the first record --------------------------------
    try:
        A = efp_and_read(cal, b0, b1)
        B = efp_and_read(cal, b0 + CAL_STEP, b1)
        C = efp_and_read(cal, b0, b1 + CAL_STEP)

        us, angs, mean0 = rotations(A, B)
        dev0 = max([abs(x - mean0) for x in angs])
        c0 = math.degrees(mean0) / CAL_STEP
        log("calibration on expno %d: PHC0 %+g deg rotates the data by %+.4f deg (spread %.4f deg)"
            % (cal, CAL_STEP, math.degrees(mean0), math.degrees(dev0)))
        if abs(abs(c0) - 1.0) > 0.02 or math.degrees(dev0) > 0.1:
            raise RephaseAbort("changing PHC0 by %g deg did not rotate all points by +/-%g deg "
                               "(mean %+.3f deg, spread %.3f deg)"
                               % (CAL_STEP, CAL_STEP, math.degrees(mean0), math.degrees(dev0)))
        us, angs, mean1 = rotations(A, C)
        a1, s1, dev1 = line_fit(us, angs)
        alpha, beta = math.degrees(a1) / CAL_STEP, math.degrees(s1) / CAL_STEP
        log("calibration on expno %d: PHC1 %+g deg rotates the data by %+.4f %+.4f*u deg "
            "(u = k/SI; largest deviation from the line %.4f deg)"
            % (cal, CAL_STEP, math.degrees(a1), math.degrees(s1), math.degrees(dev1)))
        if abs(beta) < 0.1 or math.degrees(dev1) > 0.1:
            raise RephaseAbort("changing PHC1 by %g deg did not rotate the points linearly across "
                               "the spectrum (slope %+.3f deg, deviation %.3f deg)"
                               % (CAL_STEP, math.degrees(s1), math.degrees(dev1)))

        offset, sf, sw_p = float(A[2]["OFFSET"]), float(A[2]["SF"]), float(A[2]["SW_p"])
        u_piv = (offset - ph["pivot"]) * sf / sw_p
        P1 = ph["ph1"]
        P0 = ph["ph0"] - ph["ph1"] * u_piv          # viewer phase at u = 0
        d1 = P1 / beta
        d0 = (P0 - d1 * alpha) / c0
        new0 = float(fmt_num(wrap180(b0 + d0)))
        new1 = float(fmt_num(b1 + d1))
        log("new values: PHC0 %s -> %s, PHC1 %s -> %s"
            % (fmt_num(b0), fmt_num(new0), fmt_num(b1), fmt_num(new1)))

        D = efp_and_read(cal, new0, new1)
        us, angs, _ = rotations(A, D)
        dev = max([abs(wrap_pi(x - math.radians(P0 + P1 * u))) for u, x in zip(us, angs)])
        log("check on expno %d: largest deviation from the viewer's phase %.4f deg over %d points"
            % (cal, math.degrees(dev), len(us)))
        if math.degrees(dev) > VERIFY_TOL_DEG:
            raise RephaseAbort("processing expno %d with PHC0 = %s, PHC1 = %s differs from the viewer's "
                               "phase by up to %.2f deg (limit %.2f deg)"
                               % (cal, fmt_num(new0), fmt_num(new1), math.degrees(dev), VERIFY_TOL_DEG))
    except CATCH as ex:
        log("STOPPED during the calibration: %s" % ex)
        note = restore(cal, b0, b1)
        ERRMSG("fs_rephase.py STOPPED: %s.\n\n%s\nNo other record was changed.\nLog: %s"
               % (ex, note, LOG_PATH))
        return

    ok = confirm_dialog(
        "TopSpin's phase convention, measured on expno %d:\n"
        "  PHC0 + %g deg rotates the data by %+.2f deg\n"
        "  PHC1 + %g deg rotates them by %+.2f %+.2f*u deg (u = 0..1 across the spectrum)\n\n"
        "New values  : PHC0 %s -> %s,  PHC1 %s -> %s\n"
        "Check       : expno %d processed with them matches the viewer's phase\n"
        "              to within %.3f deg\n\n"
        "Click OK to process %d record(s) with these values (%s).\n"
        "Cancel processes expno %d again with its original values."
        % (cal, CAL_STEP, CAL_STEP * c0, CAL_STEP, CAL_STEP * alpha, CAL_STEP * beta,
           fmt_num(b0), fmt_num(new0), fmt_num(b1), fmt_num(new1), cal, math.degrees(dev),
           len(todo), "; ".join(PROCESS_CMDS), cal),
        "Confirm the new PHC0/PHC1")
    if not ok:
        log("cancelled after the calibration")
        note = restore(cal, b0, b1)
        MSG("fs_rephase.py: cancelled. %s No other record was changed." % note)
        return

    # ---- All records ----------------------------------------------------------
    done = []
    final = (new0, new1)
    try:
        for e in todo:
            re_abs(e)
            set_phc(new0, new1)
            for c in PROCESS_CMDS:
                XCMD(c, wait=WAIT_TILL_DONE)
            final = check_phc(e, new0, new1)
            done.append(e)
            log("expno %d: PHC0 %s, PHC1 %s; processed (%s)"
                % (e, fmt_num(new0), fmt_num(new1), "; ".join(PROCESS_CMDS)))
    except CATCH as ex:
        rest = [e for e in todo if e not in done]
        log("STOPPED at expno %d: %s" % (rest[0], ex))
        ERRMSG("fs_rephase.py STOPPED at expno %d: %s.\n\n%d record(s) were reprocessed with PHC0 = %s, "
               "PHC1 = %s; %d were not. The phase file was not changed, so fs_plot.py corrects only "
               "the records not yet reprocessed. Running fs_rephase.py again continues with them.\n"
               "Log: %s" % (rest[0], ex, len(done), fmt_num(new0), fmt_num(new1), len(rest), LOG_PATH))
        return

    new_ph = dict(ph)
    new_ph.update(ph0=0.0, ph1=0.0, base0=final[0], base1=final[1])
    comment = ("applied to %d record(s) in TopSpin: PHC0 %s -> %s, PHC1 %s -> %s (viewer PH0 %+.3f, "
               "PH1 %+.3f deg, pivot %.4f ppm)" % (len(done), fmt_num(b0), fmt_num(final[0]),
                                                   fmt_num(b1), fmt_num(final[1]),
                                                   ph["ph0"], ph["ph1"], ph["pivot"]))
    try:
        write_phase(phase_path, new_ph, comment)
        pf = "Phase file updated: fs_plot.py now shows these records as processed."
    except CATCH as ex:
        pf = ("The phase file could NOT be updated (%s). fs_plot.py still shows the reprocessed "
              "records correctly, because their PHC0/PHC1 no longer match the file, but it keeps "
              "listing the old correction; set PH0 = PH1 = 0 there and press 'Apply to all records'."
              % ex)
    log("=== fs_rephase.py end: %s; %s ===" % (comment, pf))
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "?"
    run_id = meta.get("run_id") or os.path.basename(run_path)
    err = index_line([time.strftime("%Y-%m-%d %H:%M:%S"), "rephase", comment, run_id,
                      meta.get("label", ""), meta.get("sample", ""), ds_root,
                      "%d-%d" % (todo[0], todo[-1]), os.path.dirname(os.path.abspath(run_path)), user])
    if err:
        log("Could not write to the run index %s [%s]" % (INDEX_PATH, err))
    MSG("fs_rephase.py: %d record(s) reprocessed with PHC0 = %s, PHC1 = %s (%s).\n%s%s\nLog: %s"
        % (len(done), fmt_num(final[0]), fmt_num(final[1]), "; ".join(PROCESS_CMDS),
           ("%d record(s) with other PHC0/PHC1 were skipped.\n" % len(skipped)) if skipped else "",
           pf, LOG_PATH))

