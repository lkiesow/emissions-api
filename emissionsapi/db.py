# Copyright 2019, The Emissions API Developers
# https://emissions-api.org
# This software is available under the terms of an MIT license.
# See LICENSE fore more information.
"""Database layer for the Emmission API.
"""

from functools import wraps
import logging

import sqlalchemy
from sqlalchemy import and_, or_, create_engine, Column, DateTime, Integer, \
        Float, String, PickleType
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

import geoalchemy2

from emissionsapi.config import config

# Logger
logger = logging.getLogger(__name__)

# Database uri as described in
# https://docs.sqlalchemy.org/en/13/core/engines.html#database-urls
# Retrieved as environment variable.
database = config('database') or 'postgresql://user:user@localhost/db'

# Global session variable. Set on initialization.
__session__ = None

# Base Class of all ORM objects.
Base = declarative_base()


class File(Base):
    """ORM object for the nc files.
    """
    __tablename__ = 'file'
    filename = Column(String, primary_key=True)
    """Name of processed data file"""


class Cache(Base):
    """ORM object for the request cache
    """
    __tablename__ = 'cache'
    request = Column(String, primary_key=True)
    """Primary key identifying the request"""
    begin = Column(DateTime)
    """Begin of the time interval involved in this request (used for
    efficiently invalidating caches)
    """
    end = Column(DateTime)
    """End of the time interval involved in this request (used for efficiently
    invalidating caches)
    """
    response = Column(PickleType)
    """Cached response"""

    @classmethod
    def invalidate(cache, session, earliest, latest):
        """Invalidates/deletes all cached responses in the given interval to
        ensure these data is generated anew. This is meant to be run when the
        underlying data for this interval changes, for instance since new data
        has been imported.

        :param session: SQLAlchemy Session
        :type session: sqlalchemy.orm.session.Session
        :param earliest: Earliest time of the interval to invalidate
        :type earliest: datetime.datetime
        :param latest: Latest time of the interval to invalidate
        :type latest: datetime.datetime

        """
        logger.debug('Invalidating cache in interval %s..%s',
                     earliest.isoformat(), latest.isoformat())
        session.query(cache)\
               .filter(and_(or_(cache.begin.is_(None),
                                cache.begin <= latest),
                            or_(cache.end.is_(None),
                                cache.end > earliest)))\
               .delete()
        session.commit()


class Carbonmonoxide(Base):
    """ORM object for carbon monoxide point
    """
    __tablename__ = 'carbonmonoxide'
    id = Column(Integer, primary_key=True)
    """ Data sample identifier (primary key)"""
    value = Column(Float)
    """Carbon monoxide value"""
    timestamp = Column(DateTime)
    """Timestamp of measurement"""
    geom = Column(geoalchemy2.Geometry(geometry_type="POINT"))
    """Location (PostGis type)"""

    def __init__(self, value, longitude, latitude, timestamp):
        self.value = value
        self.timestamp = timestamp
        self.geom = geoalchemy2.elements.WKTElement(
            f"POINT({longitude} {latitude})")


