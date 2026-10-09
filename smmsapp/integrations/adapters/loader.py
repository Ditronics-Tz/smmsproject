from importlib import import_module

from django.conf import settings


def load_school_adapter():
    configured = settings.SCHOOL_SYSTEM_ADAPTER
    if configured == "csv":
        configured = "smmsapp.integrations.adapters.csv_adapter.CSVSchoolAdapter"
    module_name, class_name = configured.rsplit(".", 1)
    adapter_class = getattr(import_module(module_name), class_name)
    return adapter_class()
