# -*- coding: utf-8 -*-
"""
fs_rephase.py  -  apply the phase correction set in fs_plot.py to the TopSpin
data of one run (TopSpin / Jython)

Run it in TopSpin after the acquisition has finished, never while an
acquisition script is running. It asks for the run file
(<dataset>/fs_runs/<run id>/run.txt) unless RUN_FILE is set below. The code is
in /opt/dnptools/fs_rephase_core.py; its header describes what is done.
"""
FS_REPHASE = "/opt/dnptools/fs_rephase_core.py"
RUN_FILE = ""      # full path of run.txt; "" = choose it in a dialog

if __name__ == "__main__":
    execfile(FS_REPHASE)
    run_rephase(RUN_FILE)
