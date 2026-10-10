"""Zingly's own saved copy of reservation data (design §5): not a PSS replica.

* answer from the copy while it is fresh
* "ask once": concurrent misses on one key share a single origin load (single-flight)
* keep the last good value past expiry so a caller can hear it labelled "as of"
"""

from zingly_saved_copy.store import InMemorySavedCopy, Lookup, SavedCopy, SavedCopyConfig

__all__ = ["InMemorySavedCopy", "Lookup", "SavedCopy", "SavedCopyConfig"]
