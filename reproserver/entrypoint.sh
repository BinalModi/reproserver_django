#!/bin/sh

if [ "$#" = 0 ]; then
    echo "Usage: [server|debug]" >&2
elif [ "$1" = "server" ]; then
    # PYTHONPATH=. exec python manage.py makemigrations
    # PYTHONPATH=. exec python manage.py migrate
    exec uwsgi \
        --uid appuser \
        --http 0.0.0.0:8000 \
        --module reproserver.wsgi \
        --static-map /static=/usr/src/app/web/static \
        --processes 1 \
        --threads 8
elif [ "$1" = "debug" ]; then
    echo "Running manage.py"
    PYTHONPATH=. exec python manage.py makemigrations
    PYTHONPATH=. exec python manage.py migrate
    PYTHONPATH=. exec python manage.py runserver 0.0.0.0:8000
else
    exec "$@"
fi
