from fastapi import APIRouter, HTTPException, Response

from core.media.storage import CACHE_CONTROL, get_object

router = APIRouter(prefix="/v1/media", tags=["media"])


@router.get("/{key:path}")
def media(key: str):
    """Serve a cached image object from MinIO over the same HTTPS origin."""
    obj = get_object(key)
    if obj is None:
        raise HTTPException(status_code=404, detail="not found")
    data, content_type = obj
    return Response(content=data, media_type=content_type, headers={"Cache-Control": CACHE_CONTROL})
