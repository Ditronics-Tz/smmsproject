"""Guard against serializer `source` paths that do not exist on the model.

A wrong source (e.g. `rfid_card` on a model whose FK is `control_number`)
does not raise at import or at class definition. DRF's
Field.get_attribute() catches the AttributeError and raises SkipField, so the
field simply vanishes from the response for every row. That is how the wallet
deposit and ledger endpoints shipped broken.

This resolves every declared source against the model *class* metadata, so
nullable rows cannot produce false positives.
"""
import importlib
import inspect
import pkgutil

from django.core.exceptions import FieldDoesNotExist
from django.test import SimpleTestCase
from rest_framework import serializers

import smmsapp.serializers as serializer_package


def _resolve_source(model, source):
    """Walk a dotted source over model metadata. Returns the bad hop or None.

    A hop is valid if it is a model field, a relation to descend into, or a
    plain attribute/method on the model class (e.g. the ``get_*_display``
    helpers Django generates from choices).
    """
    current = model
    for hop in source.split('.'):
        try:
            field = current._meta.get_field(hop)
        except FieldDoesNotExist:
            if hasattr(current, hop):
                return None
            return hop
        # Descend through relations so the next hop is checked on the target.
        current = getattr(field, 'related_model', None) or current
        if current is None:
            return hop
    return None


class SerializerSourceResolutionTests(SimpleTestCase):
    def test_declared_sources_resolve_on_their_model(self):
        problems = []
        for mod_info in pkgutil.iter_modules(serializer_package.__path__):
            module = importlib.import_module(
                f'smmsapp.serializers.{mod_info.name}'
            )
            for cls_name, cls in vars(module).items():
                if not inspect.isclass(cls) or not issubclass(
                    cls, serializers.BaseSerializer
                ):
                    continue
                model = getattr(getattr(cls, 'Meta', None), 'model', None)
                if model is None:
                    continue
                try:
                    instance = cls()
                except Exception:
                    # Instantiation itself is covered by the endpoint tests.
                    continue
                for fname, field in instance.fields.items():
                    if not field.source or field.source == '*':
                        continue
                    if field.write_only or isinstance(
                        field, serializers.SerializerMethodField
                    ):
                        continue
                    bad_hop = _resolve_source(model, field.source)
                    if bad_hop is not None:
                        problems.append(
                            f'{mod_info.name}.{cls_name}.{fname}: '
                            f'source="{field.source}" has no "{bad_hop}" on '
                            f'{model.__name__}'
                        )

        self.assertEqual(problems, [], 'unresolvable serializer sources:\n' + '\n'.join(problems))
