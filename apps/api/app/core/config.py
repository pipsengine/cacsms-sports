import os
DATABASE_URL=os.getenv('DATABASE_URL','postgresql+psycopg://sports:sports@localhost:5432/sports_ai')
EXECUTION_MODE='PAPER' # No paid-wager API exists in this release.
