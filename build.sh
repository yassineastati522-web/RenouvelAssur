#!/usr/bin/env bash
set -o errexit

python -m pip install --require-hashes -r requirements.lock
python manage.py collectstatic --noinput
python manage.py migrate --noinput
