"""Tests for PicNote image classifier."""

from unittest.mock import MagicMock, patch

import pytest

from src.classifier import Classification, classify_image, _classify_local
from src.watcher import PhotoAsset


class TestLocalClassification:
    """Tests for local heuristic classification."""

    def test_screenshot_with_text_is_informational(self, screenshot_asset, test_config):
        result = classify_image(screenshot_asset, test_config)
        assert result == Classification.INFORMATIONAL

    def test_selfie_is_casual(self, selfie_asset, test_config):
        result = classify_image(selfie_asset, test_config)
        assert result == Classification.CASUAL

    def test_family_group_photo_casual(self, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "family.jpg")
        _create_test_image(img_path, 640, 480)

        asset = PhotoAsset(
            uuid="FAMILY-001",
            filename="family.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=["portrait", "party"],
            has_text=False,
            face_count=5,
            captured_at=None,
            width=640,
            height=480,
        )
        result = classify_image(asset, test_config)
        assert result == Classification.CASUAL

    def test_landscape_is_casual(self, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "landscape.jpg")
        _create_test_image(img_path, 640, 480)

        asset = PhotoAsset(
            uuid="LANDSCAPE-001",
            filename="landscape.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=["landscape", "mountain", "sky"],
            has_text=False,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )
        result = classify_image(asset, test_config)
        assert result == Classification.CASUAL

    def test_document_is_informational(self, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "document.jpg")
        _create_test_image(img_path, 640, 480)

        asset = PhotoAsset(
            uuid="DOC-001",
            filename="document.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=["document", "text"],
            has_text=True,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )
        result = classify_image(asset, test_config)
        assert result == Classification.INFORMATIONAL

    def test_receipt_is_informational(self, receipt_asset, test_config):
        result = classify_image(receipt_asset, test_config)
        assert result == Classification.INFORMATIONAL

    def test_qr_code_image_informational(self, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "qr.jpg")
        _create_test_image(img_path, 640, 480)

        asset = PhotoAsset(
            uuid="QR-001",
            filename="qr.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=["text"],
            has_text=True,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )
        result = classify_image(asset, test_config)
        assert result == Classification.INFORMATIONAL

    def test_screenshot_flag_fast_tracks(self, tmp_path, test_config):
        """Screenshot flag should fast-track to informational regardless of other signals."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "ss.png")
        _create_test_image(img_path, 390, 844)

        asset = PhotoAsset(
            uuid="SS-001",
            filename="ss.png",
            directory="A",
            file_path=img_path,
            is_screenshot=True,  # This should fast-track
            scene_labels=[],     # No scene labels
            has_text=False,      # No text detected
            face_count=0,
            captured_at=None,
            width=390,
            height=844,
        )
        result = classify_image(asset, test_config)
        assert result == Classification.INFORMATIONAL

    def test_apple_scene_label_document_fast_tracks(self, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "doc.jpg")
        _create_test_image(img_path, 640, 480)

        asset = PhotoAsset(
            uuid="SCENE-DOC",
            filename="doc.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=["document"],
            has_text=False,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )
        result = classify_image(asset, test_config)
        assert result == Classification.INFORMATIONAL

    def test_mixed_content_faces_and_text(self, tmp_path, test_config):
        """Image with both faces and text should be ambiguous (triggers Claude fallback)."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "mixed.jpg")
        _create_test_image(img_path, 640, 480)

        asset = PhotoAsset(
            uuid="MIXED-001",
            filename="mixed.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=[],
            has_text=True,
            face_count=2,
            captured_at=None,
            width=640,
            height=480,
        )
        # With no Claude fallback, ambiguous defaults to informational
        config = dict(test_config)
        config["classification"] = dict(config["classification"])
        config["classification"]["claude_fallback"] = False
        result = classify_image(asset, config)
        assert result == Classification.INFORMATIONAL

    def test_auto_process_screenshots_disabled(self, tmp_path, test_config):
        """When auto_process_screenshots is disabled, screenshots aren't fast-tracked."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "ss_disabled.png")
        _create_test_image(img_path, 390, 844)

        asset = PhotoAsset(
            uuid="SS-DISABLED",
            filename="ss_disabled.png",
            directory="A",
            file_path=img_path,
            is_screenshot=True,
            scene_labels=[],
            has_text=False,
            face_count=0,
            captured_at=None,
            width=390,
            height=844,
        )
        config = dict(test_config)
        config["classification"] = dict(config["classification"])
        config["classification"]["auto_process_screenshots"] = False
        config["classification"]["claude_fallback"] = False

        # Without screenshot fast-track and no text/scenes, it's ambiguous → defaults informational
        result = classify_image(asset, config)
        assert result == Classification.INFORMATIONAL


class TestClaudeFallback:
    """Tests for Claude Code CLI classification fallback."""

    @patch("src.classifier.subprocess.run")
    def test_claude_classifies_informational(self, mock_run, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "ambig.jpg")
        _create_test_image(img_path, 640, 480)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="INFORMATIONAL",
            stderr="",
        )

        asset = PhotoAsset(
            uuid="AMBIG-001",
            filename="ambig.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=[],
            has_text=False,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )
        result = classify_image(asset, test_config)
        assert result == Classification.INFORMATIONAL
        mock_run.assert_called_once()

    @patch("src.classifier.subprocess.run")
    def test_claude_classifies_casual(self, mock_run, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "ambig2.jpg")
        _create_test_image(img_path, 640, 480)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="CASUAL",
            stderr="",
        )

        asset = PhotoAsset(
            uuid="AMBIG-002",
            filename="ambig2.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=[],
            has_text=False,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )
        result = classify_image(asset, test_config)
        assert result == Classification.CASUAL

    @patch("src.classifier.subprocess.run")
    def test_claude_timeout_defaults_informational(self, mock_run, tmp_path, test_config):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("claude", 30)

        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "timeout.jpg")
        _create_test_image(img_path, 640, 480)

        asset = PhotoAsset(
            uuid="TIMEOUT-001",
            filename="timeout.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=[],
            has_text=False,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )
        result = classify_image(asset, test_config)
        assert result == Classification.INFORMATIONAL

    @patch("src.classifier.subprocess.run")
    def test_claude_error_defaults_informational(self, mock_run, tmp_path, test_config):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: connection failed",
        )

        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "error.jpg")
        _create_test_image(img_path, 640, 480)

        asset = PhotoAsset(
            uuid="ERR-001",
            filename="error.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=[],
            has_text=False,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )
        result = classify_image(asset, test_config)
        assert result == Classification.INFORMATIONAL

    def test_claude_not_called_for_clear_cases(self, screenshot_asset, test_config):
        """Claude CLI should NOT be invoked for clearly informational/casual images."""
        with patch("src.classifier.subprocess.run") as mock_run:
            classify_image(screenshot_asset, test_config)
            mock_run.assert_not_called()

    def test_claude_not_called_when_disabled(self, tmp_path, test_config):
        """Claude CLI should not be invoked when claude_fallback is disabled."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "no_fallback.jpg")
        _create_test_image(img_path, 640, 480)

        config = dict(test_config)
        config["classification"] = dict(config["classification"])
        config["classification"]["claude_fallback"] = False

        asset = PhotoAsset(
            uuid="NOFB-001",
            filename="no_fallback.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=[],
            has_text=False,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )

        with patch("src.classifier.subprocess.run") as mock_run:
            classify_image(asset, config)
            mock_run.assert_not_called()

    @patch("src.classifier.subprocess.run")
    def test_word_boundary_rejects_partial_match(self, mock_run, tmp_path, test_config):
        """'MISINFORMATIONAL' should NOT match INFORMATIONAL with word boundaries."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "partial.jpg")
        _create_test_image(img_path, 640, 480)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="MISINFORMATIONAL",
            stderr="",
        )

        asset = PhotoAsset(
            uuid="PARTIAL-001",
            filename="partial.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=[],
            has_text=False,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )
        # Should NOT match due to word boundary, defaults to INFORMATIONAL
        result = classify_image(asset, test_config)
        assert result == Classification.INFORMATIONAL

    @patch("src.classifier.subprocess.run")
    def test_response_with_surrounding_text(self, mock_run, tmp_path, test_config):
        """Response like 'I think this is CASUAL.' should still match."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "noisy.jpg")
        _create_test_image(img_path, 640, 480)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="I think this is CASUAL.",
            stderr="",
        )

        asset = PhotoAsset(
            uuid="NOISY-001",
            filename="noisy.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=[],
            has_text=False,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )
        result = classify_image(asset, test_config)
        assert result == Classification.CASUAL

    @patch("src.classifier.subprocess.run")
    def test_configurable_timeout_used(self, mock_run, tmp_path, test_config):
        """Custom timeout from config should be passed to subprocess."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "timeout.jpg")
        _create_test_image(img_path, 640, 480)

        config = dict(test_config)
        config["processing"] = dict(config.get("processing", {}))
        config["processing"]["claude_timeout_classify"] = 45

        mock_run.return_value = MagicMock(
            returncode=0, stdout="INFORMATIONAL", stderr=""
        )

        asset = PhotoAsset(
            uuid="TIMEOUT-CFG",
            filename="timeout.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=[],
            has_text=False,
            face_count=0,
            captured_at=None,
            width=640,
            height=480,
        )
        classify_image(asset, config)
        # Verify timeout was passed from config
        call_kwargs = mock_run.call_args
        assert call_kwargs[1]["timeout"] == 45
