"""Unit tests for snapshot API endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.model.snapshot_responses import (
    CleanupResponse,
    DatabaseStatsResponse,
    RecentSnapshotsResponse,
    SnapshotHistoryResponse,
    SnapshotResponse,
)
from api.router import snapshot
from util.time_util import TIMEZONE_INFO


@pytest.fixture
def mock_snapshot_service():
    """Create mock SnapshotService."""
    service = AsyncMock()
    return service


@pytest.fixture
def test_app(mock_snapshot_service):
    """
    Create minimal FastAPI app for testing.
    Override dependencies to avoid database initialization.
    """
    app = FastAPI()

    # Override dependency to use mock service
    from api.dependency import get_snapshot_service

    app.dependency_overrides[get_snapshot_service] = lambda: mock_snapshot_service

    # Include the snapshots router
    app.include_router(snapshot.router, prefix="/api/snapshots", tags=["Snapshots"])

    return app


@pytest.fixture
def test_client(test_app):
    """Create FastAPI test client with mocked dependencies."""
    return TestClient(test_app)


@pytest.fixture
def sample_snapshot_response():
    """Sample SnapshotResponse for testing."""
    return SnapshotResponse(
        id=1,
        device_id="IMA_C_5",
        model="IMA_C",
        slave_id="5",
        device_type="dio",
        sampling_ts=datetime(2025, 1, 25, 10, 30, 0, tzinfo=TIMEZONE_INFO),
        created_at=datetime(2025, 1, 25, 10, 30, 1, tzinfo=TIMEZONE_INFO),
        values={"DIn01": 1, "DOut01": 0},
        is_online=1,
    )


class TestGetDeviceHistoryEndpoint:
    """Test GET /api/snapshots/{device_id}/history endpoint."""

    @pytest.mark.asyncio
    async def test_when_valid_request_then_returns_history(
        self, test_client, mock_snapshot_service, sample_snapshot_response
    ):
        """Test that valid request returns device history."""
        # Arrange
        mock_snapshot_service.get_device_history.return_value = SnapshotHistoryResponse(
            device_id="IMA_C_5",
            start_time=datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO),
            end_time=datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO),
            snapshots=[sample_snapshot_response],
            total_count=1,
            limit=100,
            offset=0,
        )

        # Act
        response = test_client.get(
            "/api/snapshots/IMA_C_5/history",
            params={
                "start_ts": 1737734400,
                "end_ts": 1737820799,
            },
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["device_id"] == "IMA_C_5"
        assert data["total_count"] == 1
        assert data["limit"] == 100
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_when_start_after_end_then_returns_400(self, test_client):
        """Test that invalid time range returns 400 error."""
        # Act
        response = test_client.get(
            "/api/snapshots/IMA_C_5/history",
            params={
                "start_ts": 1737820800,  # Later timestamp
                "end_ts": 1737734400,  # Earlier timestamp
            },
        )

        # Assert
        assert response.status_code == 400
        assert "start_ts must be before end_ts" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_when_parameters_specified_then_passes_to_service(self, test_client, mock_snapshot_service):
        """Test that parameter filter is passed to service correctly."""
        # Arrange
        mock_snapshot_service.get_device_history.return_value = SnapshotHistoryResponse(
            device_id="IMA_C_5",
            start_time=datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO),
            end_time=datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO),
            snapshots=[],
            total_count=0,
            limit=100,
            offset=0,
        )

        # Act
        response = test_client.get(
            "/api/snapshots/IMA_C_5/history",
            params={
                "start_ts": 1737734400,
                "end_ts": 1737820799,
                "parameters": "DIn01,DOut01",
            },
        )

        # Assert
        assert response.status_code == 200
        # Verify service was called with parsed parameters
        call_args = mock_snapshot_service.get_device_history.call_args
        assert call_args.kwargs["parameters"] == ["DIn01", "DOut01"]

    @pytest.mark.asyncio
    async def test_when_page_param_provided_then_converts_to_offset(
        self, test_client, mock_snapshot_service, sample_snapshot_response
    ):
        """Test that page parameter is correctly converted to offset."""
        # Arrange
        mock_snapshot_service.get_device_history.return_value = SnapshotHistoryResponse(
            device_id="IMA_C_5",
            start_time=datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO),
            end_time=datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO),
            snapshots=[sample_snapshot_response] * 100,
            total_count=1000,
            limit=100,
            offset=200,  # page 3 with limit 100 → offset 200
        )

        # Act - Request page 3
        response = test_client.get(
            "/api/snapshots/IMA_C_5/history",
            params={
                "start_ts": 1737734400,
                "end_ts": 1737820799,
                "page": 3,
                "limit": 100,
            },
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["page_number"] == 3
        assert data["offset"] == 200

        # Verify service was called with correct offset: (3 - 1) * 100 = 200
        call_args = mock_snapshot_service.get_device_history.call_args
        assert call_args.kwargs["offset"] == 200

    @pytest.mark.asyncio
    async def test_when_page_1_then_offset_is_0(self, test_client, mock_snapshot_service, sample_snapshot_response):
        """Test that page 1 correctly translates to offset 0."""
        # Arrange
        mock_snapshot_service.get_device_history.return_value = SnapshotHistoryResponse(
            device_id="IMA_C_5",
            start_time=datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO),
            end_time=datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO),
            snapshots=[sample_snapshot_response] * 100,
            total_count=1000,
            limit=100,
            offset=0,
        )

        # Act - Explicitly request page 1
        response = test_client.get(
            "/api/snapshots/IMA_C_5/history",
            params={
                "start_ts": 1737734400,
                "end_ts": 1737820799,
                "page": 1,
                "limit": 100,
            },
        )

        # Assert
        assert response.status_code == 200

        # Verify service was called with offset 0: (1 - 1) * 100 = 0
        call_args = mock_snapshot_service.get_device_history.call_args
        assert call_args.kwargs["offset"] == 0

    @pytest.mark.asyncio
    async def test_when_offset_provided_then_overrides_page(
        self, test_client, mock_snapshot_service, sample_snapshot_response
    ):
        """Test that offset parameter overrides page calculation."""
        # Arrange
        mock_snapshot_service.get_device_history.return_value = SnapshotHistoryResponse(
            device_id="IMA_C_5",
            start_time=datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO),
            end_time=datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO),
            snapshots=[sample_snapshot_response] * 100,
            total_count=1000,
            limit=100,
            offset=250,
        )

        # Act - Provide both page and offset
        response = test_client.get(
            "/api/snapshots/IMA_C_5/history",
            params={
                "start_ts": 1737734400,
                "end_ts": 1737820799,
                "page": 2,  # Would be offset 100
                "offset": 250,  # Should use this instead
                "limit": 100,
            },
        )

        # Assert
        assert response.status_code == 200

        # Verify service was called with offset 250, not 100
        call_args = mock_snapshot_service.get_device_history.call_args
        assert call_args.kwargs["offset"] == 250

    @pytest.mark.asyncio
    async def test_when_no_page_provided_then_defaults_to_page_1(
        self, test_client, mock_snapshot_service, sample_snapshot_response
    ):
        """Test that defaults to page 1 when no page parameter provided."""
        # Arrange
        mock_snapshot_service.get_device_history.return_value = SnapshotHistoryResponse(
            device_id="IMA_C_5",
            start_time=datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO),
            end_time=datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO),
            snapshots=[sample_snapshot_response] * 100,
            total_count=1000,
            limit=100,
            offset=0,
        )

        # Act - No page parameter
        response = test_client.get(
            "/api/snapshots/IMA_C_5/history",
            params={
                "start_ts": 1737734400,
                "end_ts": 1737820799,
                # No page or offset params
            },
        )

        # Assert
        assert response.status_code == 200

        # Verify defaults to offset 0 (page 1)
        call_args = mock_snapshot_service.get_device_history.call_args
        assert call_args.kwargs["offset"] == 0

    @pytest.mark.asyncio
    async def test_when_different_limit_then_calculates_offset_correctly(
        self, test_client, mock_snapshot_service, sample_snapshot_response
    ):
        """Test that offset calculation works with different limit values."""
        # Arrange
        mock_snapshot_service.get_device_history.return_value = SnapshotHistoryResponse(
            device_id="IMA_C_5",
            start_time=datetime(2025, 1, 25, 0, 0, 0, tzinfo=TIMEZONE_INFO),
            end_time=datetime(2025, 1, 25, 23, 59, 59, tzinfo=TIMEZONE_INFO),
            snapshots=[sample_snapshot_response] * 50,
            total_count=1000,
            limit=50,
            offset=100,  # page 3 with limit 50 → (3-1)*50 = 100
        )

        # Act - Page 3 with limit 50
        response = test_client.get(
            "/api/snapshots/IMA_C_5/history",
            params={
                "start_ts": 1737734400,
                "end_ts": 1737820799,
                "page": 3,
                "limit": 50,
            },
        )

        # Assert
        assert response.status_code == 200

        # Verify offset = (3 - 1) * 50 = 100
        call_args = mock_snapshot_service.get_device_history.call_args
        assert call_args.kwargs["offset"] == 100
        assert call_args.kwargs["limit"] == 50


class TestGetLatestSnapshotEndpoint:
    """Test GET /api/snapshots/{device_id}/latest endpoint."""

    @pytest.mark.asyncio
    async def test_when_snapshot_exists_then_returns_latest(
        self, test_client, mock_snapshot_service, sample_snapshot_response
    ):
        """Test that latest snapshot is returned when available."""
        # Arrange
        mock_snapshot_service.get_latest_snapshot.return_value = sample_snapshot_response

        # Act
        response = test_client.get("/api/snapshots/IMA_C_5/latest")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["device_id"] == "IMA_C_5"
        assert data["id"] == 1

    @pytest.mark.asyncio
    async def test_when_no_snapshot_exists_then_returns_404(self, test_client, mock_snapshot_service):
        """Test that 404 is returned when no snapshot found."""
        # Arrange
        mock_snapshot_service.get_latest_snapshot.return_value = None

        # Act
        response = test_client.get("/api/snapshots/IMA_C_5/latest")

        # Assert
        assert response.status_code == 404
        assert "No snapshots found" in response.json()["detail"]


class TestGetRecentSnapshotsEndpoint:
    """Test GET /api/snapshots/recent endpoint."""

    @pytest.mark.asyncio
    async def test_when_recent_snapshots_exist_then_returns_list(
        self, test_client, mock_snapshot_service, sample_snapshot_response
    ):
        """Test that recent snapshots are returned from all devices."""
        # Arrange
        mock_snapshot_service.get_recent_snapshots.return_value = RecentSnapshotsResponse(
            minutes=10,
            snapshots=[sample_snapshot_response],
            total_count=1,
        )

        # Act
        response = test_client.get("/api/snapshots/recent", params={"minutes": 10})

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["minutes"] == 10
        assert data["total_count"] == 1


class TestCleanupEndpoint:
    """Test DELETE /api/snapshots/cleanup endpoint (Admin protected)."""

    @pytest.mark.asyncio
    @patch("api.auth._admin_auth")
    async def test_when_valid_admin_key_then_cleanup_succeeds(self, mock_auth, test_client, mock_snapshot_service):
        """Test that cleanup succeeds with valid admin key."""
        # Arrange
        mock_auth.verify_key.return_value = True
        mock_snapshot_service.cleanup_old_snapshots.return_value = CleanupResponse(
            deleted_count=100,
            retention_days=7,
            cutoff_time=datetime(2025, 1, 18, 0, 0, 0, tzinfo=TIMEZONE_INFO),
            status="success",
        )

        # Act
        response = test_client.delete(
            "/api/snapshots/cleanup",
            params={"retention_days": 7},
            headers={"X-Admin-Key": "valid-key"},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 100
        assert data["status"] == "success"

    @pytest.mark.asyncio
    @patch("api.auth._admin_auth")
    async def test_when_invalid_admin_key_then_returns_403(self, mock_auth, test_client):
        """Test that cleanup fails with invalid admin key."""
        # Arrange
        mock_auth.verify_key.return_value = False

        # Act
        response = test_client.delete(
            "/api/snapshots/cleanup",
            params={"retention_days": 7},
            headers={"X-Admin-Key": "invalid-key"},
        )

        # Assert
        assert response.status_code == 403
        assert "Invalid admin key" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_when_no_admin_key_then_returns_422(self, test_client):
        """Test that cleanup fails without admin key header."""
        # Act
        response = test_client.delete(
            "/api/snapshots/cleanup",
            params={"retention_days": 7},
        )

        # Assert
        assert response.status_code == 422  # FastAPI validation error


class TestVacuumEndpoint:
    """Test POST /api/snapshots/vacuum endpoint (Admin protected)."""

    @pytest.mark.asyncio
    @patch("api.auth._admin_auth")
    async def test_when_valid_admin_key_then_vacuum_succeeds(self, mock_auth, test_client, mock_snapshot_service):
        """Test that vacuum succeeds with valid admin key."""
        # Arrange
        mock_auth.verify_key.return_value = True
        mock_snapshot_service.vacuum_database.return_value = {
            "status": "success",
            "message": "Database vacuumed successfully",
        }

        # Act
        response = test_client.post(
            "/api/snapshots/vacuum",
            headers={"X-Admin-Key": "valid-key"},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    @pytest.mark.asyncio
    @patch("api.auth._admin_auth")
    async def test_when_invalid_admin_key_then_returns_403(self, mock_auth, test_client):
        """Test that vacuum fails with invalid admin key."""
        # Arrange
        mock_auth.verify_key.return_value = False

        # Act
        response = test_client.post(
            "/api/snapshots/vacuum",
            headers={"X-Admin-Key": "invalid-key"},
        )

        # Assert
        assert response.status_code == 403


class TestGetDatabaseStatsEndpoint:
    """Test GET /api/snapshots/stats endpoint."""

    @pytest.mark.asyncio
    async def test_when_stats_available_then_returns_statistics(self, test_client, mock_snapshot_service):
        """Test that database statistics are returned correctly."""
        # Arrange
        mock_snapshot_service.get_database_stats.return_value = DatabaseStatsResponse(
            total_count=1000,
            earliest_ts=datetime(2025, 1, 18, 0, 0, 0, tzinfo=TIMEZONE_INFO),
            latest_ts=datetime(2025, 1, 25, 10, 30, 0, tzinfo=TIMEZONE_INFO),
            file_size_bytes=10485760,
            file_size_mb=10.0,
        )

        # Act
        response = test_client.get("/api/snapshots/stats")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 1000
        assert data["file_size_mb"] == 10.0
