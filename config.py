import os
import secrets
from datetime import timedelta

NAME = 'osm-thanos'
VERSION = '0.1'
WEBSITE = 'https://github.com/Zaczero/osm-thanos'
USER_AGENT = f'{NAME}/{VERSION} (+{WEBSITE})'

SECRET = os.getenv('SECRET', None)

if not SECRET:
    SECRET = secrets.token_bytes(32)
    print(f'🚧 Warning: '
          f'Environment variable SECRET is not set. '
          f'Generated a random secret: {SECRET}')

OSM_CLIENT = os.getenv('OSM_CLIENT', None)
OSM_SECRET = os.getenv('OSM_SECRET', None)
OSM_SCOPES = 'read_prefs write_api'

if not OSM_CLIENT or not OSM_SECRET:
    print('🚧 Warning: '
          'Environment variables OSM_CLIENT and/or OSM_SECRET are not set. '
          'You will not be able to authenticate with OpenStreetMap.')

DISABLE_USER_WHITELIST = os.getenv('DISABLE_USER_WHITELIST', '0').lower() in ('1', 'true', 'yes')

REPLICATION_URL = 'https://planet.openstreetmap.org/replication/changesets/'
REPLICATION_FREQUENCY = timedelta(minutes=1)
REPLICATION_SLEEP = timedelta(seconds=30)

OSM_PLANET_URL = 'https://planet.openstreetmap.org/'
OSM_API_URL = 'https://www.openstreetmap.org/api/0.6/'

CHANGESET_MAX_AGE = timedelta(days=180)  # 6 months
