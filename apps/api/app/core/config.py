import os
from sqlalchemy.engine import URL
DATABASE_URL=os.getenv('DATABASE_URL') or URL.create('postgresql+psycopg',username=os.getenv('POSTGRES_USER','sports'),password=os.getenv('POSTGRES_PASSWORD','sports'),host=os.getenv('POSTGRES_HOST','localhost'),port=int(os.getenv('POSTGRES_PORT','5432')),database=os.getenv('POSTGRES_DB','sports_ai')).render_as_string(hide_password=False)
EXECUTION_MODE='PAPER' # No paid-wager API exists in this release.
