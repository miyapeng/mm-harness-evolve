"""Freeze public skills discovery to the old image snapshot, avoiding mutable GitHub pulls."""

import os
from pathlib import Path

import openhands.sdk.skills.skill as skill_module


def frozen_repository(*args, **kwargs):
    return Path(os.environ["MM_HARNESS_EXTENSIONS"])


# The CLI loads identical skill files through the original parser/marketplace filter.
skill_module.update_skills_repository = frozen_repository

from openhands_cli.entrypoint import main  # noqa: E402

main()
