"""REST API endpoints for snapshot data access."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import verify_admin_key
from api.dependency import get_snapshot_service
from api.model.enums import ResponseStatus
from api.model.responses import BaseResponse
from api.model.snapshot_responses import (
    CleanupResponse,
    DatabaseStatsResponse,
    RecentSnapshotsResponse,
    SnapshotHistoryResponse,
    SnapshotResponse,
)
from api.service.snapshot_service import SnapshotService
from util.time_util import TIMEZONE_INFO

router = APIRouter()
logger = logging.getLogger(__name__)


# ===== Device Snapshot History =====


@router.get(
    "/{device_id}/history",
    response_model=SnapshotHistoryResponse,
    summary="Get device snapshot history",
    description="Query device snapshots with pagination support",
)
async def get_device_history(
    device_id: str,
    start_ts: int = Query(..., description="Start time (Unix timestamp in seconds)", ge=0),
    end_ts: int = Query(..., description="End time (Unix timestamp in seconds)", ge=0),
    parameters: str | None = Query(None, description="Comma-separated parameter names"),
    limit: int = Query(100, ge=1, le=1000, description="Records per page (default: 100, max: 1000)"),
    page: int = Query(1, ge=1, description="Page number (1-indexed, default: 1)"),
    offset: int | None = Query(None, ge=0, description="Advanced: Records to skip (overrides page if provided)"),
    service: SnapshotService = Depends(get_snapshot_service),
) -> SnapshotHistoryResponse:
    """
    Get snapshot history for a specific device with page-based pagination.

    **Pagination (choose one method):**

    1. **Page-based** (recommended):
       - `page`: Page number (1-indexed)
       - `limit`: Records per page
       - Example: `?page=1&limit=100` (first 100 records)
       - Example: `?page=2&limit=100` (records 101-200)

    2. **Offset-based** (advanced):
       - `offset`: Number of records to skip (overrides page)
       - `limit`: Records per page
       - Example: `?offset=250&limit=100` (records 251-350)

    **Response includes pagination metadata:**
    - `total_count`: Total records in time range
    - `page_number`: Current page number
    - `total_pages`: Total number of pages
    - `has_next`: Whether next page exists
    - `has_previous`: Whether previous page exists
    - `next_offset`: Offset for next page (or null)
    - `previous_offset`: Offset for previous page (or null)

    **Examples:**
        # First page (page-based)
        GET /api/snapshots/IMA_C_5/history?start_ts=1737734400&end_ts=1738252800&page=1&limit=100

        # Second page (page-based)
        GET /api/snapshots/IMA_C_5/history?start_ts=1737734400&end_ts=1738252800&page=2&limit=100

        # Custom offset (advanced)
        GET /api/snapshots/IMA_C_5/history?start_ts=1737734400&end_ts=1738252800&offset=250&limit=100

        # With parameter filter
        GET /api/snapshots/IMA_C_5/history?start_ts=1737734400&end_ts=1738252800&page=1&parameters=DIn01,DOut01
    """
    try:
        start_time: datetime = datetime.fromtimestamp(start_ts, tz=TIMEZONE_INFO)
        end_time: datetime = datetime.fromtimestamp(end_ts, tz=TIMEZONE_INFO)

        if start_time > end_time:
            raise HTTPException(400, detail="start_ts must be before end_ts")

        # Calculate offset from page (offset parameter overrides page)
        if offset is not None:
            calculated_offset = offset
        else:
            calculated_offset = (page - 1) * limit

        parameter_list: list[str] | None = [p.strip() for p in parameters.split(",")] if parameters else None

        result: SnapshotHistoryResponse = await service.get_device_history(
            device_id=device_id,
            start_time=start_time,
            end_time=end_time,
            parameters=parameter_list,
            limit=limit,
            offset=calculated_offset,
        )

        return result

    except ValueError as e:
        raise HTTPException(400, detail=f"Invalid timestamp: {e}") from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying device history: {e}", exc_info=True)
        raise HTTPException(500, detail=str(e)) from e


# ===== Latest Snapshot =====


@router.get(
    "/{device_id}/latest",
    response_model=SnapshotResponse,
    summary="Get latest snapshot",
    description="Get the most recent snapshot for a device",
)
async def get_latest_snapshot(
    device_id: str,
    parameters: str | None = Query(None, description="Comma-separated parameter names"),
    service: SnapshotService = Depends(get_snapshot_service),
) -> SnapshotResponse:
    """
    Get the most recent snapshot for a device.

    **Parameters:**
    - `device_id`: Device identifier
    - `parameters`: Optional parameter filter

    **Returns:**
    - Most recent snapshot or 404 if not found

    **Example:**
        GET /api/snapshots/IMA_C_5/latest
        GET /api/snapshots/IMA_C_5/latest?parameters=DIn01,DOut01
    """
    try:
        parameter_list: list[str] | None = [p.strip() for p in parameters.split(",")] if parameters else None

        result: SnapshotResponse | None = await service.get_latest_snapshot(
            device_id=device_id, parameters=parameter_list
        )

        if result is None:
            raise HTTPException(status_code=404, detail=f"No snapshots found for device {device_id}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting latest snapshot: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get latest snapshot: {str(e)}") from e


# ===== Recent Snapshots =====


@router.get(
    "/recent",
    response_model=RecentSnapshotsResponse,
    summary="Get recent snapshots",
    description="Get recent snapshots from all devices",
)
async def get_recent_snapshots(
    minutes: int = Query(10, ge=1, le=1440, description="Time window in minutes"),
    parameters: str | None = Query(None, description="Comma-separated parameter names"),
    service: SnapshotService = Depends(get_snapshot_service),
) -> RecentSnapshotsResponse:
    """
    Get recent snapshots from all devices in the last N minutes.

    **Parameters:**
    - `minutes`: Time window (1-1440 minutes, default: 10)
    - `parameters`: Optional parameter filter

    **Returns:**
    - Recent snapshots from all devices

    **Example:**
        GET /api/snapshots/recent?minutes=10
        GET /api/snapshots/recent?minutes=30&parameters=DIn01
    """
    try:
        parameter_list: list[str] | None = [p.strip() for p in parameters.split(",")] if parameters else None

        result: RecentSnapshotsResponse = await service.get_recent_snapshots(minutes=minutes, parameters=parameter_list)

        return result

    except Exception as e:
        logger.error(f"Error getting recent snapshots: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get recent snapshots: {str(e)}") from e


# ===== Database Statistics =====


@router.get(
    "/stats",
    response_model=DatabaseStatsResponse,
    summary="Get database statistics",
    description="Get snapshot database stats (size, counts, timestamps)",
)
async def get_database_stats(
    service: SnapshotService = Depends(get_snapshot_service),
) -> DatabaseStatsResponse:
    """
    Get snapshot database statistics.

    **Returns:**
    - Total count, file size, timestamp range

    **Use this to monitor background job:**
    - `earliest_ts` should be within retention period (default 7 days)
    - `file_size_mb` should decrease after VACUUM runs
    - `total_count` tracks data accumulation rate

    **Example:**
        GET /api/snapshots/stats
    """
    try:
        result: DatabaseStatsResponse = await service.get_database_stats()
        return result

    except Exception as e:
        logger.error(f"Error getting database stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get database stats: {str(e)}") from e


# ===== Admin Operations (Protected) =====


@router.delete(
    "/cleanup",
    response_model=CleanupResponse,
    summary="Manual cleanup (Admin only)",
    description="""
    **Admin Operation - Requires X-Admin-Key header**
    
    Delete snapshots older than specified retention period.
    
    **Note:** Normally handled by background job every 6 hours.
    Use only for:
    - Emergency disk space issues
    - Testing/development
    - One-time cleanup with custom retention
    """,
)
async def cleanup_old_snapshots(
    retention_days: int = Query(..., ge=1, le=365, description="Keep snapshots newer than N days"),
    service: SnapshotService = Depends(get_snapshot_service),
    _: None = Depends(verify_admin_key),
) -> CleanupResponse:
    """
    Delete old snapshots based on retention policy.

    **Authentication:**
    - Requires `X-Admin-Key` header with valid admin key
    - Set via environment variable: `TALOS_ADMIN_KEY`

    **Parameters:**
    - `retention_days`: Keep snapshots newer than this (1-365 days)

    **Returns:**
    - Cleanup operation result

    **Example:**
        curl -X DELETE "http://localhost:8000/api/snapshots/cleanup?retention_days=7" \\
        -H "X-Admin-Key: your-secret-key"
    """
    try:
        logger.info(f"[Admin] Manual cleanup triggered: retention_days={retention_days}")
        result: CleanupResponse = await service.cleanup_old_snapshots(retention_days=retention_days)
        return result

    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}") from e


@router.post(
    "/vacuum",
    summary="Vacuum database (Admin only)",
    description="""
    **Admin Operation - Requires X-Admin-Key header**
    
    Run VACUUM to reclaim disk space and optimize database.
    
    **Note:** Normally handled by background job every 7 days.
    Use only for:
    - After large cleanup operations
    - Performance optimization
    - Testing/development
    
    This operation may take time on large databases.
    """,
)
async def vacuum_database(
    service: SnapshotService = Depends(get_snapshot_service),
    _: None = Depends(verify_admin_key),
) -> BaseResponse:
    """
    Run VACUUM operation to reclaim disk space.

    **Authentication:**
    - Requires `X-Admin-Key` header with valid admin key

    **Note:** This operation may take time on large databases.

    **Returns:**
    - Operation status

    **Example:**
        curl -X POST "http://localhost:8000/api/snapshots/vacuum" \\
        -H "X-Admin-Key: your-secret-key"
    """
    try:
        logger.info("[Admin] Manual VACUUM triggered")
        result: dict[str, str] = await service.vacuum_database()

        return BaseResponse(
            status=ResponseStatus.SUCCESS if result["status"] == ResponseStatus.SUCCESS.value else ResponseStatus.ERROR,
            message=result["message"],
        )

    except Exception as e:
        logger.error(f"VACUUM failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"VACUUM failed: {str(e)}") from e
