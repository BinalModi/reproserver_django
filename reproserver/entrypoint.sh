#!/bin/sh

if [ "$#" = 0 ]; then
    echo "Usage: [server|debug]" >&2
elif [ "$1" = "server" ]; then
    exec uwsgi \
        --uid appuser \
        --http 0.0.0.0:8000 \
        --module web.wsgi \
        --static-map /static=/usr/src/app/web/static \
        --processes 1 \
        --threads 8
elif [ "$1" = "debug" ]; then
    PYTHONPATH=. exec python manage.py runserver
else
    exec "$@"
fi
