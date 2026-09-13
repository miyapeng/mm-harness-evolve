"""Official scorer with an explicit CLIP cache path; no metric changes."""

import os
from pathlib import Path

from multimodalcode.official_design2code import _ensure_pkg_resources_compat, main

_ensure_pkg_resources_compat()
import clip

original_load = clip.load


def load_from_cache(name, *args, **kwargs):
    kwargs.setdefault("download_root", str(Path(os.environ["MM_HARNESS_CACHE"]) / "clip"))
    return original_load(name, *args, **kwargs)


clip.load = load_from_cache
main()
