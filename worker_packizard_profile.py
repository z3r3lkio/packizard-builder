"""Frozen Packizard trace-profile entry point."""
import multiprocessing
from packizard_engine.profile import main
if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
