"""HTTP endpoints for the prompt library, mounted at /api/prompts."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, StringConstraints

from . import store


class PromptInput(BaseModel):
    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]


router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("")
def list_prompts() -> dict:
    return {"prompts": store.all_prompts(), "categories": store.categories()}


@router.post("", status_code=201)
def add_prompt(body: PromptInput) -> dict:
    return store.add(body.category, body.text)


@router.put("/{number}")
def update_prompt(number: int, body: PromptInput) -> dict:
    try:
        prompt = store.update(number, body.category, body.text)
    except store.ReadOnlyPrompt as e:
        raise HTTPException(400, str(e))
    if prompt is None:
        raise HTTPException(404, f"Prompt #{number} not found")
    return prompt


@router.delete("/{number}", status_code=204)
def delete_prompt(number: int) -> Response:
    """Past runs keep their own copy of the prompt, so their results are unaffected."""
    try:
        deleted = store.delete(number)
    except store.ReadOnlyPrompt as e:
        raise HTTPException(400, str(e))
    if not deleted:
        raise HTTPException(404, f"Prompt #{number} not found")
    return Response(status_code=204)
