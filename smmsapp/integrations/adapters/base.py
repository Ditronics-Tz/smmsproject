from abc import ABC, abstractmethod


class BaseSchoolAdapter(ABC):
    """Adapter boundary: concrete systems return normalized rows for shared upsert."""

    @abstractmethod
    def fetch_students(self):
        raise NotImplementedError

    @abstractmethod
    def fetch_parents(self):
        raise NotImplementedError

    @abstractmethod
    def fetch_classes(self):
        raise NotImplementedError
