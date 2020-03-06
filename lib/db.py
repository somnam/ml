import json
from datetime import datetime
from sqlite3 import Connection as SQLite3Connection
from sqlalchemy import engine_from_config, MetaData, Column, TypeDecorator
from sqlalchemy.types import CHAR, DateTime, Integer, Text
from sqlalchemy.event import listens_for
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager
from hashlib import md5
from lib.config import Config


Model = declarative_base(
    metadata=MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s"
    })
)


class Handler:
    # Check existence of configuration when module is imported.
    _sqlalchemy_url = Config().get("db", "sqlalchemy.url")

    def __init__(self) -> None:
        @listens_for(Engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore
            if isinstance(dbapi_connection, SQLite3Connection):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON;")
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.close()

        # Connector pool class must be changed for multithreaded connections.
        self.engine = engine_from_config(configuration=Config()['db'],
                                         connect_args={'check_same_thread': False},
                                         poolclass=StaticPool)
        self.session_factory = sessionmaker(bind=self.engine)
        self.scoped_session = scoped_session(self.session_factory)

    def create_all(self):
        Model.metadata.create_all(self.engine, checkfirst=True)

    @contextmanager
    def session_scope(self):
        session = self.scoped_session()

        try:
            yield session
            session.commit()
        except (DBAPIError, SQLAlchemyError):
            session.rollback()
            raise
        finally:
            session.close()


class JsonType(TypeDecorator):
    """Enables JSON storage for sqlite with no extensions."""
    impl = Text

    def process_bind_param(self, value, dialect):
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None


class BookShelfInfoModel(Model):
    __tablename__ = 'book_shelf_info'

    url_md5 = Column(CHAR(32), primary_key=True)
    book_info = Column(JsonType)
    created = Column(DateTime, nullable=False, default=datetime.utcnow)

    @staticmethod
    def md5_from_url(url):
        return md5(url.encode('utf-8')).hexdigest()



class BookLibraryAvailabilityModel(Model):
    __tablename__ = 'book_library_availability'

    library_id = Column(Integer, primary_key=True)
    book_md5 = Column(CHAR(32), primary_key=True)
    search_results = Column(JsonType)
    created = Column(DateTime, nullable=False, default=datetime.utcnow)

    @staticmethod
    def md5_from_book(book):
        book_md5 = md5()
        for field in ('title', 'author', 'isbn'):
            book_md5.update((book.get(field) or '').encode('utf-8'))
        return book_md5.hexdigest()
