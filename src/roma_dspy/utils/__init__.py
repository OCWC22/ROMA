"""Utility functions and classes for ROMA-DSPy."""

import logging
from loguru import logger

from .async_executor import AsyncParallelExecutor
from .cli_lm import CLILM
from .cli_runner import CLIRunner
from .lm_factory import (
    apply_global_lm_override,
    backend_from_cli_name,
    build_lm_kwargs_from_config,
    create_gepa_reflection_lm,
    create_lm,
    create_lm_from_config,
    normalize_lm_backend,
)

__all__ = [
    "AsyncParallelExecutor",
    "CLILM",
    "CLIRunner",
    "apply_global_lm_override",
    "backend_from_cli_name",
    "build_lm_kwargs_from_config",
    "create_gepa_reflection_lm",
    "create_lm",
    "create_lm_from_config",
    "log_async_execution",
    "normalize_lm_backend",
]


def log_async_execution(verbose: bool = False):
    """
    Configure logging for async execution tasks.

    Args:
        verbose: If True, enable DEBUG level logging. Otherwise INFO level.
    """
    log_level = "DEBUG" if verbose else "INFO"

    # Configure loguru logger
    logger.remove()  # Remove default handler
    logger.add(
        lambda msg: print(msg, end=""),
        level=log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # Also configure standard logging (for compatibility)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s - %(message)s",
        datefmt="%H:%M:%S",
    )
