"""Isolated SQLite settings for local unit tests and migration checks."""
from smmsproject.settings import *  # noqa: F401,F403

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
FEATURES_DEFAULT = {key: True for key in FEATURE_KEYS}
