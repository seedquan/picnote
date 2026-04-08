"""PicNote configuration loader."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

DEFAULT_CONFIG = {
    "output_dir": "~/Documents/PicNote",
    "photos_library": "~/Pictures/Photos Library.photoslibrary",
    "classification": {
        "auto_process_screenshots": True,
        "skip_faces_only": True,
        "claude_fallback": True,
    },
    "notes": {
        "format": "markdown",
        "organize_by": "date",
    },
    "sensitive_keywords": ["password", "SSN", "bank account"],
    "processing": {
        "max_batch_size": 50,
        "thumbnail_size": 800,
        "thumbnail_quality": 85,
        "claude_timeout_classify": 30,
        "claude_timeout_analyze": 60,
    },
}


def load_config(config_path: str | None = None) -> dict:
    """Load configuration from YAML file, falling back to defaults."""
    config = dict(DEFAULT_CONFIG)

    if config_path is None:
        # Look for config.yaml in project root
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

    if os.path.exists(config_path):
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)

    # Expand ~ in paths
    config["output_dir"] = str(Path(config["output_dir"]).expanduser())
    config["photos_library"] = str(Path(config["photos_library"]).expanduser())

    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_output_paths(config: dict) -> dict:
    """Get all output directory paths from config."""
    output_dir = config["output_dir"]
    return {
        "output_dir": output_dir,
        "vault_dir": os.path.join(output_dir, "vault"),
        "assets_dir": os.path.join(output_dir, "vault", "assets"),
        "data_dir": os.path.join(output_dir, "data"),
        "logs_dir": os.path.join(output_dir, "logs"),
    }


def ensure_output_dirs(config: dict) -> dict:
    """Create output directories if they don't exist. Returns paths dict."""
    paths = get_output_paths(config)
    for path in paths.values():
        os.makedirs(path, exist_ok=True)
    return paths
