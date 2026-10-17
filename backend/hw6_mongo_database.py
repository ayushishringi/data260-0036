"""MongoDB connection and collection setup for the HW6 document API."""

from __future__ import annotations

import os
from functools import lru_cache

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database


MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "s0036_doc")
MONGO_COLLECTION_NAME = os.getenv(
    "MONGO_COLLECTION_NAME", "vulnerability_documents"
)


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)


def get_mongo_database() -> Database:
    return get_mongo_client()[MONGO_DB_NAME]


def get_document_collection() -> Collection:
    collection = get_mongo_database()[MONGO_COLLECTION_NAME]
    _ensure_collection_validation(collection)
    collection.create_index([("created_at", ASCENDING)])
    return collection


def ping_mongo() -> None:
    """Raise the PyMongo exception when MongoDB is unavailable."""

    get_mongo_client().admin.command("ping")


def _ensure_collection_validation(collection: Collection) -> None:
    """Create the collection validator once, or refresh it for an existing one."""

    database = collection.database
    validator = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "title", "severity", "status", "discovered_at",
                "created_at", "updated_at",
            ],
            "properties": {
                "title": {"bsonType": "string", "minLength": 1, "maxLength": 100},
                "description": {"bsonType": ["string", "null"]},
                "severity": {"enum": ["critical", "high", "medium", "low"]},
                "status": {"enum": ["open", "triaged", "resolved", "ignored"]},
                "discovered_at": {"bsonType": "date"},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
            },
        }
    }
    try:
        database.command({
            "collMod": collection.name,
            "validator": validator,
            "validationLevel": "strict",
            "validationAction": "error",
        })
    except Exception as exc:
        if getattr(exc, "code", None) != 26:
            raise
        database.create_collection(
            collection.name,
            validator=validator,
            validationLevel="strict",
            validationAction="error",
        )
