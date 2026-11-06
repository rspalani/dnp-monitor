# -*- coding: utf-8 -*-
from __future__ import print_function

import datetime
import socket
import sys

# Address of the AWG control server. The repository keeps a placeholder (192.0.2.x is
# reserved for examples); set the real address on the spectrometer.
HOST = '192.0.2.40'
PORT = 1234
COMMAND = "stop"
TIMEOUT = 10.0                               # s, for connect and send
LOG_FILE = '/opt/nmrdata/rsh/awg_cmd.log'    # set to None to disable file logging


def stamp():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


def report(msg):
    line = "[%s] %s" % (stamp(), msg)
    print(line)
    sys.stdout.flush()
    if LOG_FILE:
        try:
            with open(LOG_FILE, 'a') as fh:
                fh.write(line + "\n")
        except (IOError, OSError):
            pass


def send_command(host, port, command):
    """Send one newline-terminated command. Returns True on success."""
    try:
        s = socket.create_connection((host, port), TIMEOUT)
    except (socket.error, socket.timeout) as msg:
        report("Error connecting to server %s:%d: %s" % (host, port, msg))
        return False

    try:
        s.settimeout(TIMEOUT)
        report("Sending command: '%s' to %s:%d" % (command, host, port))
        s.sendall((command + "\n").encode('ascii'))
        return True
    except (socket.error, socket.timeout) as msg:
        report("Error sending '%s': %s" % (command, msg))
        return False
    finally:
        s.close()
        report("Connection closed.")


if __name__ == "__main__":
    cmd = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else COMMAND
    ok = send_command(HOST, PORT, cmd)
    # Non-zero exit on failure so subprocess.check_call() in the TopSpin
    # scripts raises CalledProcessError instead of failing silently.
    sys.exit(0 if ok else 1)
