from __future__ import annotations

import os
import time
from typing import Optional, Sequence


def resolve_startup_logo_path(base_dir: str) -> Optional[str]:
    candidates = [
        os.path.join(base_dir, "logo.png"),
        os.path.join(base_dir, "assets", "logo.png"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def should_show_startup_splash(argv: Sequence[str]) -> bool:
    """Keep startup branding disabled after moving the logo into onboarding.

    The splash entry remains in place only as a safe no-op seam for older call sites.
    """
    return False


def create_startup_splash(app, base_dir: str):
    logo_path = resolve_startup_logo_path(base_dir)
    if not logo_path:
        return None
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication, QPixmap
        from PySide6.QtWidgets import QSplashScreen

        pixmap = QPixmap(logo_path)
        if pixmap.isNull():
            return None
        if pixmap.width() > 960 or pixmap.height() > 540:
            pixmap = pixmap.scaled(960, 540, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        splash.setAttribute(Qt.WA_TranslucentBackground, True)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            splash.move(
                geometry.x() + max(0, (geometry.width() - splash.sizeHint().width()) // 2),
                geometry.y() + max(0, (geometry.height() - splash.sizeHint().height()) // 2),
            )
        splash._bioauth_started_at = time.time()
        splash.show()
        try:
            app.processEvents()
        except Exception:
            pass
        return splash
    except Exception:
        return None


def finish_startup_splash(timer_cls, splash, target=None, min_visible_ms: int = 900) -> None:
    if splash is None:
        return
    started_at = getattr(splash, "_bioauth_started_at", None)
    try:
        elapsed_ms = max(0, int((time.time() - float(started_at)) * 1000)) if started_at is not None else min_visible_ms
    except Exception:
        elapsed_ms = min_visible_ms
    delay_ms = max(0, int(min_visible_ms) - int(elapsed_ms))

    def _close() -> None:
        try:
            if target is not None and hasattr(splash, "finish"):
                splash.finish(target)
            else:
                splash.close()
        except Exception:
            try:
                splash.close()
            except Exception:
                pass

    if delay_ms <= 0:
        _close()
    else:
        timer_cls.singleShot(delay_ms, _close)
