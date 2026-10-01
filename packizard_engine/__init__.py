"""Packizard-owned compression and asset-pack engine."""
import sys as _sys
from . import container as _container
from . import lz4 as _lz4
_sys.modules.setdefault("packizard_container", _container)
_sys.modules.setdefault("packizard_lz4", _lz4)
from .lz4 import PackizardLz4Codec
__all__ = ["PackizardLz4Codec"]
