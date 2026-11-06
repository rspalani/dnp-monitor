# decay_p1.py  -  settings for decay.py: decay of the DNP-enhanced polarization of a
# P1-diamond powder sample at 100 K after the microwaves are switched off
#
# Run in TopSpin with:   decay p1
# Set FREQ (below) to the frequency to polarize at, and check the dataset,
# START_EXPNO and the template expno before each run; the confirmation dialog shows
# them in large type. The template: no saturation, a 5 degree pulse, and an RG low
# enough for the fully polarized signal, the reference record. RG 64 was safe for the
# 90 degree build-up at 100 K; a 5 degree pulse gives about sin(5)/sin(90) = 0.09 of
# that signal, so a higher RG may be possible (check the first reference for an ADC
# overflow message). About 5.5 h in all. decay_template.py explains every setting.

# Short name used in the run folder name and the index. Leave it out to use
# decay_<name> from the file name decay_<name>.py.
#RUN_LABEL = "decay_name"

SAMPLE   = "Diamond P1 center"
MAS_INFO = "13 kHz MAS, 1.3 mm Zirconia rotor, 100 K"

# Dataset and template expno, as for profiles and build-ups: leave DATA_DIR and
# DATA_NAME both "" to use the dataset open in TopSpin, and TEMPLATE_EXPNO = None to
# use the expno open in TopSpin as the template.
DATA_DIR       = ""          # e.g. "/opt/nmrdata/rsh"
DATA_NAME      = ""          # e.g. "2610_4"
TEMPLATE_EXPNO = None        # e.g. 10

START_EXPNO = 900            # first new expno; all planned expnos must be free
REPEATS     = 1              # polarize-and-decay cycles, one after the other

# Polarization: the AWG's 'cw' command, and the time from it to the reference pulse
FREQ          = None         # GHz, e.g. the frequency of the largest enhancement in the profile
POWER         = 0.4          # second argument of the AWG 'cw' command
POLARIZE_TIME = 10800        # s: 3 h, about 5 times T_B (30-40 min at 100 K)

# Times of the decay records, in s after the microwaves go off, increasing.
# logspace(first, last, n) gives n values evenly spaced on a log scale; out to about
# 3 times T1 lets the viewer fit the equilibrium level as well. With T1 expected near
# T_B (30-40 min), 30 s to 9000 s (2.5 h); 16 pulses of 5 degrees leave cos(5)^16 = 0.94
# of the polarization, which the viewer corrects for.
TIMES_LIST = logspace(30, 9000, 15)

FLIP_DEG = 5.0               # flip angle of the template's pulse, in degrees: the viewer
                             # corrects each record for the polarization the pulses before
                             # it used (it can be changed in the viewer)

# Timing (normally left as they are)
ZG_LATENCY     = 3.0   # s from setting D1 to the pulse, besides D1: the first guess;
                       # afterwards the median measured on the records so far is used
MIN_D1         = 0.5   # s; a target that comes sooner than this allows is taken late
AWG_SETTLE     = 2     # s after each AWG command
POLL_INTERVAL  = 1     # s between completion checks
MAX_EXTRA_WAIT = 300   # s past the expected end of a record before the run is stopped
POST_ACQ_PAD   = 0     # s after a record, before the next one is set up
EST_OVERHEAD   = 5     # s per record for re/wrpa/parameters and zg start-up (estimate only)
SCAN_OVERHEAD  = 5     # s per scan besides D1 (estimate and deadline only)
AWG_RETRIES    = 3     # attempts per AWG command, 5 s apart

# TopSpin commands run on each record once its acquisition has finished
PROCESS_CMDS = ["efp", "absn"]

# Live plot: intensity of each record, read by fs_plot.py from pdata/1/1r
PEAK_PPM        = 26.0       # centre of the intensity window (ppm); None = whole spectrum
PEAK_WINDOW_PPM = 10.0       # full width of the window (ppm)
INTENSITY_MODE  = "extreme"  # "extreme", "max" or "sum" (for weak signals: "sum")
LAUNCH_VIEWER   = True
RESPAWN_VIEWER  = True
