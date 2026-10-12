"""Actionable errors for CLI and distribution reports."""

from __future__ import annotations


class AppError(Exception):
    """Base for expected application errors."""


class ConfigurationError(AppError):
    """Configuration or customization input is invalid."""


class SourceError(AppError):
    """An authoritative source snapshot is unavailable."""


class ConflictError(AppError):
    """Proposed output conflicts with ownership."""


class ConversionError(AppError):
    """Conversion cannot preserve requested semantics."""


class TransactionError(AppError):
    """Commit or recovery failed."""
