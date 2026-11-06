# decay_template.py  -  template for the settings files of decay.py (DNP decay)
#
# To set up a new kind of decay, copy this file in the same folder:
#     cp /opt/nmrdata/fs_settings/decay_template.py /opt/nmrdata/fs_settings/decay_<name>.py
# fill in the values, and run it from TopSpin's command line with
#     decay <name>
# ('decay' alone lists the decay settings files to choose from). This template itself
# is not run.
#
# A decay run follows the enhanced polarization after the microwaves are switched off:
#   1. 'cw FREQ POWER' is sent to the AWG, and the sample polarizes for POLARIZE_TIME s
#      (about 5 times the build-up time reaches the steady state);
#   2. a reference record is acquired with the microwaves still on (the state at t = 0);
#   3. 'stop' is sent to the AWG: t = 0;
#   4. one record is acquired at each time in TIMES_LIST after t = 0: its D1 is set
#      so that its pulse comes at that time, and the time actually reached is written
#      to run.txt.
# Every record has NS 1 and DS 0. The template's pulse program must NOT saturate, and
# its pulse should be a small flip angle (e.g. 5 degrees), so that each record uses
# only a small part of the polarization (cos(flip angle) remains after each pulse; the
# viewer corrects for it with FLIP_DEG). Set RG in the template for the reference,
# the largest signal of the run.
#
# Timing: each record needs some seconds besides D1 (setting up, starting zg,
# processing); targets closer together than that are taken as soon as possible, and
# their actual times are recorded. Times are accurate to about a second, so decays
# of a minute or longer are followed well; faster decays need a pseudo-2D pulse
# program instead.
#
# The file is Python: plain assignments, with logspace(first, last, n) and
# frange(start, stop, step) available. UPPERCASE names are settings; an UPPERCASE
# name that is not a known setting stops the run before anything starts. Settings
# left out take the defaults in /opt/dnptools/fs_core.py (DECAY_SETTINGS).
#
# Each run is recorded as a frequency profile is, in
# <dataset>/fs_runs/<start time>_<RUN_LABEL>_e<START_EXPNO>/, and listed in
# /opt/nmrdata/fs_runs.tsv; the viewer plots the intensity against the time after
# the microwaves went off and fits the decay.

# Short name used in the run folder name and the index. Leave it out to use
# decay_<name> from the file name decay_<name>.py.
#RUN_LABEL = "decay_name"

SAMPLE   = "sample description"          # shown in the dialog, the titles and the plot
MAS_INFO = "MAS rate, rotor, temperature"

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
POLARIZE_TIME = 600          # s, about 5 times the build-up time T_B

# Times of the decay records, in s after the microwaves go off, increasing.
# logspace(first, last, n) gives n values evenly spaced on a log scale; out to about
# 3 times T1 lets the viewer fit the equilibrium level as well.
TIMES_LIST = logspace(10, 600, 12)

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
PEAK_PPM        = 0          # centre of the intensity window (ppm); None = whole spectrum
PEAK_WINDOW_PPM = 20.0       # full width of the window (ppm)
INTENSITY_MODE  = "extreme"  # "extreme", "max" or "sum" (for weak signals: "sum")
LAUNCH_VIEWER   = True
RESPAWN_VIEWER  = True
