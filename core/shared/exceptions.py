from __future__ import annotations


class PlatformError(RuntimeError):
    """Base error shared by API, worker and scripts."""


class PermissionDenied(PlatformError):
    """Raised when an actor cannot perform the requested action."""


class RiskPolicyViolation(PlatformError):
    """Raised when a high-risk action is blocked by policy."""


class RecoverableRuntimeError(PlatformError):
    """Raised when the runtime should move into a recoverable state."""

