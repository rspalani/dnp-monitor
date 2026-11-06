# settings_p1.py  -  settings for fs.py: DNP frequency profile of a P1-diamond powder sample
#
# Run in TopSpin with:   fs p1
# Check the dataset, START_EXPNO and the template expno before each run; the
# confirmation dialog shows them in large type. settings_template.py explains
# every setting. UPPERCASE names are settings, lowercase names are helpers.

SAMPLE   = "Diamond P1 center"
MAS_INFO = "15 kHz MAS, 1.3 mm diamond(c-3-1) rotor, RT"

# Dataset and template expno. Values set here are used; leave DATA_DIR and
# DATA_NAME both "" to use the dataset open in TopSpin when the script starts,
# and TEMPLATE_EXPNO = None to use the expno open in TopSpin as the template.
DATA_DIR       = ""          # e.g. "/opt/nmrdata/rsh"
DATA_NAME      = ""          # e.g. "2610_4"
TEMPLATE_EXPNO = None        # e.g. 10

POWER = 0.4

START_EXPNO    = 300          # first new expno; all planned expnos must be free
REPEATS        = 1

# OFF reference position within each set: "start", "end", "both", or "none"
#   "start" : OFF -> ON points
#   "end"   : ON points -> OFF
#   "both"  : OFF -> ON points -> OFF
#   "none"  : ON points only
OFF_MODE = "both"

# Frequencies (GHz), in acquisition order
freqs1 = frange(525.90, 525.94, 0.01)
freqs2 = frange(525.95, 526.05, 0.002)
freqs3 = frange(526.06, 526.13, 0.01)
freqs4 = frange(526.14, 526.23, 0.002)
freqs5 = frange(526.24, 526.30, 0.01)
FREQS  = freqs1 + freqs2 + freqs3 + freqs4 + freqs5

D1         = 300
DS         = 0         # dummy scans, set on every record
PROFILE_NS = 1
OFF_SCANS  = 16

AWG_SETTLE = 2         # s after each AWG command, before the record is set up

# Record timing (see settings_template.py)
SCAN_OVERHEAD  = 5     # s per scan beyond D1 (saturation block, pulses, acquisition);
                       # sets the expected duration used for the estimate and the deadline
POLL_INTERVAL  = 5     # s between completion checks
MAX_EXTRA_WAIT = 300   # s past the expected end before the run is stopped
POST_ACQ_PAD   = 5     # s after completion, before the next AWG command
EST_OVERHEAD   = 5     # s per record for re/wrpa/parameters and zg start-up
                       # (used only for the time estimate)

AWG_RETRIES      = 3   # attempts per AWG command, 5 s apart
MAX_CONSEC_SKIPS = 3   # ON points skipped in a row (failed 'cw') before the run is stopped

# TopSpin commands run on each record once its acquisition has finished,
# before the next AWG command. Set to [] for no processing.
PROCESS_CMDS = ["efp", "absn"]

# Live plot: intensity of each record, read by fs_plot.py from pdata/1/1r
PEAK_PPM        = 26.0       # centre of the intensity window (ppm); None = whole spectrum
PEAK_WINDOW_PPM = 10.0       # full width of the window (ppm)
INTENSITY_MODE  = "extreme"  # "extreme": largest |value| in the window, sign kept
                             # "max"    : largest value (for magnitude spectra, 'mc')
                             # "sum"    : sum of the points in the window
LAUNCH_VIEWER   = True       # start fs_plot.py in the background when the run starts
RESPAWN_VIEWER  = True       # after each record, start it again if no viewer for this
                             # run is running (e.g. its window was closed)
