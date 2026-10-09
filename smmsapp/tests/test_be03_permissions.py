from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from smmsapp.models import School


User = get_user_model()


class AdminRolePermissionMatrixTests(TestCase):
    """Regression matrix for endpoints that must be restricted to role=admin."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Permission School", location="Arusha")
        cls.users = {
            "admin": User.objects.create_user(
                username="matrix-admin", password="Passw0rd!123", role="admin",
                is_staff=True, school=cls.school,
            ),
            "parent": User.objects.create_user(
                username="matrix-parent", password="Passw0rd!123", role="parent",
                school=cls.school,
            ),
            "operator": User.objects.create_user(
                username="matrix-operator", password="Passw0rd!123", role="operator",
                school=cls.school,
            ),
            "staff": User.objects.create_user(
                username="matrix-staff", password="Passw0rd!123", role="staff",
                is_staff=True, school=cls.school,
            ),
            "student": User.objects.create_user(
                username="matrix-student", password="Passw0rd!123", role="student",
                school=cls.school,
            ),
        }

    def test_non_admin_roles_are_denied_from_admin_endpoints(self):
        admin_routes = (
            ("get", "/api/v1/list/parents"),
            ("get", "/api/v1/list/students"),
            ("get", "/api/v1/list/staffs"),
            ("get", "/api/v1/list/cards"),
            ("get", "/api/v1/list/schools"),
            ("get", "/api/v1/list/canteen-items"),
            ("post", "/api/v1/resources/create-school"),
            ("post", "/api/v1/resources/create-item"),
            ("post", "/api/v1/resources/delete-school"),
            ("post", "/api/v1/resources/all-notifications/"),
            ("get", "/api/v1/audit/logs"),
            ("get", "/api/v1/sms/logs"),
        )
        for role in ("parent", "operator", "staff", "student"):
            self.client = APIClient()
            self.client.force_authenticate(user=self.users[role])
            for method, path in admin_routes:
                with self.subTest(role=role, method=method, path=path):
                    response = getattr(self.client, method)(path, {}, format="json") if method == "post" else self.client.get(path)
                    self.assertEqual(response.status_code, 403, getattr(response, "data", None))

    def test_is_staff_without_admin_role_does_not_grant_admin_access(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.users["staff"])
        for path in ("/api/v1/audit/logs", "/api/v1/sms/logs", "/api/v1/resources/admin-details"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 403)
