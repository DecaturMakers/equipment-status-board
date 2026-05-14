"""Flask extension instances.

All extensions are created here and initialized in the app factory
via ext.init_app(app).
"""

import sqlite3

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()

login_manager.login_view = 'auth.login'


@event.listens_for(Engine, 'connect')
def _sqlite_fk_pragma(dbapi_conn, _):
    # SQLite does not enforce ON DELETE SET NULL unless this pragma is on.
    # MariaDB connections fail the isinstance check and skip.
    if isinstance(dbapi_conn, sqlite3.Connection):
        cursor = dbapi_conn.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()
