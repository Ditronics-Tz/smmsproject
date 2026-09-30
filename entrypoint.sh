#!/bin/sh
set -e

echo "Starting entrypoint script..."

# Path of the setup-done flag. Overridable for Podman named-volume setups.
# NOTE: worker/beat containers only see this file when they share /app with
# web (bind mount). With isolated filesystems they fall back to `migrate
# --check` after SETUP_WAIT_TIMEOUT iterations (see below).
SETUP_FLAG=${SETUP_FLAG:-/app/.entrypoint-setup-done}
SETUP_WAIT_TIMEOUT=${SETUP_WAIT_TIMEOUT:-120}

case "$*" in
  *runserver*|*gunicorn*)
    # Web service owns one-time setup. Remove any stale flag first so
    # workers started at the same time do not mistake it for fresh setup.
    rm -f "$SETUP_FLAG"

    # Wait for PostgreSQL to be ready
    if [ "$DATABASE" = "postgres" ]; then
        echo "Waiting for PostgreSQL to be ready..."

        while ! nc -z $DB_HOST $DB_PORT; do
          sleep 0.1
        done

        echo "PostgreSQL is ready!"
    fi

    # Run database migrations
    echo "Running database migrations..."
    python manage.py migrate --noinput

    # Collect static files
    echo "Collecting static files..."
    python manage.py collectstatic --noinput --clear

    # Create superuser if it doesn't exist (optional, for dev only)
    if [ "$DJANGO_SUPERUSER_USERNAME" ] && [ "$DJANGO_SUPERUSER_PASSWORD" ] && [ "$DJANGO_SUPERUSER_EMAIL" ]; then
        echo "Creating superuser..."
        python manage.py shell << END
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='$DJANGO_SUPERUSER_USERNAME').exists():
    User.objects.create_superuser('$DJANGO_SUPERUSER_USERNAME', '$DJANGO_SUPERUSER_EMAIL', '$DJANGO_SUPERUSER_PASSWORD')
    print('Superuser created successfully')
else:
    print('Superuser already exists')
END
    fi

    echo "Setup complete."
    touch "$SETUP_FLAG" || echo "WARNING: could not write setup flag $SETUP_FLAG; workers will use migrate --check fallback."
    ;;
  *)
    # Worker/beat services: wait for web to finish setup instead of
    # racing it on migrate + collectstatic --clear.
    if [ "$DATABASE" = "postgres" ]; then
        echo "Waiting for PostgreSQL to be ready..."

        while ! nc -z $DB_HOST $DB_PORT; do
          sleep 0.1
        done

        echo "PostgreSQL is ready!"
    fi

    echo "Waiting for web setup ($SETUP_FLAG)..."
    i=0
    while [ ! -f "$SETUP_FLAG" ]; do
      i=$((i+1))
      if [ "$i" -gt "$SETUP_WAIT_TIMEOUT" ]; then
        echo "Setup flag not visible (isolated filesystem?); falling back to migration check."
        break
      fi
      sleep 5
    done

    echo "Web setup detected, verifying migrations..."
    j=0
    while ! python manage.py migrate --check 2>/dev/null; do
      j=$((j+1))
      if [ "$j" -gt 24 ]; then
        echo "Migrations not complete; exiting for retry."
        exit 1
      fi
      sleep 5
    done
    echo "Migrations verified, continuing."
    ;;
esac

echo "Starting application..."

# Execute the command passed to docker run
exec "$@"
