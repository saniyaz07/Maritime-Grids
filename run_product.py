#!/usr/bin/env python3
"""
run_product.py — Unified Maritime Grids Product Launcher
=========================================================
Starts the complete Maritime Grids Operator Decision Support Platform:
  1. Verifies physical models and runtime environment.
  2. Launches the FastAPI backend on http://127.0.0.1:8000 (or $PORT).
  3. Binds the NMEA 0183 UDP receiver to 127.0.0.1:10110 for Bridge Command.
  4. Serves the interactive Operator / Driver Dashboard at /dashboard.
  5. Enforces strict zero-actuator read-only safety boundary.

Usage:
  python run_product.py [--host 0.0.0.0] [--port 8000]
"""

import argparse
import os
import sys
import uvicorn

def main():
    default_port = int(os.environ.get("PORT", 8000))
    default_host = os.environ.get("HOST", "0.0.0.0")

    parser = argparse.ArgumentParser(
        description="Maritime Grids Clean-Energy Operator Decision Support Platform"
    )
    parser.add_argument("--host", default=default_host, help=f"HTTP host to bind (default: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"HTTP port to bind (default: {default_port})")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    print("\n" + "=" * 68)
    print(" [MARITIME GRIDS] CLEAN-ENERGY OPERATOR PLATFORM")
    print("=" * 68)
    print(f" [*] Backend API:       http://{args.host}:{args.port}")
    print(f" [*] Operator Dashboard: http://{args.host}:{args.port}/dashboard")
    print(f" [*] Swagger API Docs:   http://{args.host}:{args.port}/docs")
    print(f" [*] Virtual Simulator:  Active (Cockpit Controls & Signal Agent)")
    print(f" [*] NMEA 0183 Standby:  UDP 127.0.0.1:10110 (Bridge Command)")
    print(f" [*] Energy Estimator:   Active (Hydrodynamics & Powertrain)")
    print(f" [*] Advisory Engine:    Active (Deterministic Safety Rules)")
    print(f" [*] Safety Boundary:    READ-ONLY (0 Actuators, Port 10111 Disabled)")
    print("=" * 68)
    print(" Native Virtual Maritime Simulator:")
    print(f"   1. Open http://localhost:{args.port}/dashboard in your browser.")
    print("   2. Click 'START VOYAGE' to drive the virtual vessel.")
    print("   3. Adjust speed throttle, compass heading, and sea state presets.")
    print("   4. Signal Agent provides real-time decision-support alerts.")
    print("=" * 68 + "\n")

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)

if __name__ == "__main__":
    main()
