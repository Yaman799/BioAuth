"""OS abstraction layer for BioAuth.

The desktop app is currently production-targeted for Windows. These helpers keep the
public API stable while isolating platform-specific implementations so Linux/macOS
support can be added incrementally later.
"""

from .lock_screen import lock_current_session
from .notifications import NotificationLevel, show_notification
from .secrets import get_secret_backend_name, load_or_create_secret
from .startup import is_startup_enabled, set_startup_enabled

__all__ = [
    "NotificationLevel",
    "get_secret_backend_name",
    "is_startup_enabled",
    "load_or_create_secret",
    "lock_current_session",
    "set_startup_enabled",
    "show_notification",
]
