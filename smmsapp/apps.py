from django.apps import AppConfig


class smmsappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smmsapp'

    def ready(self):
        from django.db.models.signals import post_delete, post_save
        from .models import FeatureFlag
        from .services.features import clear_feature_cache

        post_save.connect(clear_feature_cache, sender=FeatureFlag, dispatch_uid='feature_flag_cache_save')
        post_delete.connect(clear_feature_cache, sender=FeatureFlag, dispatch_uid='feature_flag_cache_delete')
