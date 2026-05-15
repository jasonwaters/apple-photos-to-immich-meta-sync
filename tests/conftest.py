"""Pytest configuration."""

import logging

import pytest


@pytest.fixture(autouse=True)
def configure_logging():
    """Configure logging for tests."""
    logging.basicConfig(level=logging.DEBUG)
