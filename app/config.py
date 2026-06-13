import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent /'app' / 'config' / '.env')


class Config:
    DB_USER   = os.getenv('DB_USER')
    DB_PASS   = os.getenv('DB_PASS')
    DB_HOST   = os.getenv('DB_HOST')
    DB_NAME   = os.getenv('DB_NAME')
    DB_SCHEMA = os.getenv('DB_SCHEMA')

    # Card ledger lives in the same DB under its own schema.
    LEDGER_SCHEMA = os.getenv('LEDGER_SCHEMA', 'card_ledger')

    SQLALCHEMY_DATABASE_URI = (
        f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False