#!/usr/bin/env python3
"""ShortCutRadio -- a discreet radio and music player with an in-game overlay.

    shortcutradio.py            start (opens the setup window)
    shortcutradio.py --hidden   start straight to the tray
    shortcutradio.py --version  print the version and exit (starts nothing)
    shortcutradio.py --quit     close the copy running on this config, if any
"""

import sys

if __name__ == "__main__":
    if "--version" in sys.argv[1:]:
        # Before Qt is imported: this is how a build is checked for life.
        from src import __version__
        print(f"ShortCutRadio {__version__}")
        sys.exit(0)

    from src.app import main
    sys.exit(main())
