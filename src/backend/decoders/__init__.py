"""SpectraSDR decoder plugin system.

Auto-discovers BaseDecoder subclasses from all Python modules in this directory.
"""

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Type

from .base import BaseDecoder, InputType, DecoderState, DecoderResult

logger = logging.getLogger(__name__)

__all__ = [
    "BaseDecoder", "InputType", "DecoderState", "DecoderResult",
    "discover_decoders", "load_decoders",
]


def discover_decoders() -> dict[str, Type[BaseDecoder]]:
    """Scan the decoders package and return {name: class} for every concrete BaseDecoder subclass."""
    found: dict[str, Type[BaseDecoder]] = {}
    package_path = str(Path(__file__).parent)

    for finder, module_name, _ispkg in pkgutil.iter_modules([package_path]):
        if module_name.startswith("_") or module_name == "base":
            continue
        try:
            mod = importlib.import_module(f".{module_name}", package=__package__)
        except Exception:
            logger.exception(f"Failed to import decoder module: {module_name}")
            continue

        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseDecoder)
                and obj is not BaseDecoder
                and not getattr(obj, "__abstractmethods__", set())
            ):
                found[obj.name] = obj
                logger.info(f"Discovered decoder plugin: {obj.name} ({obj.__name__})")

    return found


def load_decoders(sample_rate: int = 48000) -> dict[str, BaseDecoder]:
    """Discover, initialize, and instantiate all decoder plugins. Returns {name: instance}."""
    classes = discover_decoders()
    instances: dict[str, BaseDecoder] = {}
    for name, cls in classes.items():
        try:
            inst = cls(sample_rate=sample_rate)
            # Call one-time init; skip if it returns False
            if not inst.init():
                logger.warning(f"Decoder '{name}' init() returned False — skipping")
                continue
            instances[name] = inst
            logger.info(f"Loaded decoder: {name} v{cls.version}")
        except Exception:
            logger.exception(f"Failed to instantiate decoder: {name}")
    return instances
