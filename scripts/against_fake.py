#!/usr/bin/env python3
"""Run the real CLI with the Trading 212 hosts pointed at scripts/fake_t212.py.

    python3 scripts/against_fake.py <port> plan --picks picks.example.json
"""
import sys

import autopilot.config as config

port = sys.argv.pop(1)
config.DEMO_BASE = config.LIVE_BASE = f"http://127.0.0.1:{port}/api/v0"
sys.argv[0] = "autopilot"

from autopilot.cli import main  # noqa: E402

main()
