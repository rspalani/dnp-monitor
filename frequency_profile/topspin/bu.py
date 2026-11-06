# -*- coding: utf-8 -*-
"""
bu.py  -  DNP build-up (intensity against the build-up time D1) with a live plot,
from a settings file (TopSpin / Jython)

On TopSpin's command line:
    bu p1            run /opt/nmrdata/fs_settings/buildup_p1.py
    bu buildup_p1    the same
    bu               choose the settings file from a list
New settings files are made by copying buildup_template.py in
/opt/nmrdata/fs_settings. The code is in /opt/dnptools/fs_core.py, shared with
fs.py; its header describes the run, the timing, and the files written.
"""
import sys

FS_CORE = "/opt/dnptools/fs_core.py"

if __name__ == "__main__":
    execfile(FS_CORE)
    run_buildup_settings(sys.argv[1:])
