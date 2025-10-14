# Use Python 3.13 Alpine as the base image
FROM python:3.13-alpine

# Set working directory
WORKDIR /app

# Add edge/community repository for additional packages and update apk
RUN echo "http://dl-cdn.alpinelinux.org/alpine/edge/community" >> /etc/apk/repositories && \
    apk update

# Install system dependencies for WeasyPrint
RUN apk add --no-cache \
    pango \
    cairo \
    gdk-pixbuf \
    libffi-dev \
    glib-dev \
    && apk add --no-cache --virtual .build-deps \
    build-base \
    python3-dev \
    && pip install --no-cache-dir weasyprint \
    && apk del .build-deps

# Copy requirements file
COPY requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose port 8000 (default for Django development server)
EXPOSE 8000

# Start the Django development server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]