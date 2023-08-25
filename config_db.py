import os

import pymongo
from motor.core import AgnosticCollection
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import IndexModel

from config import NAME

MONGO_HOST = os.getenv('MONGO_HOST', '127.0.0.1')
MONGO_PORT = int(os.getenv('MONGO_PORT', '27017'))
MONGO_CLIENT = AsyncIOMotorClient(f'mongodb://{MONGO_HOST}:{MONGO_PORT}')
_mongo_db = MONGO_CLIENT[NAME]

STATE_COLLECTION: AgnosticCollection = _mongo_db['state']
CHANGESET_COLLECTION: AgnosticCollection = _mongo_db['changeset']

async def setup_mongo():
    await CHANGESET_COLLECTION.create_indexes([
        IndexModel([('@id', pymongo.ASCENDING)], unique=True),
        IndexModel([('@closed_at', pymongo.ASCENDING)]),
        IndexModel([('tags.$**', pymongo.ASCENDING)]),
    ])
