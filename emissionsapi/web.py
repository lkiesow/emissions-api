# Copyright 2019, The Emissions API Developers
# https://emissions-api.org
# This software is available under the terms of an MIT license.
# See LICENSE fore more information.
"""Web application to deliver the data stored in the database via an API to
the users.
"""
import logging
import dateutil.parser

import connexion
import geojson
from flask import redirect

import emissionsapi.db
from emissionsapi.country_bounding_boxes import country_bounding_boxes
from emissionsapi.utils import bounding_box_to_wkt, polygon_to_wkt, \
    RESTParamError

# Logger
logger = logging.getLogger(__name__)


def parse_date(*keys):
    """Function wrapper replacing string date arguments with
    datetime.datetime

    :param keys: keys to be parsed and replaced
    :type keys: list
    :return: wrapper function
    :rtype: func
    """
    def wrap(f):
        def wrapped_f(*args, **kwargs):
            for key in keys:
                logger.debug(f'Try to parse {key} as date')
                date = kwargs.get(key)
                if date is None:
                    continue
                try:
                    kwargs[key] = dateutil.parser.parse(date)
                except ValueError:
                    return f'Invalid {key}', 400
            return f(*args, **kwargs)
        return wrapped_f
    return wrap


@parse_date('begin', 'end')
@emissionsapi.db.with_session
def get_data(session, country=None, geoframe=None, polygon=None,
             begin=None, end=None, limit=None, offset=None):
    """Get data in GeoJSON format.

    :param session: SQLAlchemy session
    :type session: sqlalchemy.orm.session.Session
    :param country: 'country' url parameter
    :type country: string
    :param geoframe: 'geoframe' url parameter
    :type geoframe: list
    :param polygon: 'polygon' url parameter
    :type polygon: list
    :return: Feature Collection with requested Points
    :rtype: geojson.FeatureCollection
    """
    wkt_polygon = None
    # Parse parameter geoframe
    if geoframe is not None:
        try:
            wkt_polygon = bounding_box_to_wkt(*geoframe)
        except ValueError:
            return 'Invalid geoparam', 400
    # parse parameter country
    elif country is not None:
        if country not in country_bounding_boxes:
            return 'Unknown country code.', 400
        wkt_polygon = bounding_box_to_wkt(*country_bounding_boxes[country][1])
    # parse parameter polygon
    elif polygon is not None:
        try:
            wkt_polygon = polygon_to_wkt(polygon)
        except RESTParamError as err:
            return str(err), 400

    # Init feature list
    features = []
    # Iterate through database query
    query = emissionsapi.db.get_points(
        session, polygon=wkt_polygon, begin=begin, end=end)
    # Apply limit and offset
    query = emissionsapi.db.limit_offset_query(
        query, limit=limit, offset=offset)

    for obj, longitude, latitude in query:
        # Create and append single features.
        features.append(geojson.Feature(
            geometry=geojson.Point((longitude, latitude)),
            properties={
                "carbonmonoxide": obj.value,
                "timestamp": obj.timestamp
            }))
    # Create feature collection from gathered points
    feature_collection = geojson.FeatureCollection(features)
    return feature_collection


@parse_date('begin', 'end')
@emissionsapi.db.with_session
def get_daily(session, country=None, geoframe=None, polygon=None,
              begin=None, end=None, limit=None, offset=None):
    wkt_polygon = None
    # Parse parameter geoframe
    if geoframe is not None:
        try:
            wkt_polygon = bounding_box_to_wkt(*geoframe)
        except ValueError:
            return 'Invalid geoparam', 400
    # parse parameter country
    elif country is not None:
        if country not in country_bounding_boxes:
            return 'Unknown country code.', 400
        wkt_polygon = bounding_box_to_wkt(*country_bounding_boxes[country][1])
    # parse parameter polygon
    elif polygon is not None:
        try:
            wkt_polygon = polygon_to_wkt(polygon)
        except RESTParamError as err:
            return str(err), 400

    query = emissionsapi.db.get_daily(
        session, polygon=wkt_polygon, begin=begin, end=end)
    # Apply limit and offset
    query = emissionsapi.db.limit_offset_query(
        query, limit=limit, offset=offset)
    return [{'value': {
                'count': count,
                'average': avg,
                'standard deviation': stddev,
                'min': min_val,
                'max': max_val},
            'time': {
                'start': min_time,
                'end': max_time,
                'day': day.strftime("%Y-%m-%d")}}
            for count, avg, stddev, min_val, max_val, min_time, max_time, day
            in query]


# Create connexion app
app = connexion.App(__name__)

# Add swagger description to api
app.add_api('openapi.yml', )

# Create app to run with wsgi server
application = app.app


@app.route('/')
def home():
    """Redirect / to the swagger ui

    :return: Redirect response
    :rtype: werkzeug.wrappers.response.Response
    """
    return redirect('/ui', code=302)


def entrypoint():
    """Entrypoint for running this as a module or from the binary.
    It starts the Connexion Debug Server. It is not meant to be used for
    production, but only during the development.
    """
    logger.info("Starting the Connexion Debug Server")
    app.run(host='127.0.0.1')


if __name__ == "__main__":
    entrypoint()
