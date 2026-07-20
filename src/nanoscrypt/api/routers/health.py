from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["system"])


@router.get("")
def health_check():
    """
    Check the health status of the API.
    Returns a simple JSON response indicating the service is running.
    """
    return {"status": "ok", "service": "nanoscrypt-api"}
