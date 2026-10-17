from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from backend.hw6_document_schemas import DocumentInput, DocumentResponse
from backend.hw6_mongo_database import get_document_collection


router = APIRouter(prefix="/api/documents", tags=["MongoDB documents"])


def _collection_or_503() -> Collection:
    try:
        return get_document_collection()
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="MongoDB is unavailable") from exc


def _object_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail="Document ID must be a valid ObjectId")
    return ObjectId(value)


def _to_response(document: dict) -> dict:
    document["id"] = str(document.pop("_id"))
    return document


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentInput) -> dict:
    collection = _collection_or_503()
    now = datetime.now(timezone.utc)
    document = {**payload.model_dump(), "created_at": now, "updated_at": now}
    try:
        result = collection.insert_one(document)
        document["_id"] = result.inserted_id
        return _to_response(document)
    except PyMongoError as exc:
        raise HTTPException(status_code=500, detail="Could not create document") from exc


@router.get("", response_model=list[DocumentResponse])
def list_documents() -> list[dict]:
    collection = _collection_or_503()
    try:
        return [_to_response(item) for item in collection.find().sort("created_at", -1)]
    except PyMongoError as exc:
        raise HTTPException(status_code=500, detail="Could not retrieve documents") from exc


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str) -> dict:
    collection = _collection_or_503()
    try:
        document = collection.find_one({"_id": _object_id(document_id)})
    except PyMongoError as exc:
        raise HTTPException(status_code=500, detail="Could not retrieve document") from exc
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_response(document)


@router.put("/{document_id}", response_model=DocumentResponse)
def update_document(document_id: str, payload: DocumentInput) -> dict:
    collection = _collection_or_503()
    object_id = _object_id(document_id)
    now = datetime.now(timezone.utc)
    try:
        result = collection.update_one(
            {"_id": object_id},
            {"$set": {**payload.model_dump(), "updated_at": now}},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Document not found")
        document = collection.find_one({"_id": object_id})
    except HTTPException:
        raise
    except PyMongoError as exc:
        raise HTTPException(status_code=500, detail="Could not update document") from exc
    return _to_response(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str) -> None:
    collection = _collection_or_503()
    try:
        result = collection.delete_one({"_id": _object_id(document_id)})
    except PyMongoError as exc:
        raise HTTPException(status_code=500, detail="Could not delete document") from exc
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
