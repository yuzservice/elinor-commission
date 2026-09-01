from datetime import date, time
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from .models import (
    AuditLog,
    CommissionLevel,
    DailyShiftLog,
    Department,
    Employee,
    EmployeeLevelHistory,
    LineCommissionRate,
    LineShiftPerformance,
    LineTarget,
    Shift,
    SupportLineInterval,
    Violation,
    ViolationRule,
)
from .services import employee_metrics

class BaseEmployeeTest(TestCase):
    def setUp(self):
        self.level_a=CommissionLevel.objects.create(code="A",performance_rate=1400,violation_rate=6000)
        self.level_b=CommissionLevel.objects.create(code="B",performance_rate=1000,violation_rate=4000)
        self.department=Department.objects.create(name="لاین وسط")
        self.shift_morning, _=Shift.objects.update_or_create(
            code="MORNING",
            defaults={"title":"شیفت صبح","start_time":time(10, 0),"end_time":time(16, 0),"standard_hours":Decimal("6.0"),"sort_order":1}
        )
        self.shift_evening, _=Shift.objects.update_or_create(
            code="EVENING",
            defaults={"title":"شیفت عصر","start_time":time(16, 0),"end_time":time(22, 0),"standard_hours":Decimal("6.0"),"sort_order":2}
        )
        self.manager_user=User.objects.create_user("manager",password="StrongPass123!",is_staff=True)
        self.manager=Employee.objects.create(
            user=self.manager_user,
            employee_code="M001",
            first_name="مدیر",
            last_name="سیستم",
            mobile="09120000001",
            role=Employee.Role.MANAGER,
            commission_level=self.level_a,
            default_shift=self.shift_morning,
            standard_daily_hours=Decimal("6.0"),
            primary_department=self.department
        )
        self.manager.departments.add(self.department)
        self.employee_user=User.objects.create_user("E001",password="StrongPass123!")
        self.employee=Employee.objects.create(
            user=self.employee_user,
            employee_code="E001",
            first_name="کارمند",
            last_name="اول",
            mobile="09120000002",
            commission_level=self.level_a,
            default_shift=self.shift_morning,
            standard_daily_hours=Decimal("6.0"),
            primary_department=self.department
        )
        self.employee.departments.add(self.department)

class ShiftModelTests(TestCase):
    def test_shift_creation_and_str(self):
        shift = Shift.objects.create(
            code="CUSTOM_1",
            title="شیفت میانی",
            start_time=time(12, 0),
            end_time=time(18, 0),
            standard_hours=Decimal("6.0"),
            sort_order=3
        )
        self.assertEqual(str(shift), "شیفت میانی (12:00 تا 18:00)")
        self.assertEqual(shift.duration_display, "6.0 ساعت")

