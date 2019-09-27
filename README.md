# emissions-api
The main repository for the Emissions API

## Prerequisites

* numpy
* gdal (C Library and Python bindings)
* (SQLAlchemy)[https://www.sqlalchemy.org/]
* (GeoAlchemy2)[https://github.com/geoalchemy/geoalchemy2]
* (psycopg2)[https://pypi.org/project/psycopg2/]

## Installation

Note that you do not need to install this project to run the different parts of it. But you can install this tool and its binaries in your environment by executing

```
python setup.py install
```

## Execute

To execute the programs in this project run

* **download**: `python -m emissionsapi.download`
* **preprocess**: `python -m emissionsapi.preprocess`
* **web**: `python -m emissionsapi.web`

or execute the binaries after installation

* **download**: `emissionsapi-download`
* **preprocess**: `emissionsapi-preprocess`
* **web**: `emissionsapi-web`
