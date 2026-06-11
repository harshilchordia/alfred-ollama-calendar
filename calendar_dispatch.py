#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dispatcher that launches calendar_nlp.py in the background.
Alfred calls this script (returns immediately), so the Alfred window closes instantly.
The background process handles Ollama parsing + event creation and sends a macOS notification.
"""

import sys
import os
import subprocess


def main():
    if len(sys.argv) < 2:
        return

    user_input = " ".join(sys.argv[1:])
    script_dir = os.path.dirname(os.path.abspath(__file__))
    worker = os.path.join(script_dir, "calendar_worker.py")

    # Spawn the worker as a fully detached background process
    subprocess.Popen(
        [sys.executable, worker, user_input],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=script_dir
    )


if __name__ == "__main__":
    main()
