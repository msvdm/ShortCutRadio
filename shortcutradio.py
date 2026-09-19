#!/usr/bin/env python3
"""ShortCutRadio -- a discreet radio and music player with an in-game overlay.

    shortcutradio.py            start (opens the setup window)
    shortcutradio.py --hidden   start straight to the tray
"""

import sys

from src.app import main

if __name__ == "__main__":
    sys.exit(main())
