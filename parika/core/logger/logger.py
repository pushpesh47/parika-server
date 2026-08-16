"""
Logging service for PARIKA.

This module configures the application's logging infrastructure using
Python's standard logging package. It initializes console and file
handlers, applies a common formatter, and provides logger instances
within the PARIKA logger hierarchy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime

from parika.core.configuration.configuration import Configuration


class Logger:
    """
    Configure and provide application loggers.
    """

    def __init__(self, configuration: Configuration) -> None:
        """
        Initialize the logging service.

        Args:
            configuration:
                Loaded application configuration.
        """

        self._configuration = configuration
        self._root_logger_name = "parika"

        self._root_logger = logging.getLogger(self._root_logger_name)

        self._configure()

    def get_logger(self, name: str) -> logging.Logger:
        """
        Return a logger within the PARIKA hierarchy.

        Args:
            name:
                Logger name.

        Returns:
            Configured logger instance.
        """

        if not name:
            return self._root_logger

        if name == self._root_logger_name:
            return self._root_logger

        if name.startswith(f"{self._root_logger_name}."):
            return logging.getLogger(name)

        return logging.getLogger(f"{self._root_logger_name}.{name}")

    def _configure(self) -> None:
        """
        Configure the root PARIKA logger.
        """

        if self._root_logger.handlers:
            return

        logging_level = self._get_logging_level()

        self._root_logger.setLevel(logging_level)
        self._root_logger.propagate = False

        formatter = self._create_formatter()

        if self._configuration.get("logging.console", True):
            console_handler = self._create_console_handler(formatter)
            self._root_logger.addHandler(console_handler)

        file_handler = self._create_file_handler(formatter)

        if file_handler is not None:
            self._root_logger.addHandler(file_handler)

    def _get_logging_level(self) -> int:
        """
        Resolve the configured logging level.

        Returns:
            Python logging level.
        """

        configured_level = self._configuration.get("logging.level", "INFO")

        if not isinstance(configured_level, str):
            return logging.INFO

        return getattr(logging, configured_level.upper(), logging.INFO)

    def _create_formatter(self) -> logging.Formatter:
        """
        Create the default log formatter.

        Returns:
            Configured formatter.
        """

        return logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def _create_console_handler(
        self,
        formatter: logging.Formatter,
    ) -> logging.Handler:
        """
        Create the console logging handler.

        Args:
            formatter:
                Formatter applied to the handler.

        Returns:
            Configured console handler.
        """

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        return console_handler

    def _create_file_handler(
        self,
        formatter: logging.Formatter,
    ) -> logging.Handler | None:
        """
        Create the file logging handler.

        If file logging cannot be configured, the application
        continues using console logging only.

        Args:
            formatter:
                Formatter applied to the handler.

        Returns:
            File handler or None.
        """

        try:
            log_file_path = self._get_log_file_path()

            log_file_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            file_handler = logging.FileHandler(
                filename=log_file_path,
                mode="a",
                encoding="utf-8",
            )

            file_handler.setFormatter(formatter)

            return file_handler

        except Exception:
            return None

    def _get_log_file_path(self) -> Path:
        """
        Build the configured log file path.

        Returns:
            Absolute path to the log file.
        """

        log_directory = self._configuration.get("logging.directory", "logs")
        log_file = self._configuration.get("logging.file", "parika.log")

        log_file_path = Path(log_file)

        log_file_name = (
            f"{log_file_path.stem}-{datetime.now().strftime('%Y-%m-%d')}"
            f"{log_file_path.suffix}"
        )

        return Path(log_directory) / log_file_name

    