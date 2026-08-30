from datetime import date, time
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from .forms import ActivityForm
from .models import (
    Activity,
    ActivityCategory,
    ActivityStatusHistory,
    ActivityType,
    AuditLog,
    CommissionLevel,
    DailyShiftLog,
    Department,
    Employee,
    EmployeeLevelHistory,
    LineCommissionRate,
    LineShiftPerformance,
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
        self.assertContains(response, "قبلاً کارکرد ثبت کرده‌اید")

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
        response = self.client.get(reverse("management_shift_logs"))
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

    def test_manager_can_review_and_edit_employee_intervals(self):
        log = DailyShiftLog.objects.create(employee=self.employee, date=date.today(), shift=self.shift_morning, main_department=self.department, main_hours=Decimal("6"))
        SupportLineInterval.objects.create(shift_log=log, department=self.shirt, start_time=time(10, 30), end_time=time(11, 30))
        log.recalculate_allocations()
        self.client.force_login(self.manager_user)
        self.assertEqual(self.client.get(reverse("shift_log_detail", args=[log.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("shift_log_edit", args=[log.pk])).status_code, 200)

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

    def test_manager_can_view_and_update_rates_matrix(self):
        self.client.force_login(self.manager_user)
        response = self.client.get(reverse("management_line_rates"))
        self.assertEqual(response.status_code, 200)

        payload = {
            f"rate_{self.dept_pants.pk}_{self.level_a.pk}": "2000",
            f"rate_{self.dept_accessories.pk}_{self.level_a.pk}": "900",
        }
        response = self.client.post(reverse("management_line_rates"), payload)
        self.assertEqual(response.status_code, 302)

        rate = LineCommissionRate.objects.get(department=self.dept_pants, commission_level=self.level_a)
        self.assertEqual(rate.rate_per_unit, 2000)

class CommissionTests(BaseEmployeeTest):
    def setUp(self):
        super().setUp(); self.category=ActivityCategory.objects.create(code="MAIN",title="عملکرد اصلی"); self.kind=ActivityType.objects.create(code="M1",title="فعالیت",category=self.category,scoring_method=ActivityType.ScoringMethod.QUANTITY_MULTIPLIER,multiplier=10,requires_quantity=True,all_departments=True)
    def test_only_approved_activity_counts(self):
        for status in [Activity.Status.APPROVED,Activity.Status.PENDING]: Activity.objects.create(employee=self.employee,activity_type=self.kind,activity_date=date.today(),value=2,definition_score_snapshot=1,multiplier_snapshot=10,calculated_score=20,final_score=20,status=status,submitted_by=self.employee_user)
        m=employee_metrics(self.employee,date.today(),date.today()); self.assertEqual(m["score"],20); self.assertEqual(m["gross"],28000)
    def test_violation_is_deduction(self):
        rule=ViolationRule.objects.create(code="V1",title="تست",first_points=2,second_points=4,third_points=8)
        Violation.objects.create(employee=self.employee,rule=rule,violation_date=date.today(),occurrence=1,points_snapshot=2,description="x",recorded_by=self.manager_user)
        m=employee_metrics(self.employee,date.today(),date.today()); self.assertEqual(m["deduction"],12000); self.assertEqual(m["commission"],0)
    def test_jalali_date_input_is_stored_as_gregorian(self):
        form=ActivityForm(data={"activity_type":self.kind.pk,"activity_date":"۱۴۰۵/۰۶/۰۷","start_time":"09:00","end_time":"10:00","value":"1","employee_note":""},employee=self.employee)
        self.assertTrue(form.is_valid(),form.errors); self.assertEqual(form.cleaned_data["activity_date"],date(2026,8,29))

class ActivityWorkflowTests(BaseEmployeeTest):
    def setUp(self):
        super().setUp()
        self.category=ActivityCategory.objects.create(code="OP",title="وظیفه عملیاتی")
        self.kind=ActivityType.objects.create(code="A01",title="کمک انبار",category=self.category,scoring_method=ActivityType.ScoringMethod.QUANTITY_MULTIPLIER,multiplier=2,requires_quantity=True,requires_time_tracking=True,requires_manager_approval=True,max_daily_submissions=1)
        self.kind.departments.add(self.department)
        self.jalali_today="۱۴۰۵/۰۶/۰۷"
    def payload(self,**overrides):
        data={"activity_type":self.kind.pk,"activity_date":self.jalali_today,"start_time":"09:15","end_time":"10:45","value":"3","employee_note":"انجام شد","action":"submit"}; data.update(overrides); return data
    def submit(self,**overrides):
        self.client.force_login(self.employee_user); return self.client.post(reverse("activity_create"),self.payload(**overrides))
    def test_employee_submission_calculates_score_on_server(self):
        response=self.submit(calculated_score="9999"); self.assertEqual(response.status_code,302)
        item=Activity.objects.get(); self.assertEqual(item.calculated_score,6); self.assertEqual(item.final_score,6); self.assertEqual(item.duration_minutes,90); self.assertEqual(item.status,Activity.Status.PENDING); self.assertEqual(item.employee,self.employee)
        self.assertTrue(ActivityStatusHistory.objects.filter(activity=item,new_status=Activity.Status.PENDING).exists()); self.assertTrue(AuditLog.objects.filter(action="activity.submitted").exists())
    def test_draft_can_be_edited_and_submitted(self):
        response=self.submit(action="draft"); item=Activity.objects.get(); self.assertEqual(item.status,Activity.Status.DRAFT)
        response=self.client.post(reverse("activity_edit",args=[item.pk]),self.payload(value="4")); self.assertEqual(response.status_code,302); item.refresh_from_db(); self.assertEqual(item.status,Activity.Status.PENDING); self.assertEqual(item.final_score,8)
    def test_employee_form_never_exposes_score_fields(self):
        form=ActivityForm(employee=self.employee)
        self.assertNotIn("calculated_score",form.fields)
        self.assertNotIn("final_score",form.fields)
        self.assertNotIn("definition_score_snapshot",form.fields)
        self.assertNotIn("multiplier_snapshot",form.fields)

    def test_score_post_tampering_is_ignored(self):
        response=self.submit(
            calculated_score="999999",
            final_score="999999",
            definition_score_snapshot="999999",
            multiplier_snapshot="999999",
        )
        self.assertEqual(response.status_code,302)
        item=Activity.objects.get()
        self.assertEqual(item.calculated_score,6)
        self.assertEqual(item.final_score,6)
        self.assertEqual(item.multiplier_snapshot,2)

    def test_end_time_must_be_after_start_time(self):
        response=self.submit(start_time="11:00",end_time="10:00")
        self.assertEqual(response.status_code,200)
        self.assertEqual(Activity.objects.count(),0)
        self.assertContains(response,"ساعت پایان باید بعد از ساعت شروع باشد")

    def test_quantity_is_required_only_when_definition_requires_it(self):
        response=self.submit(value="")
        self.assertEqual(response.status_code,200)
        self.assertEqual(Activity.objects.count(),0)
        self.assertContains(response,"ثبت مقدار")

        self.kind.requires_quantity=False
        self.kind.scoring_method=ActivityType.ScoringMethod.FIXED
        self.kind.score_value=7
        self.kind.save()

        response=self.submit(value="")
        self.assertEqual(response.status_code,302)

        item=Activity.objects.get()
        self.assertEqual(item.value,1)
        self.assertEqual(item.calculated_score,7)

    def test_time_is_required_only_when_definition_requires_it(self):
        response=self.submit(start_time="",end_time="")
        self.assertEqual(response.status_code,200)
        self.assertEqual(Activity.objects.count(),0)
        self.assertContains(response,"ثبت ساعت شروع")

        self.kind.requires_time_tracking=False
        self.kind.save()

        response=self.submit(start_time="",end_time="")
        self.assertEqual(response.status_code,302)

        item=Activity.objects.get()
        self.assertIsNone(item.start_time)
        self.assertIsNone(item.end_time)
        self.assertIsNone(item.duration_minutes)

    def test_duration_is_calculated_server_side(self):
        response=self.submit(
            start_time="08:10",
            end_time="11:25",
            duration_minutes="99999",
        )
        self.assertEqual(response.status_code,302)

        item=Activity.objects.get()
        self.assertEqual(item.duration_minutes,195)

    def test_daily_limit_is_enforced(self):
        self.submit(); response=self.submit(); self.assertEqual(response.status_code,200); self.assertEqual(Activity.objects.count(),1); self.assertContains(response,"حداکثر ثبت روزانه")
    def test_employee_cannot_view_another_employee_activity(self):
        item=Activity.objects.create(employee=self.manager,activity_type=self.kind,activity_date=date.today(),value=1,submitted_by=self.manager_user)
        self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("activity_detail",args=[item.pk])).status_code,404)
    def test_employee_cannot_open_manager_review(self):
        self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("management_activity_reviews")).status_code,403)
    def test_manager_approve_creates_history_and_audit(self):
        self.submit(); item=Activity.objects.get(); self.client.force_login(self.manager_user)
        response=self.client.post(reverse("management_activity_review_detail",args=[item.pk]),{"action":"APPROVED","manager_note":"مورد تأیید است"}); self.assertEqual(response.status_code,302); item.refresh_from_db(); self.assertEqual(item.status,Activity.Status.APPROVED); self.assertEqual(item.reviewed_by,self.manager_user)
        self.assertTrue(ActivityStatusHistory.objects.filter(activity=item,new_status="APPROVED").exists()); self.assertTrue(AuditLog.objects.filter(action="activity.approved").exists())
    def test_revision_requires_note_and_can_be_resubmitted(self):
        self.submit(); item=Activity.objects.get(); self.client.force_login(self.manager_user)
        response=self.client.post(reverse("management_activity_review_detail",args=[item.pk]),{"action":"NEEDS_REVISION","manager_note":""}); self.assertEqual(response.status_code,200); item.refresh_from_db(); self.assertEqual(item.status,Activity.Status.PENDING)
        self.client.post(reverse("management_activity_review_detail",args=[item.pk]),{"action":"NEEDS_REVISION","manager_note":"مدرک کامل نیست"}); item.refresh_from_db(); self.assertEqual(item.status,Activity.Status.NEEDS_REVISION)
        self.client.force_login(self.employee_user); self.client.post(reverse("activity_edit",args=[item.pk]),self.payload()); item.refresh_from_db(); self.assertEqual(item.status,Activity.Status.PENDING); self.assertTrue(AuditLog.objects.filter(action="activity.resubmitted").exists())
    def test_required_evidence_type_and_size_validation(self):
        self.kind.requires_evidence=True; self.kind.save(); response=self.submit(); self.assertEqual(response.status_code,200); self.assertContains(response,"بارگذاری مدرک الزامی")
        bad=SimpleUploadedFile("proof.exe",b"x",content_type="application/octet-stream"); response=self.submit(evidence=bad); self.assertEqual(response.status_code,200); self.assertEqual(Activity.objects.count(),0)
    def test_inactive_and_other_department_types_hidden(self):
        other=Department.objects.create(name="صندوق"); hidden=ActivityType.objects.create(code="A02",title="مخفی",category=self.category,active=True); hidden.departments.add(other)
        inactive=ActivityType.objects.create(code="A03",title="غیرفعال",category=self.category,all_departments=True,active=False)
        self.client.force_login(self.employee_user); response=self.client.get(reverse("activity_create")); self.assertNotContains(response,"مخفی"); self.assertNotContains(response,"غیرفعال")
    def test_non_commission_activity_does_not_count(self):
        self.kind.is_commission_eligible=False; self.kind.save(); self.submit(); item=Activity.objects.get(); item.status=Activity.Status.APPROVED; item.save()
        self.assertEqual(employee_metrics(self.employee,date(2026,8,1),date(2026,8,31))["score"],0)

class ActivityDefinitionTests(BaseEmployeeTest):
    def setUp(self): super().setUp(); self.category=ActivityCategory.objects.create(code="DAILY",title="روزانه")
    def payload(self): return {"title":"چک صندوق","code":"D01","category":self.category.pk,"description":"","unit":"مرتبه","scoring_method":"FIXED","score_value":"10","multiplier":"1","is_commission_eligible":"on","requires_manager_approval":"on","allow_employee_note":"on","recurrence_type":"DAILY","max_daily_submissions":"1","all_departments":"on","active":"on","sort_order":"1"}
    def test_manager_can_create_definition_and_audit(self):
        self.client.force_login(self.manager_user); response=self.client.post(reverse("management_activity_type_create"),self.payload()); self.assertEqual(response.status_code,302); self.assertTrue(ActivityType.objects.filter(code="D01").exists()); self.assertTrue(AuditLog.objects.filter(action="activity_type.created").exists())
    def test_employee_cannot_manage_definitions(self):
        self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("management_activity_types")).status_code,403)

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