class ShiftManagementTests(BaseEmployeeTest):
    def test_manager_can_list_shifts(self):
        self.client.force_login(self.manager_user)
        response = self.client.get(reverse("management_shifts"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "شیفت صبح")
        self.assertContains(response, "شیفت عصر")

    def test_employee_cannot_list_shifts(self):
        self.client.force_login(self.employee_user)
        response = self.client.get(reverse("management_shifts"))
        self.assertEqual(response.status_code, 403)

    def test_manager_can_create_shift_and_audit(self):
        self.client.force_login(self.manager_user)
        payload = {
            "title": "شیفت شب",
            "code": "NIGHT",
            "start_time": "22:00",
            "end_time": "06:00",
            "standard_hours": "8.0",
            "is_active": "on",
            "sort_order": "3",
        }
        response = self.client.post(reverse("management_shift_create"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Shift.objects.filter(code="NIGHT").exists())
        self.assertTrue(AuditLog.objects.filter(action="shift.created").exists())

    def test_manager_can_edit_shift_and_audit(self):
        self.client.force_login(self.manager_user)
        payload = {
            "title": "شیفت صبح ویرایش‌شده",
            "code": self.shift_morning.code,
            "start_time": "09:30",
            "end_time": "15:30",
            "standard_hours": "6.0",
            "is_active": "on",
            "sort_order": "1",
        }
        response = self.client.post(reverse("management_shift_edit", args=[self.shift_morning.pk]), payload)
        self.assertEqual(response.status_code, 302)
        self.shift_morning.refresh_from_db()
        self.assertEqual(self.shift_morning.title, "شیفت صبح ویرایش‌شده")
        self.assertEqual(self.shift_morning.start_time, time(9, 30))
        self.assertTrue(AuditLog.objects.filter(action="shift.updated").exists())

    def test_shift_validation_same_start_end_time(self):
        self.client.force_login(self.manager_user)
        payload = {
            "title": "شیفت نامعتبر",
            "code": "INVALID",
            "start_time": "10:00",
            "end_time": "10:00",
            "standard_hours": "6.0",
            "is_active": "on",
            "sort_order": "1",
        }
        response = self.client.post(reverse("management_shift_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ساعت شروع و پایان نمی‌تواند یکسان باشد")

    def test_employee_creation_and_edit_with_shift(self):
        self.client.force_login(self.manager_user)
        payload = {
            "username": "E099",
            "first_name": "علی",
            "last_name": "رضایی",
            "mobile": "09120000099",
            "employee_code": "E099",
            "start_date": "۱۴۰۵/۰۶/۰۷",
            "default_shift": self.shift_evening.pk,
            "standard_daily_hours": "8.0",
            "primary_department": self.department.pk,
            "departments": [self.department.pk],
            "commission_level": self.level_a.pk,
            "is_active": "on",
            "role": Employee.Role.EMPLOYEE,
            "initial_password": "AnotherStrong123!",
        }
        response = self.client.post(reverse("management_employee_create"), payload)
        self.assertEqual(response.status_code, 302)
        emp = Employee.objects.get(employee_code="E099")
        self.assertEqual(emp.default_shift, self.shift_evening)
        self.assertEqual(emp.standard_daily_hours, Decimal("8.0"))


class DepartmentManagementTests(BaseEmployeeTest):
    def test_manager_can_create_and_edit_department_with_audit(self):
        self.client.force_login(self.manager_user)
        response = self.client.post(reverse("management_department_create"), {"name": "  کیف   و کفش  ", "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        department = Department.objects.get(name="کیف و کفش")
        self.assertTrue(AuditLog.objects.filter(action="department.created", entity_id=str(department.pk)).exists())
        response = self.client.post(reverse("management_department_edit", args=[department.pk]), {"name": "کفش", "is_active": ""})
        self.assertEqual(response.status_code, 302)
        department.refresh_from_db()
        self.assertEqual(department.name, "کفش")
        self.assertFalse(department.is_active)
        self.assertTrue(AuditLog.objects.filter(action="department.updated", entity_id=str(department.pk)).exists())

    def test_duplicate_department_name_is_rejected_case_insensitively(self):
        self.client.force_login(self.manager_user)
        response = self.client.post(reverse("management_department_create"), {"name": self.department.name, "is_active": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "لاین دیگری با این نام وجود دارد")

    def test_employee_cannot_manage_departments(self):
        self.client.force_login(self.employee_user)
        self.assertEqual(self.client.get(reverse("management_departments")).status_code, 403)

    def test_department_cards_show_real_target_progress(self):
        LineTarget.objects.create(
            department=self.department, bronze_units=10, bronze_reward=100,
            silver_units=20, silver_reward=200, gold_units=30, gold_reward=300,
        )
        LineShiftPerformance.objects.create(
            date=date.today().replace(day=1), shift=self.shift_morning,
            department=self.department, sold_units=5, recorded_by=self.manager_user,
        )
        self.client.force_login(self.manager_user)
        response = self.client.get(reverse("management_departments"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "5 کالا")
        self.assertContains(response, "50٪ مسیر تارگت بعدی")

    def test_inactive_line_without_target_or_performance_renders_gracefully(self):
        inactive = Department.objects.create(name="لاین غیرفعال", is_active=False)
        self.client.force_login(self.manager_user)
        response = self.client.get(reverse("management_departments"))
        self.assertContains(response, inactive.name)
        self.assertContains(response, "بدون داده")
        detail = self.client.get(reverse("management_department_detail", args=[inactive.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "هنوز عملکردی برای این لاین ثبت نشده است")

    def test_old_line_rates_route_redirects_to_departments(self):
        self.client.force_login(self.manager_user)
        response = self.client.get(reverse("management_line_rates"))
        self.assertRedirects(response, reverse("management_departments"))

    def test_employee_cannot_access_department_control_center(self):
        self.client.force_login(self.employee_user)
        response = self.client.get(reverse("management_department_detail", args=[self.department.pk]))
        self.assertEqual(response.status_code, 403)


class ManagementDeletionTests(BaseEmployeeTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.manager_user)

    def test_delete_is_manager_only_and_post_only(self):
        shift = Shift.objects.create(code="DELETE_AUTH", title="حذف مجوز", start_time=time(8), end_time=time(9))
        self.assertEqual(self.client.get(reverse("management_shift_delete", args=[shift.pk])).status_code, 405)
        self.client.force_login(self.employee_user)
        self.assertEqual(self.client.post(reverse("management_shift_delete", args=[shift.pk])).status_code, 403)
        self.assertTrue(Shift.objects.filter(pk=shift.pk).exists())

    def test_department_delete_success_audits_and_dependency_message_counts(self):
        clean = Department.objects.create(name="لاین قابل حذف")
        response = self.client.post(reverse("management_department_delete", args=[clean.pk]))
        self.assertRedirects(response, reverse("management_departments"))
        self.assertFalse(Department.objects.filter(pk=clean.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="department.deleted", entity_id=str(clean.pk)).exists())
        response = self.client.post(reverse("management_department_delete", args=[self.department.pk]), follow=True)
        self.assertContains(response, "2 کارمند با این لاین به‌عنوان لاین اصلی")
        self.assertTrue(Department.objects.filter(pk=self.department.pk).exists())

    def test_department_detail_only_offers_deleting_the_department(self):
        clean = Department.objects.create(name="لاین مرکز کنترل")
        response = self.client.get(reverse("management_department_detail", args=[clean.pk]))
        self.assertContains(response, "حذف لاین")
        self.assertNotContains(response, "حذف ضریب گرید")
        self.assertNotContains(response, "حذف تنظیمات تارگت")
        self.assertFalse(LineTarget.objects.filter(department=clean).exists())

    def test_shift_delete_blocks_with_count_then_deletes_clean_shift(self):
        response = self.client.post(reverse("management_shift_delete", args=[self.shift_morning.pk]), follow=True)
        self.assertContains(response, "2 کارمند با شیفت پیش‌فرض")
        clean = Shift.objects.create(code="DELETE_ME", title="شیفت حذف", start_time=time(8), end_time=time(9))
        self.client.post(reverse("management_shift_delete", args=[clean.pk]))
        self.assertFalse(Shift.objects.filter(pk=clean.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="shift.deleted", entity_id=str(clean.pk)).exists())

    def test_employee_delete_blocks_history_and_keeps_user_on_success(self):
        rule = ViolationRule.objects.create(code="EMP_BLOCK", title="وابستگی کارمند", first_points=1, second_points=2, third_points=3)
        Violation.objects.create(employee=self.employee, rule=rule, violation_date=date(2026, 8, 1),
                                 occurrence=1, points_snapshot=1, recorded_by=self.manager_user)
        response = self.client.post(reverse("management_employee_delete", args=[self.employee.pk]), follow=True)
        self.assertContains(response, "1 تخلف ثبت‌شده")
        self.assertTrue(Employee.objects.filter(pk=self.employee.pk).exists())
        user = User.objects.create_user("delete-user")
        clean = Employee.objects.create(user=user, employee_code="DEL1", first_name="حذف", last_name="آزمایشی",
                                        mobile="09120000111", commission_level=self.level_a)
        self.client.post(reverse("management_employee_delete", args=[clean.pk]))
        self.assertFalse(Employee.objects.filter(pk=clean.pk).exists())
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="employee.deleted", entity_id=str(clean.pk)).exists())

    def test_shift_log_delete_blocks_frozen_and_support_intervals(self):
        log = DailyShiftLog.objects.create(employee=self.employee, date=date(2026, 8, 1), shift=self.shift_morning,
                                           main_department=self.department, is_frozen=True)
        response = self.client.post(reverse("management_shift_log_delete", args=[log.pk]), follow=True)
        self.assertContains(response, "1 کارکرد تأیید یا فریز‌شده")
        log.is_frozen = False
        log.save(update_fields=["is_frozen"])
        SupportLineInterval.objects.create(shift_log=log, department=Department.objects.create(name="کمکی حذف"),
                                           start_time=time(11), end_time=time(12))
        response = self.client.post(reverse("management_shift_log_delete", args=[log.pk]), follow=True)
        self.assertContains(response, "1 بازه کمکی")

    def test_violation_rule_delete_blocks_and_clean_rule_deletes(self):
        linked = ViolationRule.objects.create(code="LINKED", title="قانون مرتبط", first_points=1, second_points=2, third_points=3)
        linked.departments.add(self.department)
        response = self.client.post(reverse("management_violation_rule_delete", args=[linked.pk]), follow=True)
        self.assertContains(response, "1 لاین مرتبط")
        clean = ViolationRule.objects.create(code="CLEAN", title="قانون پاک", first_points=1, second_points=2, third_points=3)
        self.client.post(reverse("management_violation_rule_delete", args=[clean.pk]))
        self.assertFalse(ViolationRule.objects.filter(pk=clean.pk).exists())

    def test_line_performance_and_violation_delete_with_audit(self):
        performance = LineShiftPerformance.objects.create(date=date(2026, 8, 2), shift=self.shift_evening,
            department=self.department, sold_units=10, recorded_by=self.manager_user)
        violation = Violation.objects.create(employee=self.employee, rule=ViolationRule.objects.create(
            code="DELETE_V", title="تخلف حذف", first_points=1, second_points=2, third_points=3),
            violation_date=date(2026, 8, 2), occurrence=1, points_snapshot=1, recorded_by=self.manager_user)
        self.client.post(reverse("management_line_performance_delete", args=[performance.pk]))
        self.client.post(reverse("management_violation_delete", args=[violation.pk]))
        self.assertFalse(LineShiftPerformance.objects.filter(pk=performance.pk).exists())
        self.assertFalse(Violation.objects.filter(pk=violation.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="line_performance.deleted", entity_id=str(performance.pk)).exists())
        self.assertTrue(AuditLog.objects.filter(action="violation.deleted", entity_id=str(violation.pk)).exists())


class ViolationRuleManagementTests(BaseEmployeeTest):
    def test_manager_can_create_line_scoped_rule(self):
        self.client.force_login(self.manager_user)
        response = self.client.post(reverse("management_violation_rule_create"), {
            "code": "LATE", "title": "تاخیر", "first_points": 1,
            "second_points": 2, "third_points": 4,
            "recurrence_window": ViolationRule.RecurrenceWindow.SAME_MONTH,
            "departments": [self.department.pk], "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        rule = ViolationRule.objects.get(code="LATE")
        self.assertFalse(rule.all_departments)
        self.assertEqual(list(rule.departments.all()), [self.department])
        self.assertTrue(AuditLog.objects.filter(action="violation_rule.created").exists())

    def test_violation_keeps_rule_snapshot_after_rule_change(self):
        rule = ViolationRule.objects.create(
            code="V-SNAP", title="قانون اولیه", first_points=2, second_points=4, third_points=8,
        )
        self.client.force_login(self.manager_user)
        response = self.client.post(reverse("violation_create"), {
            "employee": self.employee.pk, "rule": rule.pk,
            "violation_date": "۱۴۰۵/۰۶/۰۹", "occurrence": 2, "description": "شرح",
        })
        self.assertEqual(response.status_code, 302)
        violation = Violation.objects.get(rule=rule)
        rule.title = "قانون ویرایش‌شده"
        rule.second_points = 20
        rule.save()
        violation.refresh_from_db()
        self.assertEqual(violation.points_snapshot, 4)
        self.assertEqual(violation.rule_snapshot["title"], "قانون اولیه")
        self.assertEqual(violation.rule_snapshot["points"], 4)

    def test_employee_cannot_manage_violation_rules(self):
        self.client.force_login(self.employee_user)
        self.assertEqual(self.client.get(reverse("management_violation_rules")).status_code, 403)

class DailyShiftLogTests(BaseEmployeeTest):
    def setUp(self):
        super().setUp()
        self.dept_accessories = Department.objects.create(name="اکسسوری")
        self.dept_shirt = Department.objects.create(name="پیراهن")
        self.employee.departments.add(self.dept_accessories, self.dept_shirt)
        self.jalali_today = "۱۴۰۵/۰۶/۰۷"

    def test_create_shift_log_main_line_only(self):
        self.client.force_login(self.employee_user)
        payload = {
            "date": self.jalali_today,
            "shift": self.shift_morning.pk,
            "main_department": self.department.pk,
            "main_hours": "6.0",
            "has_support_line": "",
            "employee_note": "روز عادی",
        }
        response = self.client.post(reverse("shift_log_create"), payload)
        self.assertEqual(response.status_code, 302)
        log = DailyShiftLog.objects.get()
        self.assertEqual(log.employee, self.employee)
        self.assertEqual(log.main_department, self.department)
        self.assertEqual(log.main_hours, Decimal("6.0"))
        self.assertFalse(log.has_support_line)
        self.assertEqual(log.support_departments.count(), 0)
        self.assertEqual(log.support_hours, Decimal("0.0"))
        self.assertEqual(log.total_hours, Decimal("6.0"))
        self.assertTrue(AuditLog.objects.filter(action="shift_log.created").exists())

    def test_create_shift_log_with_support_line(self):
        self.client.force_login(self.employee_user)
        payload = {
            "date": self.jalali_today,
            "shift": self.shift_morning.pk,
            "main_department": self.department.pk,
            "has_support_line": "on",
            "support-TOTAL_FORMS": "1", "support-INITIAL_FORMS": "0",
            "support-MIN_NUM_FORMS": "0", "support-MAX_NUM_FORMS": "1000",
            "support-0-department": self.dept_accessories.pk,
            "support-0-start_time": "10:00", "support-0-end_time": "12:00",
            "employee_note": "۴ ساعت شلوار و ۲ ساعت اکسسوری",
        }
        response = self.client.post(reverse("shift_log_create"), payload)
        self.assertEqual(response.status_code, 302)
        log = DailyShiftLog.objects.get()
        self.assertEqual(log.main_hours, Decimal("4.0"))
        self.assertTrue(log.has_support_line)
        self.assertIn(self.dept_accessories, log.support_departments.all())
        self.assertEqual(log.support_hours, Decimal("2.0"))
        self.assertEqual(log.total_hours, Decimal("6.0"))

    def test_create_shift_log_with_multiple_support_lines(self):
        self.client.force_login(self.employee_user)
        payload = {
            "date": self.jalali_today,
            "shift": self.shift_morning.pk,
            "main_department": self.department.pk,
            "has_support_line": "on",
            "support-TOTAL_FORMS": "2", "support-INITIAL_FORMS": "0",
            "support-MIN_NUM_FORMS": "0", "support-MAX_NUM_FORMS": "1000",
            "support-0-department": self.dept_accessories.pk,
            "support-0-start_time": "10:00", "support-0-end_time": "11:00",
            "support-1-department": self.dept_shirt.pk,
            "support-1-start_time": "11:00", "support-1-end_time": "12:00",
            "employee_note": "کمک به دو لاین",
        }
        response = self.client.post(reverse("shift_log_create"), payload)
        self.assertEqual(response.status_code, 302)
        log = DailyShiftLog.objects.get()
        self.assertEqual(log.support_departments.count(), 2)
        self.assertIn(self.dept_accessories, log.support_departments.all())
        self.assertIn(self.dept_shirt, log.support_departments.all())
        self.assertEqual(log.support_hours, Decimal("2.0"))

    def test_support_department_cannot_be_same_as_main(self):
        self.client.force_login(self.employee_user)
        payload = {
            "date": self.jalali_today,
            "shift": self.shift_morning.pk,
            "main_department": self.department.pk,
            "has_support_line": "on",
            "support-TOTAL_FORMS": "1", "support-INITIAL_FORMS": "0",
            "support-MIN_NUM_FORMS": "0", "support-MAX_NUM_FORMS": "1000",
            "support-0-department": self.department.pk,
            "support-0-start_time": "10:00", "support-0-end_time": "12:00",
        }
        response = self.client.post(reverse("shift_log_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DailyShiftLog.objects.count(), 0)
        self.assertContains(response, "لاین کمکی نمی‌تواند همان لاین اصلی باشد")

    def test_support_interval_requires_complete_times(self):
        self.client.force_login(self.employee_user)
        payload = {
            "date": self.jalali_today,
            "shift": self.shift_morning.pk,
            "main_department": self.department.pk,
            "has_support_line": "on",
            "support-TOTAL_FORMS": "1", "support-INITIAL_FORMS": "0",
            "support-MIN_NUM_FORMS": "0", "support-MAX_NUM_FORMS": "1000",
            "support-0-department": self.dept_accessories.pk,
            "support-0-start_time": "10:00", "support-0-end_time": "",
        }
        response = self.client.post(reverse("shift_log_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DailyShiftLog.objects.count(), 0)
        self.assertContains(response, "این فیلد لازم است")

    def test_unique_shift_log_per_day_and_shift(self):
        self.client.force_login(self.employee_user)
        payload = {
            "date": self.jalali_today,
            "shift": self.shift_morning.pk,
            "main_department": self.department.pk,
            "main_hours": "6.0",
        }
        self.client.post(reverse("shift_log_create"), payload)
        self.assertEqual(DailyShiftLog.objects.count(), 1)
        response = self.client.post(reverse("shift_log_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DailyShiftLog.objects.count(), 1)
        self.assertContains(response, "قبلاً کارکرد ثبت کرده‌ای")

    def test_employee_cannot_view_another_employee_shift_log(self):
        other_user = User.objects.create_user("E002", password="StrongPass123!")
        other_emp = Employee.objects.create(
            user=other_user,
            employee_code="E002",
            first_name="کارمند۲",
            last_name="دوم",
            mobile="09120000003",
            commission_level=self.level_a,
            primary_department=self.department,
        )
        log = DailyShiftLog.objects.create(
            employee=other_emp,
            date=date.today(),
            shift=self.shift_morning,
            main_department=self.department,
            main_hours=Decimal("6.0"),
        )
        self.client.force_login(self.employee_user)
        response = self.client.get(reverse("shift_log_detail", args=[log.pk]))
        self.assertEqual(response.status_code, 404)

    def test_manager_can_view_all_shift_logs(self):
        log = DailyShiftLog.objects.create(
            employee=self.employee,
            date=date.today(),
            shift=self.shift_morning,
            main_department=self.department,
            main_hours=Decimal("6.0"),
        )
        self.client.force_login(self.manager_user)
        response = self.client.get(reverse("management_shift_log_reviews"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.employee.full_name)


class SupportLineIntervalTests(BaseEmployeeTest):
    def setUp(self):
        super().setUp()
        self.accessories = Department.objects.create(name="اکسسوری")
        self.shirt = Department.objects.create(name="پیراهن")
        self.jalali_date = "۱۴۰۵/۰۶/۰۷"

    def payload(self, intervals, **overrides):
        data = {
            "date": self.jalali_date,
            "shift": str(self.shift_morning.pk),
            "main_department": str(self.department.pk),
            "has_support_line": "on" if intervals else "",
            "employee_note": "ثبت چند بازه",
            "support-TOTAL_FORMS": str(len(intervals)),
            "support-INITIAL_FORMS": "0",
            "support-MIN_NUM_FORMS": "0",
            "support-MAX_NUM_FORMS": "1000",
        }
        for index, (department, start, end) in enumerate(intervals):
            data[f"support-{index}-department"] = str(department.pk)
            data[f"support-{index}-start_time"] = start
            data[f"support-{index}-end_time"] = end
        data.update(overrides)
        return data

    def test_add_multiple_ranges_and_server_calculations(self):
        self.client.force_login(self.employee_user)
        data = self.payload([(self.shirt, "10:30", "11:30"), (self.accessories, "13:00", "14:30")])
        data.update({"main_hours": "99", "support_hours": "99", "total_hours": "99"})
        response = self.client.post(reverse("shift_log_create"), data)
        self.assertEqual(response.status_code, 302)
        log = DailyShiftLog.objects.get()
        self.assertEqual(log.support_intervals.count(), 2)
        self.assertEqual(log.support_hours, Decimal("2.50"))
        self.assertEqual(log.main_hours, Decimal("3.50"))
        self.assertEqual(log.total_hours, Decimal("6.00"))
        self.assertEqual(set(log.support_departments.all()), {self.shirt, self.accessories})

    def test_overlap_is_rejected(self):
        self.client.force_login(self.employee_user)
        response = self.client.post(reverse("shift_log_create"), self.payload([
            (self.shirt, "10:30", "12:00"), (self.accessories, "11:30", "13:00")
        ]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DailyShiftLog.objects.exists())

    def test_out_of_shift_and_same_line_are_rejected(self):
        self.client.force_login(self.employee_user)
        response = self.client.post(reverse("shift_log_create"), self.payload([(self.shirt, "09:30", "10:30")]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DailyShiftLog.objects.exists())
        response = self.client.post(reverse("shift_log_create"), self.payload([(self.department, "10:30", "11:30")]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DailyShiftLog.objects.exists())

    def test_end_before_start_is_rejected(self):
        self.client.force_login(self.employee_user)
        response = self.client.post(reverse("shift_log_create"), self.payload([(self.shirt, "12:00", "11:00")]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DailyShiftLog.objects.exists())

    def test_interval_create_update_delete_are_audited(self):
        self.client.force_login(self.employee_user)
        self.client.post(reverse("shift_log_create"), self.payload([(self.shirt, "10:30", "11:30")]))
        log = DailyShiftLog.objects.get()
        interval = log.support_intervals.get()
        self.assertTrue(AuditLog.objects.filter(action="support_interval.created").exists())
        data = self.payload([(self.shirt, "10:30", "12:00")])
        data.update({"support-INITIAL_FORMS": "1", "support-0-id": str(interval.pk)})
        self.client.post(reverse("shift_log_edit", args=[log.pk]), data)
        self.assertTrue(AuditLog.objects.filter(action="support_interval.updated").exists())
        data["support-0-DELETE"] = "on"
        self.client.post(reverse("shift_log_edit", args=[log.pk]), data)
        self.assertTrue(AuditLog.objects.filter(action="support_interval.deleted").exists())

class LineShiftPerformanceTests(BaseEmployeeTest):
    def setUp(self):
        super().setUp()
        self.jalali_today = "۱۴۰۵/۰۶/۰۷"

    def test_manager_can_create_line_performance(self):
        self.client.force_login(self.manager_user)
        payload = {
            "date": self.jalali_today,
            "shift": self.shift_morning.pk,
            "department": self.department.pk,
            "sold_units": "34",
            "sales_amount": "150000000",
            "description": "فروش شیفت صبح",
        }
        response = self.client.post(reverse("management_line_performance_create"), payload)
        self.assertEqual(response.status_code, 302)
        rec = LineShiftPerformance.objects.get()
        self.assertEqual(rec.sold_units, 34)
        self.assertEqual(rec.shift, self.shift_morning)
        self.assertEqual(rec.department, self.department)
        self.assertTrue(AuditLog.objects.filter(action="line_performance.created").exists())

    def test_employee_cannot_access_line_performance(self):
        self.client.force_login(self.employee_user)
        response = self.client.get(reverse("management_line_performances"))
        self.assertEqual(response.status_code, 403)
        response = self.client.get(reverse("management_line_performance_create"))
        self.assertEqual(response.status_code, 403)

    def test_manager_batch_entry(self):
        dept2 = Department.objects.create(name="اکسسوری")
        self.client.force_login(self.manager_user)
        payload = {
            "date": self.jalali_today,
            "shift": self.shift_morning.pk,
            "save_batch": "1",
            f"sold_units_{self.department.pk}": "25",
            f"sold_units_{dept2.pk}": "12",
        }
        response = self.client.post(reverse("management_line_performance_batch"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LineShiftPerformance.objects.count(), 2)
        rec1 = LineShiftPerformance.objects.get(department=self.department)
        rec2 = LineShiftPerformance.objects.get(department=dept2)
        self.assertEqual(rec1.sold_units, 25)
        self.assertEqual(rec2.sold_units, 12)

class LineCommissionEngineTests(BaseEmployeeTest):
    def setUp(self):
        super().setUp()
        self.dept_pants = Department.objects.create(name="شلوار")
        self.dept_accessories = Department.objects.create(name="اکسسوری")
        self.employee.departments.add(self.dept_pants, self.dept_accessories)
        self.employee.primary_department = self.dept_pants
        self.employee.save()

        # Rates: Pants Grade A = 1500, Accessories Grade A = 800
        LineCommissionRate.objects.create(department=self.dept_pants, commission_level=self.level_a, rate_per_unit=1500)
        LineCommissionRate.objects.create(department=self.dept_accessories, commission_level=self.level_a, rate_per_unit=800)

        self.user_emp2 = User.objects.create_user("E002", password="StrongPass123!")
        self.emp2 = Employee.objects.create(
            user=self.user_emp2,
            employee_code="E002",
            first_name="کارمند۲",
            last_name="دوم",
            mobile="09120000003",
            commission_level=self.level_a,
            primary_department=self.dept_accessories,
        )
        self.emp2.departments.add(self.dept_pants, self.dept_accessories)

    def test_proportional_sharing_with_main_and_support_lines(self):
        # Emp1: 4h Pants (main) + 2h Accessories (support) in Morning shift
        log1 = DailyShiftLog.objects.create(
            employee=self.employee,
            date=date(2026, 8, 29),
            shift=self.shift_morning,
            main_department=self.dept_pants,
            main_hours=Decimal("4.0"),
            has_support_line=True,
            support_hours=Decimal("2.0"),
        )
        log1.support_departments.add(self.dept_accessories)

        # Emp2: 6h Accessories (main) in Morning shift
        DailyShiftLog.objects.create(
            employee=self.emp2,
            date=date(2026, 8, 29),
            shift=self.shift_morning,
            main_department=self.dept_accessories,
            main_hours=Decimal("6.0"),
            has_support_line=False,
        )

        # Performance:
        # Pants: 30 sold units in Morning shift (total pants hours = 4h by Emp1 -> Emp1 gets 30 units)
        LineShiftPerformance.objects.create(
            date=date(2026, 8, 29),
            shift=self.shift_morning,
            department=self.dept_pants,
            sold_units=30,
            recorded_by=self.manager_user,
        )
        # Accessories: 40 sold units in Morning shift
        # Total accessories hours = 2h (Emp1) + 6h (Emp2) = 8h
        # Emp1 gets (2/8)*40 = 10 units
        # Emp2 gets (6/8)*40 = 30 units
        LineShiftPerformance.objects.create(
            date=date(2026, 8, 29),
            shift=self.shift_morning,
            department=self.dept_accessories,
            sold_units=40,
            recorded_by=self.manager_user,
        )

        # Check Emp1 metrics
        m1 = employee_metrics(self.employee, date(2026, 8, 1), date(2026, 8, 31))
        # Total units share for Emp1: 30 (pants) + 10 (accessories) = 40 units
        self.assertEqual(m1["total_sales_units_share"], Decimal("40.0"))
        # Commission: 30 * 1500 (pants) + 10 * 800 (accessories) = 45000 + 8000 = 53000
        self.assertEqual(m1["gross_sales_commission"], 53000)
        self.assertEqual(m1["commission"], 53000)

        # Check Emp2 metrics
        m2 = employee_metrics(self.emp2, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(m2["total_sales_units_share"], Decimal("30.0"))
        # Commission: 30 * 800 = 24000
        self.assertEqual(m2["gross_sales_commission"], 24000)
        self.assertEqual(m2["commission"], 24000)

    def test_manager_can_update_rates_and_targets_from_department_detail(self):
        self.client.force_login(self.manager_user)
        response = self.client.get(reverse("management_line_rates"))
        self.assertRedirects(response, reverse("management_departments"))

        detail_url = reverse("management_department_detail", args=[self.dept_pants.pk])
        response = self.client.post(detail_url, {"section": "rates", f"rate_{self.level_a.pk}": "2000"})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(detail_url, {
            "section": "target", "bronze_units": "30", "bronze_reward": "5000000",
            "silver_units": "60", "silver_reward": "12000000",
            "gold_units": "90", "gold_reward": "30000000", "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)

        rate = LineCommissionRate.objects.get(department=self.dept_pants, commission_level=self.level_a)
        self.assertEqual(rate.rate_per_unit, 2000)
        target = LineTarget.objects.get(department=self.dept_pants)
        self.assertEqual(target.bronze_units, 30)
        self.assertEqual(target.gold_reward, 30000000)
        self.assertTrue(AuditLog.objects.filter(action="department.rates_updated").exists())
        self.assertTrue(AuditLog.objects.filter(action="department.target_updated").exists())

    def test_line_target_reward_uses_monthly_units_share(self):
        LineTarget.objects.create(
            department=self.dept_pants,
            bronze_units=30,
            bronze_reward=5000000,
            silver_units=60,
            silver_reward=12000000,
            gold_units=90,
            gold_reward=30000000,
        )
        DailyShiftLog.objects.create(
            employee=self.employee,
            date=date(2026, 8, 29),
            shift=self.shift_morning,
            main_department=self.dept_pants,
            main_hours=Decimal("6.0"),
        )
        LineShiftPerformance.objects.create(
            date=date(2026, 8, 29),
            shift=self.shift_morning,
            department=self.dept_pants,
            sold_units=40,
            recorded_by=self.manager_user,
        )
        metrics = employee_metrics(self.employee, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(metrics["total_sales_units_share"], Decimal("40.0"))
        self.assertEqual(metrics["reward"], 5000000)
        self.assertEqual(metrics["line_target_result"]["achieved_title"], "تارگت برنزی 🥉")
        self.assertEqual(metrics["line_target_result"]["next_target_title"], "تارگت نقره‌ای 🥈")
        self.assertEqual(metrics["commission"], 5060000)

class CommissionTests(BaseEmployeeTest):
    def test_violation_is_deduction(self):
        rule=ViolationRule.objects.create(code="V1",title="تست",first_points=2,second_points=4,third_points=8)
        Violation.objects.create(employee=self.employee,rule=rule,violation_date=date.today(),occurrence=1,points_snapshot=2,description="x",recorded_by=self.manager_user)
        m=employee_metrics(self.employee,date.today(),date.today()); self.assertEqual(m["deduction"],12000); self.assertEqual(m["commission"],0)

class EmployeePermissionTests(BaseEmployeeTest):
    def test_manager_can_list_employees(self): self.client.force_login(self.manager_user); self.assertEqual(self.client.get(reverse("management_employees")).status_code,200)
    def test_employee_cannot_list_employees(self): self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("management_employees")).status_code,403)
    def test_employee_cannot_access_another_employee_idor(self): self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("management_employee_detail",args=[self.manager.pk])).status_code,403)
    def test_inactive_employee_cannot_login(self):
        self.employee.is_active=False; self.employee.save(); self.employee_user.refresh_from_db(); self.assertFalse(self.employee_user.is_active); self.assertFalse(self.client.login(username="E001",password="StrongPass123!"))
    def test_user_without_employee_does_not_500(self):
        user=User.objects.create_user("standalone",password="StrongPass123!"); self.client.force_login(user); self.assertEqual(self.client.get(reverse("dashboard")).status_code,403)
    def test_employee_can_access_own_profile(self):
        self.client.force_login(self.employee_user); response=self.client.get(reverse("profile")); self.assertEqual(response.status_code,200); self.assertContains(response,self.employee.full_name)
    def test_employee_cannot_change_own_level(self): self.client.force_login(self.employee_user); self.assertEqual(self.client.post(reverse("management_employee_edit",args=[self.employee.pk]),{}).status_code,403)
    def test_branding_only_manager(self):
        self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("branding_settings")).status_code,403)
        self.client.force_login(self.manager_user); self.assertEqual(self.client.get(reverse("branding_settings")).status_code,200)

class EmployeeManagementTests(BaseEmployeeTest):
    def setUp(self): super().setUp(); self.client.force_login(self.manager_user)
    def employee_payload(self,**overrides):
        data={"username":"E002","first_name":"نیروی","last_name":"جدید","mobile":"09120000003","employee_code":"E002","start_date":"۱۴۰۵/۰۶/۰۷","default_shift":self.shift_morning.pk,"standard_daily_hours":"6.0","primary_department":self.department.pk,"departments":[self.department.pk],"commission_level":self.level_a.pk,"is_active":"on","role":Employee.Role.EMPLOYEE,"initial_password":"AnotherStrong123!"}; data.update(overrides); return data
    def test_employee_code_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): Employee.objects.create(user=User.objects.create_user("duplicate1"),employee_code="E001",first_name="الف",last_name="ب",mobile="09120000004",commission_level=self.level_a)
    def test_mobile_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): Employee.objects.create(user=User.objects.create_user("duplicate2"),employee_code="E099",first_name="الف",last_name="ب",mobile="09120000002",commission_level=self.level_a)
    def test_manager_can_create_employee_atomically(self):
        response=self.client.post(reverse("management_employee_create"),self.employee_payload()); self.assertEqual(response.status_code,302)
        obj=Employee.objects.get(employee_code="E002"); self.assertEqual(obj.user.username,"E002"); self.assertTrue(AuditLog.objects.filter(action="employee.created",entity_id=str(obj.pk)).exists())
    def test_manager_can_edit_and_level_change_creates_history_and_audit(self):
        payload=self.employee_payload(username=self.employee.user.username,first_name="ویرایش",mobile=self.employee.mobile,employee_code=self.employee.employee_code,commission_level=self.level_b.pk,level_reason="ارتقای آزمایشی"); payload.pop("initial_password"); payload.pop("role")
        response=self.client.post(reverse("management_employee_edit",args=[self.employee.pk]),payload); self.assertEqual(response.status_code,302)
        self.employee.refresh_from_db(); self.assertEqual(self.employee.first_name,"ویرایش"); self.assertEqual(self.employee.commission_level,self.level_b)
        self.assertTrue(EmployeeLevelHistory.objects.filter(employee=self.employee,previous_level=self.level_a,new_level=self.level_b).exists()); self.assertTrue(AuditLog.objects.filter(action="employee.level_changed",entity_id=str(self.employee.pk)).exists())
    def test_deactivation_syncs_login_and_audits(self):
        payload=self.employee_payload(username=self.employee.user.username,mobile=self.employee.mobile,employee_code=self.employee.employee_code,commission_level=self.level_a.pk); payload.pop("initial_password"); payload.pop("role"); payload.pop("is_active")
        self.client.post(reverse("management_employee_edit",args=[self.employee.pk]),payload); self.employee_user.refresh_from_db(); self.assertFalse(self.employee_user.is_active); self.assertTrue(AuditLog.objects.filter(action="employee.deactivated").exists())
    def test_manager_password_reset_and_plaintext_not_logged(self):
        password="NewSecurePass456!"; response=self.client.post(reverse("management_employee_password",args=[self.employee.pk]),{"new_password1":password,"new_password2":password})
        self.assertEqual(response.status_code,302); self.employee_user.refresh_from_db(); self.assertTrue(self.employee_user.check_password(password)); log=AuditLog.objects.get(action="employee.password_reset"); self.assertNotIn(password,str(log.old_values)+str(log.new_values)+log.description)
    def test_employee_can_change_own_password(self):
        self.client.force_login(self.employee_user); new="EmployeeNewPass789!"; response=self.client.post(reverse("profile_password"),{"old_password":"StrongPass123!","new_password1":new,"new_password2":new})
        self.assertEqual(response.status_code,302); self.employee_user.refresh_from_db(); self.assertTrue(self.employee_user.check_password(new))
