"""Behavioural model of the sky130-trng digital section.

Everything downstream of the raw tap, modelled bit-exactly and
cycle-accurately in Python. ``digital/rtl/`` implements this; the two are
checked against each other by ``sim/digital-rtl-equivalence/``.
"""

from .conditioner import Crc32Conditioner
from .digital_top import TrngDigital
from .health import AdaptiveProportionTest, HealthMonitor, RepetitionCountTest

__all__ = [
    "AdaptiveProportionTest",
    "Crc32Conditioner",
    "HealthMonitor",
    "RepetitionCountTest",
    "TrngDigital",
]
