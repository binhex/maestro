"""Daemon module — scheduled pipeline execution.

Provides the :class:`Daemon` class for running the scan → identify → import
pipeline on a cron-based schedule, and :func:`is_due` for checking whether
a cron expression matches the current time.
"""

from __future__ import annotations

import signal
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from croniter import croniter  # type: ignore[import-untyped]
from loguru import logger

from maestro.db.core import create_session, get_engine

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from maestro.config import Config


# Default pipeline interval (seconds) between cron checks.
_POLL_INTERVAL: float = 10.0


# ---------------------------------------------------------------------------
# Cron helpers
# ---------------------------------------------------------------------------


def is_due(cron_expression: str, current_time: datetime | None = None) -> bool:
    """Check whether *cron_expression* matches *current_time*.

    Uses :class:`croniter.croniter` to determine if the given expression
    fires at the supplied moment.  If *current_time* is ``None`` the
    current UTC time is used.

    Returns ``False`` for any invalid cron expression (rather than raising).

    Args:
        cron_expression: Standard 5-field cron expression
            (minute hour dom month dow).
        current_time: The datetime to check.  ``None`` means "now".

    Returns:
        ``True`` if the expression matches the time, ``False`` otherwise.
    """
    if current_time is None:
        current_time = datetime.now(UTC)

    try:
        # Check if current_time falls between the previous and next
        # cron firing, within a 60-second window. This correctly handles
        # microsecond precision and non-zero poll intervals.
        cron = croniter(cron_expression, current_time)
        prev_match: datetime = cast("datetime", cron.get_prev(datetime))
        nxt_match: datetime = cast("datetime", cron.get_next(datetime))
        # Due if current_time is within 60 seconds of either boundary
        return (
            abs((current_time - prev_match).total_seconds()) < 60
            or abs((nxt_match - current_time).total_seconds()) < 60
        )
    except (ValueError, KeyError):
        return False


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def run_pipeline(config: Config | None, session: Any) -> dict[str, Any]:
    """Run the full scan → identify → import pipeline.

    Process:
    1. Scan all enabled download roots (creates Download records).
    2. Identify all newly-discovered downloads.
    3. Import all identified downloads into the first enabled library root.

    If *config* is ``None`` or lacks roots the pipeline is a no-op.

    Args:
        config: The application :class:`~maestro.config.Config`.  May be
            ``None`` — the function will return an empty summary.
        session: An active SQLAlchemy session.

    Returns:
        A dictionary containing cumulative pipeline results:

        - ``scan`` — list of per-root scan results
        - ``identified`` — count of identified downloads
        - ``imported`` — dict of import counts
        - ``pipeline`` — overall summary (errors, success flag)
    """
    from maestro.identifier import identify_downloads  # noqa: PLC0415
    from maestro.organizer import import_downloads  # noqa: PLC0415
    from maestro.scanner import scan_download_root  # noqa: PLC0415

    result: dict[str, Any] = {
        "scan": [],
        "identified": 0,
        "imported": {},
        "pipeline": {"errors": 0, "success": True},
    }

    if config is None:
        logger.info("No config provided — pipeline skipped")
        return result

    # --- 1. Scan download roots ---
    download_roots = [r for r in config.download_roots if r.enabled]
    if not download_roots:
        logger.info("No enabled download roots — scan phase skipped")
    else:
        for entry in download_roots:
            try:
                scan_result = scan_download_root(session, entry.path, pattern=getattr(entry, "pattern", None))
                result["scan"].append({"root": entry.path, **scan_result})
                logger.info("Scanned {}: {}", entry.path, scan_result)
            except Exception:  # noqa: BLE001
                logger.exception("Scan failed for {}", entry.path)
                result["pipeline"]["errors"] += 1

    # --- 2. Identify downloads ---
    try:
        identified = identify_downloads(session)
        result["identified"] = len(identified)
        logger.info("Identified {} downloads", len(identified))
    except Exception:  # noqa: BLE001
        logger.exception("Identification phase failed")
        result["pipeline"]["errors"] += 1

    # --- 3. Import identified downloads ---
    library_roots = [r for r in config.library_roots if r.enabled]
    if not library_roots:
        logger.info("No enabled library roots — import phase skipped")
    else:
        # Use the first enabled library root
        lib_root = library_roots[0]
        dest_pattern = lib_root.destination_pattern or "{artist}/{album}/{filename}.{ext}"
        try:
            import_result = import_downloads(
                session=session,
                destination_root=lib_root.path,
                destination_pattern=dest_pattern,
                move=True,
                delete_replaced=config.quality.delete_replaced,
            )
            result["imported"] = import_result
            logger.info("Imported: {}", import_result)
        except Exception:  # noqa: BLE001
            logger.exception("Import phase failed")
            result["pipeline"]["errors"] += 1

    result["pipeline"]["success"] = result["pipeline"]["errors"] == 0
    return result


# ---------------------------------------------------------------------------
# Daemon class
# ---------------------------------------------------------------------------


