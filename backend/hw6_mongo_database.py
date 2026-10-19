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
MESSAGES_COLLECTION_NAME = "messages"
SUMMARIES_COLLECTION_NAME = "summaries"
EPISODES_COLLECTION_NAME = "episodes"


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    return MongoClient(MONGO_URI, tz_aware=True, serverSelectionTimeoutMS=2000)


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


def get_messages_collection() -> Collection:
    collection = get_mongo_database()[MESSAGES_COLLECTION_NAME]
    _ensure_collection_validation(collection, "messages")
    collection.create_index([("user_id", ASCENDING), ("session_id", ASCENDING), ("created_at", ASCENDING)])
    return collection


def get_summaries_collection() -> Collection:
    collection = get_mongo_database()[SUMMARIES_COLLECTION_NAME]
    _ensure_collection_validation(collection, "summaries")
    collection.create_index([("user_id", ASCENDING), ("scope", ASCENDING), ("created_at", ASCENDING)])
    return collection


def get_episodes_collection() -> Collection:
    collection = get_mongo_database()[EPISODES_COLLECTION_NAME]
    _ensure_collection_validation(collection, "episodes")
    collection.create_index([("user_id", ASCENDING), ("created_at", ASCENDING)])
    return collection


def _ensure_collection_validation(collection: Collection, kind: str = "documents") -> None:
    """Create the collection validator once, or refresh it for an existing one."""

    database = collection.database
    validators = {
        "documents": {
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
        }},
        "messages": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["user_id", "role", "content", "created_at"],
                "properties": {
                    "user_id": {"bsonType": "string", "minLength": 1},
                    "session_id": {"bsonType": ["string", "null"]},
                    "role": {"enum": ["user", "assistant"]},
                    "content": {"bsonType": "string", "minLength": 1},
                    "created_at": {"bsonType": "date"},
                },
            }
        },
        "summaries": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["user_id", "scope", "text", "created_at"],
                "properties": {
                    "user_id": {"bsonType": "string", "minLength": 1},
                    "session_id": {"bsonType": ["string", "null"]},
                    "scope": {"enum": ["session", "user"]},
                    "text": {"bsonType": "string", "minLength": 1},
                    "created_at": {"bsonType": "date"},
                },
            }
        },
        "episodes": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["user_id", "fact", "importance", "embedding", "created_at"],
                "properties": {
                    "user_id": {"bsonType": "string", "minLength": 1},
                    "session_id": {"bsonType": ["string", "null"]},
                    "fact": {"bsonType": "string", "minLength": 1, "maxLength": 500},
                    "importance": {"bsonType": "double", "minimum": 0, "maximum": 1},
                    "embedding": {"bsonType": "array", "items": {"bsonType": "double"}},
                    "created_at": {"bsonType": "date"},
                },
            }
        },
    }
    validator = validators[kind]
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