def with_session(f):
    """Wrapper for f to make a SQLAlchemy session present within the function

    :param f: Function to call
    :type f: Function
    :raises e: Possible exception of f
    :return: Result of f
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Get new session
        session = get_session()
        try:
            # Call f with the session and all the other arguments
            result = f(session, *args, **kwargs)
        except Exception as e:
            # Rollback session, something bad happend.
            session.rollback()
            session.close()
            raise e
        # Close session and return the result of f
        session.close()
        return result
    return decorated


def get_session():
    """Get a new session.

    Lazy load the database connection and create the tables.

    Returns:
        sqlalchemy.orm.session.Session -- SQLAlchemy Session object
    """
    global __session__
    # Create database connection, tables and Sessionmaker if neccessary.
    if not __session__:
        Engine = create_engine(
            database, echo=logger.getEffectiveLevel() == logging.DEBUG)
        __session__ = sessionmaker(bind=Engine)
        Base.metadata.create_all(Engine)

    # Return new session object
    return __session__()


def insert(session, data, table_name=Carbonmonoxide.__table__.name):
    '''Batch insert data into the database using PostGIS specific functions.

    :param session: SQLAlchemy Session
    :type session: sqlalchemy.orm.session.Session
    :param data: List of dictionaries with entries for timestamp, longitude,
                 latitude and value
    :type data: list
    :param table_name: Name of database table to insert data into, defaults to
                       table for carbon monoxide values.
    :type table_name: str
    '''
    statement = text(f'insert into {table_name} '
                     '(value, timestamp, geom) '
                     'values (:value, :timestamp, '
                     '        ST_MakePoint(:longitude, :latitude))')
    session.execute(statement, data)


def get_points(session):
    """Get all points.

    :param session: SQLAlchemy Session
    :type session: sqlalchemy.orm.session.Session
    :return: SQLAlchemy Query with tuple of Carbonmonoxide object,
             longitude and latitude.
    :rtype: sqlalchemy.orm.query.Query
    """
    return session.query(
        Carbonmonoxide,
        Carbonmonoxide.geom.ST_X(),
        Carbonmonoxide.geom.ST_Y())


def get_averages(session):
    """Get daily averages of all points.

    :param session: SQLAlchemy Session
    :type session: sqlalchemy.orm.session.Session
    :return: SQLAlchemy Query with tuple of the daily carbon monoxide average,
             the maximal timestamp the minimal timestamp and the timestamp
             truncated by day.
    :rtype: sqlalchemy.orm.query.Query
    """
    day = sqlalchemy.func.date(Carbonmonoxide.timestamp)
    return session.query(
        sqlalchemy.func.avg(Carbonmonoxide.value),
        sqlalchemy.func.max(Carbonmonoxide.timestamp),
        sqlalchemy.func.min(Carbonmonoxide.timestamp),
        day).group_by(day)


def get_statistics(session, interval_length='day'):
    """Get statistical data like amount, average, min, or max values for a
    specified time interval. Optionally, time and location filters can be
    applied.

    :param session: SQLAlchemy Session
    :type session: sqlalchemy.orm.session.Session
    :param interval_length: Length of the time interval for which data is being
                            aggregated as accepted by PostgreSQL's date_trunc_
                            function like ``day`` or ``week``.
    :type interval_length: str
    :return: SQLAlchemy Query requesting the following statistical values for
             the specified time interval:

             - number of considered measurements
             - average carbon monoxide value
             - minimum carbon monoxide value
             - maximum carbon monoxide value
             - time of the first measurement
             - time of the last measurement
             - start of the interval
    :rtype: sqlalchemy.orm.query.Query

    .. _date_trunc: https://postgresql.org/docs/9.1/functions-datetime.html
    """
    interval = sqlalchemy.func.date_trunc(interval_length,
                                          Carbonmonoxide.timestamp)
    return session.query(
        sqlalchemy.func.count(Carbonmonoxide.value),
        sqlalchemy.func.avg(Carbonmonoxide.value),
        sqlalchemy.func.stddev(Carbonmonoxide.value),
        sqlalchemy.func.min(Carbonmonoxide.value),
        sqlalchemy.func.max(Carbonmonoxide.value),
        sqlalchemy.func.min(Carbonmonoxide.timestamp),
        sqlalchemy.func.max(Carbonmonoxide.timestamp),
        interval).group_by(interval)


def filter_query(query, wkt=None, distance=None, begin=None, end=None):
    """Filter query by time and location.

    :param query: SQLAlchemy Query
    :type query: sqlalchemy.orm.Query
    :param wkt: WKT Element specifying an area in which to search for points,
                defaults to None.
    :type wkt: geoalchemy2.WKTElement, optional
    :param distance: Distance as defined in PostGIS' ST_DWithin_ function.
    :type distance: float, optional
    :param begin: Get only points after this timestamp, defaults to None
    :type begin: datetime.datetime, optional
    :param end: Get only points before this timestamp, defaults to None
    :type end: datetime.datetime, optional
    :return: SQLAlchemy Query filtered by time and location.
    :rtype: sqlalchemy.orm.query.Query

    .. _ST_DWithin: https://postgis.net/docs/ST_DWithin.html
    """
    # Filter by WKT
    if wkt is not None:
        if distance is not None:
            query = query.filter(geoalchemy2.func.ST_DWITHIN(
                Carbonmonoxide.geom, wkt, distance))
        else:
            query = query.filter(geoalchemy2.func.ST_WITHIN(
                Carbonmonoxide.geom, wkt))

    # Filter for points after the time specified as begin
    if begin is not None:
        query = query.filter(begin <= Carbonmonoxide.timestamp)

    # Filter for points before the time specified as end
    if end is not None:
        query = query.filter(end > Carbonmonoxide.timestamp)

    return query


def limit_offset_query(query, limit=None, offset=None):
    """Apply limit and offset to the query.

    :param query: SQLAlchemy Query
    :type query: sqlalchemy.orm.Query
    :param limit: Limit number of Items returned, defaults to None
    :type limit: int, optional
    :param offset: Specify the offset of the first hit to return,
                   defaults to None
    :type offset: int, optional
    :return: SQLAlchemy Query with limit and offset applied.
    :rtype: sqlalchemy.orm.query.Query
    """
    # Apply limit
    if limit is not None:
        query = query.limit(limit)

    # Apply offset
    if offset is not None:
        query = query.offset(offset)
    return query