class Daemon:
    """Foreground daemon that runs the Maestro pipeline on a cron schedule.

    Stateful shutdown via signal handlers: SIGTERM and SIGINT set an internal
    ``_shutdown_requested`` flag so the main loop can exit cleanly.

    The daemon runs in the foreground.  An OS service manager (systemd,
    supervisord, etc.) is expected to handle backgrounding.
    """

    def __init__(
        self,
        config: Config | None,
        db_path: str | None = None,
    ) -> None:
        """Initialise the daemon with the given *config* and *db_path*.

        Registers signal handlers for SIGTERM and SIGINT that set
        ``_shutdown_requested = True``.

        Args:
            config: The application configuration.  May be ``None``.
            db_path: Path to the SQLite database.  If ``None``, uses
                ``MAESTRO_DB`` env var, then default project path.
        """
        self.config: Config | None = config
        self._db_path: str | None = db_path
        self._shutdown_requested: bool = False
        self._engine: Engine | None = None
        self._has_run_once: bool = False

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, _frame: object) -> None:
        """Handle termination signals by setting the shutdown flag.

        Args:
            signum: The signal number received.
            _frame: Current stack frame (unused).
        """
        logger.info("Received signal {} — shutting down gracefully", signum)
        self._shutdown_requested = True

    def _get_cron_expression(self) -> str:
        """Return the cron expression from config, or a default."""
        if self.config is not None:
            return self.config.scheduler.schedule
        return "0 3 * * *"

    def _should_run_on_start(self) -> bool:
        """Return whether the pipeline should run immediately on start."""
        if self.config is not None:
            return self.config.scheduler.run_on_start
        return True

    def _get_engine(self) -> Engine | None:
        """Return a cached SQLAlchemy engine.

        The engine is created lazily from the config database path.  If no
        config is available, ``None`` is returned.
        """
        if self._engine is not None:
            return self._engine

        if self.config is not None:
            import os  # noqa: PLC0415

            db_path = self._db_path or os.environ.get("MAESTRO_DB", "")
            if not db_path:
                from maestro.utils import get_project_root  # noqa: PLC0415

                db_path = str(get_project_root() / "db" / "maestro.db")
            self._engine = get_engine(db_path)
            from maestro.db.core import init_db  # noqa: PLC0415

            init_db(self._engine)

        return self._engine

    def run(self) -> None:
        """Main daemon loop.

        - When ``run_on_start`` is ``True`` (default), runs the pipeline
          immediately on startup.
        - Then checks the cron expression every *POLL_INTERVAL* seconds.
        - When the cron expression matches the current time, runs the
          pipeline.
        - On SIGTERM / SIGINT, sets ``_shutdown_requested = True`` and
          exits the loop cleanly.
        """
        logger.info("Daemon starting (PID {})", os_getpid())

        engine = self._get_engine()
        if engine is None:
            logger.error("No database configured — daemon cannot run")
            return

        # Optionally run immediately on start
        if self._should_run_on_start():
            logger.info("run_on_start is True — running initial pipeline")
            self._run_pipeline_once(engine)

        self._has_run_once = True

        # Main loop
        while not self._shutdown_requested:
            try:
                now = datetime.now(UTC)
                cron_expr = self._get_cron_expression()

                if is_due(cron_expr, current_time=now):
                    logger.info("Cron expression '{}' is due — running pipeline", cron_expr)
                    self._run_pipeline_once(engine)
                else:
                    logger.debug("Cron '{}' not due at {}", cron_expr, now)

            except Exception:  # noqa: BLE001
                logger.exception("Unexpected error in daemon main loop")

            # Sleep in small increments so we can react promptly to shutdown
            self._sleep_interruptible(_POLL_INTERVAL)

        logger.info("Daemon shut down gracefully")

    def _run_pipeline_once(self, engine: Engine) -> None:
        """Run a single pipeline iteration using the given engine.

        Creates a session, calls :func:`run_pipeline`, and logs results.

        Args:
            engine: A SQLAlchemy engine instance.
        """
        session = create_session(engine)
        try:
            result = run_pipeline(self.config, session)
            session.commit()
            pl = result.get("pipeline", {})
            logger.info(
                "Pipeline finished — errors={} success={}",
                pl.get("errors", 0),
                pl.get("success", False),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Pipeline iteration failed")
            session.rollback()
        finally:
            session.close()

    def _sleep_interruptible(self, seconds: float) -> None:
        """Sleep for *seconds* in short intervals, checking shutdown flag.

        This allows the daemon to respond to signals quickly rather than
        blocking for the full sleep duration.
        """
        interval = min(seconds, 0.5)
        elapsed = 0.0
        while elapsed < seconds and not self._shutdown_requested:
            time.sleep(interval)
            elapsed += interval


def os_getpid() -> int:
    """Return the current process PID.

    Wrapped so it can be patched in tests.
    """
    import os  # noqa: PLC0415

    return os.getpid()
