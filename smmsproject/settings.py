"""
Django settings for smmsproject project.

Generated by 'django-admin startproject' using Django 5.0.6.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.0/ref/settings/
"""

from pathlib import Path
import os
from dotenv import load_dotenv
from datetime import timedelta
from celery.schedules import crontab

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# custome user model
AUTH_USER_MODEL = 'smmsapp.CustomUser'

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-!hea+%$-fy)8!6=fu3@7hqrc&i5)2fqu+r0hxj92-$r62lsup@'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

ALLOWED_HOSTS = [
    'localhost', 
    '127.0.0.1', 
    'ditronics.co.tz', 
    'adhimkitchen.ditronics.co.tz', 
    'www.adhimkitchen.ditronics.co.tz',
    'backend1.ditronics.co.tz'
]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3005",
    "http://ditronics.co.tz:8000",
    "http://diatronis.co.tz:3000",
    "https://adhimkitchen.ditronics.co.tz",
    "https://www.adhimkitchen.ditronics.co.tz",
    "https://backend1.ditronics.co.tz"
]

CORS_ALLOW_ALL_ORIGINS = False

CORS_ALLOW_CREDENTIALS = True  # Allow cookies, tokens, and authentication credentials

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

CSRF_TRUSTED_ORIGINS = ["https://31.220.82.177","https://backend1.ditronics.co.tz"]

SECURE_SSL_REDIRECT = False # Redirects all HTTP traffic to HTTPS
SESSION_COOKIE_SECURE = True  # Ensures session cookies are only sent over HTTPS
CSRF_COOKIE_SECURE = True  # Ensures CSRF cookies are only sent over HTTPS

# Load environment variables from .env file
load_dotenv()

# ---- FIREBASE SETUP
FIREBASE_API_KEY = os.getenv('FIREBASE_API_KEY')
FIREBASE_SENDER_ID = os.getenv('FIREBASE_SENDER_ID')
FIREBASE_PROJECT_ID=os.getenv('FIREBASE_PROJECT_ID')

# ---- EMAIL CONDIFURATIONS ----
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST')
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# --- for message engine
CELERY_BROKER_URL = 'redis://localhost:6379/0'  
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'

CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

CELERY_BEAT_SCHEDULE = {
    "send-pending-notifications": {
        "task": "smmsapp.tasks.send_pending_notifications",
        "schedule": crontab(minute="*/5"),  # Run every 5 minutes
    },
}


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'smmsapp',
    'corsheaders',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'smmsproject.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR,"templates")],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'smmsproject.wsgi.application'


# ----- DATABASE LOCAL ------
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'smmsDB',
#         'USER': 'postgres',
#         'PASSWORD': '1234',
#         'HOST': '127.0.0.1',
#         'PORT': '5433',
#     }
# }

# ----- DATABASE PRODUCTION -----
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'smmsdb',
        'USER': 'postgres',
        'PASSWORD': '123456789',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

REST_FRAMEWORK = {
    # Use Django's standard `django.contrib.auth` permissions,
    # or allow read-only access for unauthenticated users.
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.DjangoModelPermissionsOrAnonReadOnly',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 5
}

# ---- ACCESS AND REFRESH TOKEN -----
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),  # access token to 15 min
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),  # refresh token to 1 days
    "ROTATE_REFRESH_TOKENS": True,  # Issue a new refresh token on refresh
    "BLACKLIST_AFTER_ROTATION": True,  # Blacklist old refresh tokens
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Africa/Nairobi'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

# STATIC_URL = 'static/'

MEDIA_URL="/uploads/"
MEDIA_ROOT=os.path.join(BASE_DIR,"uploads")

STATIC_URL="/static/"
STATIC_ROOT=os.path.join(BASE_DIR,"/static")

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
