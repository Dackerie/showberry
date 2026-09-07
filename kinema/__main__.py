#!/usr/bin/env python3
"""Run Showberry application."""

import sys
import os

# Add parent directory to path for development
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kinema.main import main

if __name__ == '__main__':
    sys.exit(main())
