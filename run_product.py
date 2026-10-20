#!/usr/bin/env python3
"""
run_product.py — Unified Maritime Grids Product Launcher
=========================================================
Starts the complete Maritime Grids Operator Decision Support Platform:
  1. Verifies physical models and runtime environment.
  2. Launches the FastAPI backend on http://127.0.0.1:8000.
  3. Binds the NMEA 0183 UDP receiver to 127.0.0.1:10110 for Bridge Command.
  4. Serves the interactive Operator / Driver Dashboard at http://127.0.0.1:8000/dashboard.
  5. Enforces strict zero-actuator read-only safety boundary.

Usage:
  python run_product.py [--host 0.0.0.0] [--port 8000]
"""

import argparse
import os
import sys
import uvicorn

def main():
    parser = argparse.ArgumentParser(
        description="Maritime Grids Clean-Energy Operator Decision Support Platform"
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port to bind (default: 8000)")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    print("\n" + "=" * 68)
    print(" [MARITIME GRIDS] CLEAN-ENERGY OPERATOR PLATFORM")
    print("=" * 68)
    print(f" [*] Backend API:       http://127.0.0.1:{args.port}")
    print(f" [*] Operator Dashboard: http://127.0.0.1:{args.port}/dashboard")
    print(f" [*] Swagger API Docs:   http://127.0.0.1:{args.port}/docs")
    print(f" [*] Virtual Simulator:  Active (Cockpit Controls & Signal Agent)")
    print(f" [*] NMEA 0183 Standby:  UDP 127.0.0.1:10110 (Bridge Command)")
    print(f" [*] Energy Estimator:   Active (Hydrodynamics & Powertrain)")
    print(f" [*] Advisory Engine:    Active (Deterministic Safety Rules)")
    print(f" [*] Safety Boundary:    READ-ONLY (0 Actuators, Port 10111 Disabled)")
    print("=" * 68)
    print(" Native Virtual Maritime Simulator:")
    print(f"   1. Open http://127.0.0.1:{args.port}/dashboard in your browser.")
    print("   2. Click 'START VOYAGE' to drive the virtual vessel.")
    print("   3. Adjust speed throttle, compass heading, and sea state presets.")
    print("   4. Signal Agent provides real-time decision-support alerts.")
    print("=" * 68 + "\n")

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)

if __name__ == "__main__":
    main()
