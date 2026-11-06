# -*- coding: utf-8 -*-
"""
fs.py  -  DNP frequency profile with a live plot, from a settings file
(TopSpin / Jython)

On TopSpin's command line:
    fs bdpa            run /opt/nmrdata/fs_settings/settings_bdpa.py
    fs settings_bdpa   the same
    fs                 choose the settings file from a list
New settings files are made by copying settings_template.py in
/opt/nmrdata/fs_settings. The code is in /opt/dnptools/fs_core.py; its header
describes the run, the timing, and the files written.
"""
import sys

FS_CORE = "/opt/dnptools/fs_core.py"

if __name__ == "__main__":
    execfile(FS_CORE)
    run_settings(sys.argv[1:])
