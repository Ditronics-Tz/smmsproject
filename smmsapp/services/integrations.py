import hashlib

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from smmsapp.models import CustomUser, IntegrationClass, IntegrationSyncLog
from smmsapp.services.audit import log_action


USER_FIELDS = ("first_name", "middle_name", "last_name", "email", "mobile_number", "gender", "class_room")


def _integration_username(source_system, external_id):
    digest = hashlib.sha256(f"{source_system}:{external_id}".encode()).hexdigest()[:32]
    return f"ext_{digest}"


def _validate_row(kind, row):
    if not isinstance(row, dict):
        raise ValueError("Each row must be a JSON object.")
    external_id = str(row.get("external_id", "")).strip()
    if not external_id or len(external_id) > 120:
        raise ValueError("external_id is required and must be at most 120 characters.")
    if kind == "classes":
        name = str(row.get("name", "")).strip()
        if not name or len(name) > 160:
            raise ValueError("name is required and must be at most 160 characters.")
        return external_id, {"name": name}

    clean = {}
    for field in USER_FIELDS:
        value = row.get(field)
        if value is not None:
            clean[field] = str(value).strip()
    if not clean.get("first_name") or not clean.get("last_name"):
        raise ValueError("first_name and last_name are required.")
    max_lengths = {"first_name": 150, "last_name": 150, "middle_name": 100,
                   "email": 254, "mobile_number": 15, "class_room": 255}
    for field, max_length in max_lengths.items():
        if field in clean and len(clean[field]) > max_length:
            raise ValueError(f"{field} must be at most {max_length} characters.")
    if clean.get("email"):
        try:
            EmailValidator()(clean["email"])
        except ValidationError as exc:
            raise ValueError("email must be a valid email address.") from exc
    if clean.get("gender") and clean["gender"] not in ("M", "F"):
        raise ValueError("gender must be M or F.")
    clean["role"] = "parent" if kind == "parents" else "student"
    return external_id, clean


def _upsert_row(kind, row, school, source_system, dry_run):
    external_id, values = _validate_row(kind, row)
    if kind == "classes":
        existing = IntegrationClass.objects.filter(
            school=school, source_system=source_system, external_id=external_id,
        ).first()
        if dry_run:
            return "updated" if existing else "created", external_id
        obj, created = IntegrationClass.objects.update_or_create(
            school=school, source_system=source_system, external_id=external_id,
            defaults={"name": values["name"]},
        )
        return "created" if created else "updated", external_id

    existing = CustomUser.objects.filter(source_system=source_system, external_id=external_id).first()
    if dry_run:
        return "updated" if existing else "created", external_id
    defaults = dict(values)
    defaults.update({"school": school, "username": _integration_username(source_system, external_id)})
    if existing is None:
        user = CustomUser(**defaults, source_system=source_system, external_id=external_id)
        user.set_unusable_password()
        user.save()
        return "created", external_id
    # External syncs must not silently change the account role or password.
    defaults.pop("role", None)
    defaults.pop("username", None)
    for field, value in defaults.items():
        setattr(existing, field, value)
    existing.save(update_fields=list(defaults))
    return "updated", external_id


def sync_batch(kind, rows, school, source_system, dry_run, key):
    if kind not in {"students", "parents", "classes"}:
        raise ValueError("Unsupported sync type.")
    source_system = str(source_system or "").strip()
    if not source_system or len(source_system) > 80:
        raise ValueError("source_system is required and must be at most 80 characters.")
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("rows must be a list containing at most 500 records.")

    result_rows = []
    counts = {"created": 0, "updated": 0, "failed": 0}
    for index, row in enumerate(rows):
        try:
            # A row is isolated: one malformed record cannot roll back the batch.
            with transaction.atomic():
                outcome, external_id = _upsert_row(kind, row, school, source_system, dry_run)
            counts[outcome] += 1
            result_rows.append({"index": index, "external_id": external_id, "status": outcome})
        except (ValueError, IntegrityError) as exc:
            counts["failed"] += 1
            result_rows.append({"index": index, "external_id": row.get("external_id") if isinstance(row, dict) else None,
                                "status": "failed", "error": str(exc)[:240]})

    sync_log = IntegrationSyncLog.objects.create(
        key=key, endpoint=kind, dry_run=dry_run, created_count=counts["created"],
        updated_count=counts["updated"], failed_count=counts["failed"], results=result_rows,
    )
    try:
        log_action("integration_sync", obj=sync_log, after={"endpoint": kind, **counts, "dry_run": dry_run})
    except Exception:
        # The explicit sync log is authoritative if audit storage is unavailable.
        pass
    return {**counts, "results": result_rows}
