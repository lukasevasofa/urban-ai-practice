"""Проверки используют только актуальную practice3; результаты — во временной папке приложения."""

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from model import Model


@pytest.fixture(scope="session")
def model(tmp_path_factory):
    return Model(output=tmp_path_factory.mktemp("results"))
