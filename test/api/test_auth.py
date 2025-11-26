"""Unit tests for API authentication module."""

import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.auth import AdminAuth, verify_admin_key


class TestAdminAuth:
    """Test AdminAuth class for key loading and verification."""

    @patch.dict(os.environ, {"TALOS_ADMIN_KEY": "env-secret-key"}, clear=True)
    def test_when_env_var_set_then_loads_from_environment(self):
        """Test that admin key is loaded from environment variable with highest priority."""
        # Arrange & Act
        auth = AdminAuth()

        # Assert
        assert auth.admin_key == "env-secret-key"

    @patch.dict(os.environ, {}, clear=True)
    @patch("api.auth.ConfigManager.load_yaml_file")
    def test_when_config_file_exists_then_loads_from_config(self, mock_load_config):
        """Test that admin key is loaded from config file when env var not set."""
        # Arrange
        mock_load_config.return_value = {"admin_key": "config-secret-key"}

        # Act
        auth = AdminAuth()

        # Assert
        assert auth.admin_key == "config-secret-key"
        mock_load_config.assert_called_once_with("config/api_auth.yaml")

    @patch.dict(os.environ, {}, clear=True)
    @patch("api.auth.ConfigManager.load_yaml_file", side_effect=FileNotFoundError())
    def test_when_no_config_exists_then_uses_default(self, mock_load_config):
        """Test that default key is used when neither env var nor config file exists."""
        # Arrange & Act
        auth = AdminAuth()

        # Assert
        assert auth.admin_key == "change-me-in-production"

    def test_when_correct_key_provided_then_verification_succeeds(self):
        """Test that verify_key returns True for correct key."""
        # Arrange
        auth = AdminAuth()
        auth.admin_key = "test-secret-key"

        # Act
        result = auth.verify_key("test-secret-key")

        # Assert
        assert result is True

    def test_when_incorrect_key_provided_then_verification_fails(self):
        """Test that verify_key returns False for incorrect key."""
        # Arrange
        auth = AdminAuth()
        auth.admin_key = "test-secret-key"

        # Act
        result = auth.verify_key("wrong-key")

        # Assert
        assert result is False


class TestVerifyAdminKeyDependency:
    """Test verify_admin_key FastAPI dependency."""

    @patch("api.auth._admin_auth")
    def test_when_valid_key_provided_then_passes_verification(self, mock_auth):
        """Test that dependency passes with valid admin key."""
        # Arrange
        mock_auth.verify_key.return_value = True

        # Act & Assert (should not raise)
        try:
            verify_admin_key(x_admin_key="valid-key")
        except HTTPException:
            pytest.fail("Should not raise HTTPException for valid key")

        mock_auth.verify_key.assert_called_once_with("valid-key")

    @patch("api.auth._admin_auth")
    def test_when_invalid_key_provided_then_raises_403(self, mock_auth):
        """Test that dependency raises 403 for invalid admin key."""
        # Arrange
        mock_auth.verify_key.return_value = False

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key="invalid-key")

        assert exc_info.value.status_code == 403
        assert "Invalid admin key" in exc_info.value.detail
        mock_auth.verify_key.assert_called_once_with("invalid-key")

    @patch("api.auth._admin_auth")
    def test_when_no_key_provided_then_raises_422(self, mock_auth):
        """Test that missing header raises validation error (handled by FastAPI)."""
        # Note: FastAPI will raise 422 for missing required header
        # This test verifies the Header(...) requirement

        # The actual validation happens in FastAPI, not in our function
        # We just verify our function expects the parameter
        import inspect

        sig = inspect.signature(verify_admin_key)

        # Assert
        assert "x_admin_key" in sig.parameters
        assert sig.parameters["x_admin_key"].default is not inspect.Parameter.empty
