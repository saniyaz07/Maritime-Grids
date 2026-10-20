"""
app/main.py — Maritime Grids Clean-Energy Decision Support Platform Entrypoint
================================================================================
Standard ASGI entrypoint for Maritime Grids exposing `app = create_app()`.
Starts the FastAPI application, NMEA 0183 UDP receiver on port 10110,
and serves the Driver Dashboard at `/dashboard`.

Usage:
  uvicorn app.main:app --host 0.0.0.0 --port 8000
  or:
  python -m app.main
"""

import os
import sys

# Cross-version compatibility shim for unpickling BitGenerators (numpy 1.x <-> 2.x)
try:
    import numpy.random._pickle as _npp
    _orig_bit_gen_ctor = _npp.__bit_generator_ctor
    def _safe_bit_gen_ctor(bit_generator='MT19937'):
        if isinstance(bit_generator, type):
            return bit_generator()
        return _orig_bit_gen_ctor(bit_generator)
    _npp.__bit_generator_ctor = _safe_bit_gen_ctor
except Exception:
    pass

import uvicorn
from app.api.app import create_app

# Create production FastAPI application instance with NMEA receiver enabled
app = create_app(enable_nmea_receiver=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"============================================================")
    print(f" MARITIME GRIDS — Operator Decision Support Platform")
    print(f"============================================================")
    print(f" Dashboard:    http://127.0.0.1:{port}/dashboard")
    print(f" API Docs:     http://127.0.0.1:{port}/docs")
    print(f" NMEA UDP:     127.0.0.1:10110 (Bridge Command Read-Only)")
    print(f" Safety:       Strictly Read-Only (0 Actuators, No Port 10111)")
    print(f"============================================================")
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
