from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.transliteration import transliterate_mosque_name, classify_mosque_type

router = APIRouter(prefix="/api/v1/transliterate", tags=["transliteration"])


class TransliterationRequest(BaseModel):
    name: str


class TransliterationResponse(BaseModel):
    name_ar: str
    name_en: str
    type: str
    confidence: float


@router.get("", response_model=TransliterationResponse)
def transliterate_get(name: str = Query(..., min_length=1, max_length=200)):
    """Transliterates an Arabic mosque name to English following UNGEGN/GASGI standards."""
    result = transliterate_mosque_name(name)
    return result


@router.post("", response_model=TransliterationResponse)
def transliterate_post(req: TransliterationRequest):
    """Transliterates an Arabic mosque name to English following UNGEGN/GASGI standards."""
    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty.")
    result = transliterate_mosque_name(req.name)
    return result
