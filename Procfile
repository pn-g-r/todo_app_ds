web: python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn todoproject.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --log-file -
