# settings_template.py  -  template for the settings files of fs.py
#
# To set up a new kind of experiment, copy this file in the same folder:
#     cp /opt/nmrdata/fs_settings/settings_template.py /opt/nmrdata/fs_settings/settings_<name>.py
# fill in the values, and run it from TopSpin's command line with
#     fs <name>
# ('fs' alone lists the settings files to choose from). This template itself is
# not run.
#
# The file is Python: plain assignments, with frange(start, stop, step)
# available for evenly spaced values (both ends included). UPPERCASE names are
# settings; an UPPERCASE name that is not a known setting stops the run before
# anything starts, so typos are caught. Use lowercase names for your own helper
# variables, such as frequency segments. Settings left out take the defaults
# listed in /opt/dnptools/fs_core.py (SETTINGS).
#
# Each run is recorded in <dataset>/fs_runs/<start time>_<RUN_LABEL>_e<START_EXPNO>/
# (run.txt, log.txt, a copy of this file, settings.txt with every value as used,
# and the viewer's files) and listed in /opt/nmrdata/fs_runs.tsv.

# Short name used in the run folder name and the index. Leave it out to use
# <name> from the file name settings_<name>.py.
#RUN_LABEL = "name"

SAMPLE   = "sample description"          # shown in the dialog, the titles and the plot
MAS_INFO = "MAS rate, rotor, temperature"

# Dataset and template expno. Values set here are used; leave DATA_DIR and
# DATA_NAME both "" to use the dataset open in TopSpin when the script starts,
# and TEMPLATE_EXPNO = None to use the expno open in TopSpin as the template
# (it must belong to that dataset). Every record is created from the template
# with wrpa; D1, NS and DS are then set as below.
DATA_DIR       = ""          # e.g. "/opt/nmrdata/rsh"
DATA_NAME      = ""          # e.g. "2610_4"
TEMPLATE_EXPNO = None        # e.g. 10

POWER = 0.4                  # second argument of the AWG 'cw' command

START_EXPNO    = 500         # first new expno; all planned expnos must be free
REPEATS        = 1           # sets; each set occupies its own block of expnos

# OFF reference position within each set: "start", "end", "both", or "none"
#   "start" : OFF -> ON points
#   "end"   : ON points -> OFF
#   "both"  : OFF -> ON points -> OFF
#   "none"  : ON points only
OFF_MODE = "both"

# Frequencies (GHz), in acquisition order. For example, finer steps around a
# feature:
#   seg1 = frange(525.90, 526.00, 0.010)
#   seg2 = frange(526.002, 526.10, 0.002)
#   FREQS = seg1 + seg2
FREQS = frange(525.950, 526.550, 0.020)

D1         = 20        # s, set on every record
DS         = 0         # dummy scans, set on every record
PROFILE_NS = 4         # scans per ON record
OFF_SCANS  = 16        # scans per OFF record

AWG_SETTLE = 2         # s after each AWG command, before the record is set up

# Record timing. XCMD("zg") returns before the acquisition has finished, so
# each record is timed: after zg the script waits (NS+DS)*D1, then checks every
# POLL_INTERVAL s for audita.txt; the record is accepted whenever audita.txt
# appears before (NS+DS)*(D1+SCAN_OVERHEAD) + MAX_EXTRA_WAIT s after zg, and
# otherwise the run is stopped (mm-wave 'stop', error box).
SCAN_OVERHEAD  = 5     # s per scan beyond D1 (saturation block, pulses, acquisition);
                       # sets the expected duration used for the estimate and the deadline
POLL_INTERVAL  = 2     # s between completion checks
MAX_EXTRA_WAIT = 120   # s past the expected end before the run is stopped
POST_ACQ_PAD   = 2     # s after completion, before the next AWG command
EST_OVERHEAD   = 3     # s per record for re/wrpa/parameters and zg start-up
                       # (used only for the time estimate)

AWG_RETRIES      = 3   # attempts per AWG command, 5 s apart
MAX_CONSEC_SKIPS = 3   # ON points skipped in a row (failed 'cw') before the run is stopped

# TopSpin commands run on each record once its acquisition has finished,
# before the next AWG command. Set to [] for no processing.
PROCESS_CMDS = ["efp", "absn"]

# Live plot: intensity of each record, read by fs_plot.py from pdata/1/1r
PEAK_PPM        = 0          # centre of the intensity window (ppm); None = whole spectrum
PEAK_WINDOW_PPM = 20.0       # full width of the window (ppm)
INTENSITY_MODE  = "extreme"  # "extreme": largest |value| in the window, sign kept
                             # "max"    : largest value (for magnitude spectra, 'mc')
                             # "sum"    : sum of the points in the window
LAUNCH_VIEWER   = True       # start fs_plot.py in the background when the run starts
RESPAWN_VIEWER  = True       # after each record, start it again if no viewer for this
                             # run is running (e.g. its window was closed)
