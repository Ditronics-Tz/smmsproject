import csv
from pathlib import Path

from django.conf import settings

from .base import BaseSchoolAdapter


class CSVSchoolAdapter(BaseSchoolAdapter):
    """Read three UTF-8 CSV extracts whose first row contains field names."""

    def _read(self, setting_name):
        configured_path = getattr(settings, setting_name, "")
        if not configured_path:
            return []
        path = Path(configured_path).expanduser()
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            return list(csv.DictReader(source))

    def fetch_students(self):
        return self._read("SCHOOL_SYSTEM_STUDENTS_CSV")

    def fetch_parents(self):
        return self._read("SCHOOL_SYSTEM_PARENTS_CSV")

    def fetch_classes(self):
        return self._read("SCHOOL_SYSTEM_CLASSES_CSV")
