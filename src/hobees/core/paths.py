"""Filesystem-safe path helpers shared by the core engine and the tool layer.

Hobees thread keys are namespaced (`container:bee|hive|assistant:name:run`), and
the same key is used as a directory name for offloaded tool output. `:` cannot
appear in a Windows path segment, so every place that turns a namespaced key
into a path must go through :func:`safe_path_component`.
"""

from __future__ import annotations

import re

#: Characters a single path segment cannot contain on Windows. `/` and `\` are
#: separators rather than segment characters, but replacing them keeps a helper
#: safe when a full key is passed in by accident.
_ILLEGAL_SEGMENT_CHARS = re.compile(r'[<>:"|?*\\/]')


def safe_path_component(value: str, *, separator: str = "__") -> str:
    """Return ``value`` as one filesystem-safe path segment.

    A key that is already safe is returned unchanged, so existing artifact and
    scratchpad layouts keep their names; only reserved characters are replaced.
    """
    cleaned = _ILLEGAL_SEGMENT_CHARS.sub(separator, str(value)).strip()
    # `.` and `..` (or a key made only of dots) are not usable as a directory name.
    return cleaned.strip(".") or "unknown"


__all__ = ["safe_path_component"]
