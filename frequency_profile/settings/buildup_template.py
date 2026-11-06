# buildup_template.py  -  template for the settings files of bu.py (DNP build-up)
#
# To set up a new kind of build-up, copy this file in the same folder:
#     cp /opt/nmrdata/fs_settings/buildup_template.py /opt/nmrdata/fs_settings/buildup_<name>.py
# fill in the values, and run it from TopSpin's command line with
#     bu <name>
# ('bu' alone lists the build-up settings files to choose from). This template
# itself is not run.
#
# A build-up run acquires one record per build-up time D1, at one mm-wave
# frequency or with the microwaves off. The template's pulse program must
# saturate before D1, so that every scan starts from zero polarization and D1
# is the build-up time.
#
# The file is Python: plain assignments, with logspace(first, last, n),
# ns_for_time(...) and frange(start, stop, step) available. UPPERCASE names are
# settings; an UPPERCASE name that is not a known setting stops the run before
# anything starts, so typos are caught. Use lowercase names for your own helper
# variables. Settings left out take the defaults listed in
# /opt/dnptools/fs_core.py (BU_SETTINGS).
#
# Each run is recorded as a frequency profile is, in
# <dataset>/fs_runs/<start time>_<RUN_LABEL>_e<START_EXPNO>/ (run.txt, log.txt,
# a copy of this file, settings.txt with every value as used, and the viewer's
# files), and listed in /opt/nmrdata/fs_runs.tsv. The viewer plots the
# intensity against D1 and fits the build-up.

# Short name used in the run folder name and the index. Leave it out to use
# bu_<name> from the file name buildup_<name>.py.
#RUN_LABEL = "bu_name"

SAMPLE   = "sample description"          # shown in the dialog, the titles and the plot
MAS_INFO = "MAS rate, rotor, temperature"

# Dataset and template expno. Values set here are used; leave DATA_DIR and
# DATA_NAME both "" to use the dataset open in TopSpin when the script starts,
# and TEMPLATE_EXPNO = None to use the expno open in TopSpin as the template
# (it must belong to that dataset). Every record is created from the template
# with wrpa; D1, NS and DS are then set for each record.
DATA_DIR       = ""          # e.g. "/opt/nmrdata/rsh"
DATA_NAME      = ""          # e.g. "2610_4"
TEMPLATE_EXPNO = None        # e.g. 10

START_EXPNO = 600            # first new expno; all planned expnos must be free
REPEATS     = 1              # sets; each set repeats the whole series in its own expnos

# The records of each set:
#   "on"          : ON at each D1 (microwaves at FREQ)
#   "off"         : OFF at each D1 (microwaves off)
#   "interleaved" : ON and OFF at each D1, back to back (ON first); only where
#                   the OFF signal can be measured at every D1
#   "on_then_off" : all ON records, then all OFF records
#   "off_then_on" : all OFF records, then all ON records
SERIES = "on"

# mm-wave for the ON records: 'cw FREQ POWER' is sent to the AWG before each ON
# record, 'stop' before each OFF record. FREQ and POWER are not needed for
# SERIES = "off".
FREQ  = None                 # GHz, e.g. the frequency of the largest enhancement in the profile
POWER = 0.4                  # second argument of the AWG 'cw' command

SCAN_OVERHEAD = 5            # s per scan beyond D1 (saturation block, pulses, acquisition);
                             # used for the time estimate, the deadline, and ns_for_time below

# Build-up times D1 (s), acquired in the order written. logspace(first, last, n)
# gives n values evenly spaced on a log scale (rounded to 3 significant digits);
# a list can also be written out, e.g. [1, 2, 4, 8, 16, 32, 64, 128].
# About 0.05 to 5 times the expected T_B covers the curve and its plateau.
D1_LIST = logspace(1, 150, 12)

# Scans per ON record: one number for all records, or a list with one per D1.
# ns_for_time(D1_LIST, seconds, ns_min, ns_max, multiple, overhead) gives records
# of about `seconds` each: NS = seconds / (D1 + overhead), at most ns_max, rounded
# down to a multiple of `multiple` (the phase cycle), and at least ns_min (by
# default `multiple`). That is, more scans at short D1, where the signal is small.
NS_LIST     = ns_for_time(D1_LIST, 120, ns_max=32, multiple=4, overhead=SCAN_OVERHEAD)
OFF_NS_LIST = None           # scans per OFF record, in the same way; None = NS_LIST
DS          = 0              # dummy scans, set on every record (with saturation, 0 is enough)

AWG_SETTLE = 2         # s after each AWG command, before the record is set up

# Record timing, as for frequency profiles: after zg the script waits (NS+DS)*D1,
# then checks every POLL_INTERVAL s for audita.txt; the record is accepted
# whenever audita.txt appears before (NS+DS)*(D1+SCAN_OVERHEAD) + MAX_EXTRA_WAIT s
# after zg, and otherwise the run is stopped (mm-wave 'stop', error box).
POLL_INTERVAL  = 5     # s between completion checks
MAX_EXTRA_WAIT = 300   # s past the expected end before the run is stopped
POST_ACQ_PAD   = 2     # s after completion, before the next AWG command
EST_OVERHEAD   = 3     # s per record for re/wrpa/parameters and zg start-up
                       # (used only for the time estimate)

AWG_RETRIES      = 3   # attempts per AWG command, 5 s apart
MAX_CONSEC_SKIPS = 3   # ON records skipped in a row (failed 'cw') before the run is stopped

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
