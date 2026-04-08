"""Tests for PicNote configuration loading."""

import os

import pytest
import yaml

from src.config import DEFAULT_CONFIG, get_output_paths, ensure_output_dirs, load_config


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_defaults_when_no_config_file(self, tmp_path):
        """Should return default config when config.yaml doesn't exist."""
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        assert config["classification"]["auto_process_screenshots"] is True
        assert config["classification"]["skip_faces_only"] is True
        assert config["classification"]["claude_fallback"] is True
        assert config["notes"]["format"] == "markdown"
        assert config["notes"]["organize_by"] == "date"

    def test_load_custom_output_dir(self, tmp_path):
        """Should load custom output_dir from config.yaml."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"output_dir": "/custom/output"}))
        config = load_config(str(config_path))
        assert config["output_dir"] == "/custom/output"

    def test_expand_tilde_in_paths(self, tmp_path):
        """Paths with ~ should be expanded to the full home directory."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"output_dir": "~/Documents/PicNote"}))
        config = load_config(str(config_path))
        assert "~" not in config["output_dir"]
        assert os.path.expanduser("~") in config["output_dir"]

    def test_expand_tilde_in_photos_library(self, tmp_path):
        """Photos library path with ~ should be expanded."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"photos_library": "~/Pictures/Photos Library.photoslibrary"}))
        config = load_config(str(config_path))
        assert "~" not in config["photos_library"]

    def test_handle_malformed_config(self, tmp_path):
        """Should handle malformed YAML gracefully (empty file)."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")
        config = load_config(str(config_path))
        # Should still have defaults
        assert "output_dir" in config
        assert "classification" in config

    def test_sensitive_keywords_loaded(self, tmp_path):
        """Should load sensitive keywords list from config."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "sensitive_keywords": ["password", "SSN", "secret"]
        }))
        config = load_config(str(config_path))
        assert "password" in config["sensitive_keywords"]
        assert "SSN" in config["sensitive_keywords"]
        assert "secret" in config["sensitive_keywords"]

    def test_deep_merge_preserves_defaults(self, tmp_path):
        """Partial config should preserve unset defaults via deep merge."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "classification": {"auto_process_screenshots": False}
        }))
        config = load_config(str(config_path))
        # Overridden value
        assert config["classification"]["auto_process_screenshots"] is False
        # Preserved defaults
        assert config["classification"]["skip_faces_only"] is True
        assert config["classification"]["claude_fallback"] is True

    def test_processing_config_loaded(self, tmp_path):
        """Should load processing configuration."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "processing": {"max_batch_size": 100, "thumbnail_size": 600}
        }))
        config = load_config(str(config_path))
        assert config["processing"]["max_batch_size"] == 100
        assert config["processing"]["thumbnail_size"] == 600
        # Default preserved
        assert config["processing"]["thumbnail_quality"] == 85

    def test_timeout_defaults_exist(self, tmp_path):
        """New timeout defaults should be present in default config."""
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        assert config["processing"]["claude_timeout_classify"] == 30
        assert config["processing"]["claude_timeout_analyze"] == 60

    def test_timeout_override(self, tmp_path):
        """Custom timeout values should override defaults."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "processing": {"claude_timeout_classify": 90, "claude_timeout_analyze": 120}
        }))
        config = load_config(str(config_path))
        assert config["processing"]["claude_timeout_classify"] == 90
        assert config["processing"]["claude_timeout_analyze"] == 120


class TestGetOutputPaths:
    """Tests for get_output_paths function."""

    def test_returns_all_required_paths(self, test_config):
        paths = get_output_paths(test_config)
        assert "output_dir" in paths
        assert "vault_dir" in paths
        assert "assets_dir" in paths
        assert "data_dir" in paths
        assert "logs_dir" in paths

    def test_paths_are_under_output_dir(self, test_config):
        paths = get_output_paths(test_config)
        output_dir = paths["output_dir"]
        for key, path in paths.items():
            assert path.startswith(output_dir), f"{key} not under output_dir"


class TestEnsureOutputDirs:
    """Tests for ensure_output_dirs function."""

    def test_creates_all_directories(self, test_config):
        paths = ensure_output_dirs(test_config)
        for key, path in paths.items():
            assert os.path.isdir(path), f"{key} directory not created: {path}"

    def test_idempotent(self, test_config):
        """Calling twice should not fail."""
        ensure_output_dirs(test_config)
        paths = ensure_output_dirs(test_config)
        for path in paths.values():
            assert os.path.isdir(path)
