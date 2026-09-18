# backend/routers/app_version.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import logging

import auth
from database import get_db

# Setup logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/app", tags=["app-version"])

# =====================================================
# VERSION CONFIGURATION (HARDCODED - Easy to update)
# =====================================================

# TODO: Update these values when releasing new version
LATEST_VERSION = "1.4.1"
DOWNLOAD_URL = "https://cloud.kapitmas.com/public.php/dav/files/NGHjaJqf2H9MLZW/HR%20Monitoring%20App/HR-Monitoring-app-v.1.4.1.apk" 
CHANGELOG = """• Bug fixes and improvements
• New announcement feature
• New speaker feature
• Performance optimizations
• UI/UX enhancements"""
IS_REQUIRED = False  # False = Optional, True = Forced update
FILE_SIZE_MB = 53.6
MIN_SUPPORTED_VERSION = "1.0.0"  # Versions below this will be forced to update

# =====================================================
# HELPER FUNCTIONS
# =====================================================

def parse_version(version_string: str) -> tuple:

    try:
        parts = version_string.split('.')
        return tuple(int(p) for p in parts)
    except:
        return (0, 0, 0)


def compare_versions(current: str, latest: str) -> dict:

    current_tuple = parse_version(current)
    latest_tuple = parse_version(latest)
    
    if current_tuple >= latest_tuple:
        return {
            "is_update_available": False,
            "update_type": "none"
        }
    
    # Determine update type
    if current_tuple[0] < latest_tuple[0]:
        update_type = "major"  # 1.x.x → 2.x.x
    elif current_tuple[1] < latest_tuple[1]:
        update_type = "minor"  # 1.0.x → 1.1.x
    else:
        update_type = "patch"  # 1.0.0 → 1.0.1
    
    return {
        "is_update_available": True,
        "update_type": update_type
    }


def is_version_below_minimum(version: str, minimum: str) -> bool:
    """Check if version is below minimum supported version"""
    version_tuple = parse_version(version)
    minimum_tuple = parse_version(minimum)
    return version_tuple < minimum_tuple


# =====================================================
# ENDPOINTS
# =====================================================

@router.get("/version")
async def check_app_version(
    current_version: Optional[str] = None,
):
    try:
        response = {
            "success": True,
            "data": {
                "latest_version": LATEST_VERSION,
                "download_url": DOWNLOAD_URL,
                "changelog": CHANGELOG,
                "file_size_mb": FILE_SIZE_MB,
                "min_supported_version": MIN_SUPPORTED_VERSION,
                "checked_at": datetime.now().isoformat()
            }
        }
        
        # If current_version provided, add comparison data
        if current_version:
            comparison = compare_versions(current_version, LATEST_VERSION)
            is_below_minimum = is_version_below_minimum(current_version, MIN_SUPPORTED_VERSION)
            
            response["data"].update({
                "current_version": current_version,
                "is_update_available": comparison["is_update_available"],
                "update_type": comparison["update_type"],
                "is_required": IS_REQUIRED or is_below_minimum or comparison["update_type"] == "major"
            })
            
            logger.info(f"Version check: {current_version} → {LATEST_VERSION} (update_available={comparison['is_update_available']})")
        else:
            # No current version provided, assume update available
            response["data"].update({
                "current_version": "unknown",
                "is_update_available": True,
                "update_type": "unknown",
                "is_required": IS_REQUIRED
            })
        
        return response
        
    except Exception as e:
        logger.error(f"Error checking app version: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error checking app version: {str(e)}"
        )


@router.get("/version/info")
async def get_version_info():
    try:
        return {
            "success": True,
            "data": {
                "latest_version": LATEST_VERSION,
                "min_supported_version": MIN_SUPPORTED_VERSION,
                "has_update": True  # Always true since we don't know client version
            }
        }
    except Exception as e:
        logger.error(f"Error getting version info: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting version info: {str(e)}"
        )
