from datetime import time, timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import (
    CommissionLevel,
    DailyShiftLog,
    Department,
    Employee,
    LineCommissionRate,
    LineShiftPerformance,
    LineTarget,
    Shift,
    SystemSettings,
    Target,
    ViolationRule,
)
from core.services import approve_shift_log

class Command(BaseCommand):
    help = "ایجاد داده‌های جامع تستی، تارگت‌های ماهانه و کارکردهای تستی جهت بررسی تأیید و فریز پورسانت"

    def handle(self, *args, **opts):
        self.stdout.write("در حال ایجاد داده‌های پایه، لاین‌ها، تارگت‌ها و پرسنل...")

        # ۱. گریدها و سطوح
        level_data = [
            ("A", 1500, 6000, Decimal("1.0")),
            ("B", 1200, 4000, Decimal("1.0")),
            ("C", 900, 4000, Decimal("1.0")),
            ("D", 600, 4000, Decimal("1.0")),
        ]
        levels = {}
        for code, perf, viol, morning in level_data:
            lvl, _ = CommissionLevel.objects.update_or_create(
                code=code,
                defaults={"performance_rate": perf, "violation_rate": viol, "morning_rate": morning}
            )
            levels[code] = lvl

        # ۲. لاین‌ها / بخش‌ها
        dept_names = ["شلوار", "پیراهن", "اکسسوری", "شال و روسری", "تیشرت", "کفش"]
        depts = {}
        for name in dept_names:
            d, _ = Department.objects.get_or_create(name=name, defaults={"is_active": True})
            depts[name] = d

        # ۳. شیفت‌ها
        shift_data = [
            ("MORNING", "شیفت صبح (۱۰ تا ۱۶)", time(10, 0), time(16, 0), Decimal("6.0"), 1),
            ("EVENING", "شیفت عصر (۱۶ تا ۲۲)", time(16, 0), time(22, 0), Decimal("6.0"), 2),
        ]
        shifts = {}
        for code, title, start, end, hours, sort in shift_data:
            s, _ = Shift.objects.update_or_create(
                code=code,
                defaults={
                    "title": title,
                    "start_time": start,
                    "end_time": end,
                    "standard_hours": hours,
                    "sort_order": sort,
                    "is_active": True,
                }
            )
            shifts[code] = s

        # ۴. ماتریس ضرایب لاین و گرید
        rate_matrix = {
            "شلوار": {"A": 1500, "B": 1200, "C": 900, "D": 600},
            "پیراهن": {"A": 1400, "B": 1100, "C": 800, "D": 500},
            "اکسسوری": {"A": 1200, "B": 950, "C": 700, "D": 450},
            "شال و روسری": {"A": 1100, "B": 850, "C": 650, "D": 400},
            "تیشرت": {"A": 1300, "B": 1000, "C": 750, "D": 500},
            "کفش": {"A": 1800, "B": 1400, "C": 1000, "D": 700},
        }
        for d_name, d_obj in depts.items():
            for l_code, l_obj in levels.items():
                rate_val = rate_matrix.get(d_name, {}).get(l_code, l_obj.performance_rate)
                LineCommissionRate.objects.update_or_create(
                    department=d_obj,
                    commission_level=l_obj,
                    defaults={"rate_per_unit": rate_val, "is_active": True}
                )

        # ۵. کاربران و پرسنل
        users_config = [
            ("manager", "مدیر", "سیستم", "MANAGER", "A", "E000", "09110000000", "شلوار", "MORNING"),
            ("sara", "سارا", "راد", "EMPLOYEE", "A", "1002", "09121112233", "شلوار", "MORNING"),
            ("ali", "علی", "حسینی", "EMPLOYEE", "B", "1003", "09122223344", "پیراهن", "MORNING"),
            ("fatemeh", "فاطمه", "ظاهری", "EMPLOYEE", "A", "1004", "09123334455", "شلوار", "MORNING"),
            ("maryam", "مریم", "قلی‌نژاد", "EMPLOYEE", "C", "1005", "09124445566", "اکسسوری", "EVENING"),
        ]

        employees = {}
        for uname, fname, lname, role, lvl, code, mobile, main_dept, def_shift in users_config:
            user, created = User.objects.get_or_create(
                username=uname,
                defaults={
                    "first_name": fname,
                    "last_name": lname,
                    "is_staff": role == "MANAGER",
                    "is_active": True,
                }
            )
            if created:
                user.set_password("Elinor123!")
                user.save()

            emp, emp_created = Employee.objects.get_or_create(
                user=user,
                defaults={
                    "employee_code": code,
                    "first_name": fname,
                    "last_name": lname,
                    "mobile": mobile,
                    "role": role,
                    "commission_level": levels[lvl],
                    "primary_department": depts[main_dept],
                    "default_shift": shifts[def_shift],
                    "standard_daily_hours": Decimal("6.0"),
                    "is_active": True,
                }
            )
            if emp_created:
                emp.departments.add(depts[main_dept], depts["اکسسوری"], depts["پیراهن"])
            employees[uname] = emp

        # ۶. تارگت‌های برنزی، نقره‌ای و طلایی هر لاین
        for dept in depts.values():
            LineTarget.objects.update_or_create(
                department=dept,
                defaults={
                    "bronze_units": 500,
                    "bronze_reward": 5000000,
                    "silver_units": 1000,
                    "silver_reward": 12000000,
                    "gold_units": 3000,
                    "gold_reward": 30000000,
                    "is_active": True,
                },
            )

        # ۷. قوانین تخلفات و تارگت‌های عمومی
        rules = [
            ("V01", "استفاده از تلفن همراه در محیط کار", 5, 10, 20),
            ("V02", "رفتار نامناسب با مشتری", 5, 10, 20),
            ("V03", "صحبت با همکاران در حضور مشتری", 3, 6, 12),
            ("V04", "رعایت نکردن پوشش سازمانی", 2, 4, 8),
        ]
        for code, title, a, b, c in rules:
            ViolationRule.objects.update_or_create(
                code=code,
                defaults={"title": title, "first_points": a, "second_points": b, "third_points": c, "is_active": True}
            )

        for title, points, reward in [("تارگت نقره‌ای", 100, 500000), ("تارگت طلایی", 250, 1200000), ("تارگت الماس", 400, 2500000)]:
            Target.objects.update_or_create(title=title, defaults={"points": points, "reward": reward, "is_active": True})

        SystemSettings.load()

        # ۸. نمونه کارکردهای روزانه شیفت و آمار فروش برای امروز و دیروز
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        morning_shift = shifts["MORNING"]

        # آمار فروش ثبت شده توسط مدیر برای دیروز و امروز
        LineShiftPerformance.objects.update_or_create(
            date=yesterday,
            shift=morning_shift,
            department=depts["شلوار"],
            defaults={"sold_units": 40, "sales_amount": 200000000, "recorded_by": mgr_user}
        )
        LineShiftPerformance.objects.update_or_create(
            date=today,
            shift=morning_shift,
            department=depts["شلوار"],
            defaults={"sold_units": 50, "sales_amount": 250000000, "recorded_by": mgr_user, "description": "فروش عالی شلوار"}
        )
        LineShiftPerformance.objects.update_or_create(
            date=today,
            shift=morning_shift,
            department=depts["پیراهن"],
            defaults={"sold_units": 35, "sales_amount": 180000000, "recorded_by": mgr_user, "description": "فروش پیراهن"}
        )
        LineShiftPerformance.objects.update_or_create(
            date=today,
            shift=morning_shift,
            department=depts["اکسسوری"],
            defaults={"sold_units": 20, "sales_amount": 60000000, "recorded_by": mgr_user, "description": "فروش اکسسوری"}
        )

        # کارکرد دیروز سارا (تأییدشده و فریز شده توسط مدیر)
        sara_log_yesterday, _ = DailyShiftLog.objects.update_or_create(
            employee=employees["sara"],
            date=yesterday,
            shift=morning_shift,
            defaults={
                "main_department": depts["شلوار"],
                "main_hours": Decimal("6.0"),
                "has_support_line": False,
                "support_hours": Decimal("0.0"),
                "total_hours": Decimal("6.0"),
                "status": DailyShiftLog.Status.PENDING,
            }
        )
        approve_shift_log(sara_log_yesterday, mgr_user, "تأیید و واریز شد.")

        # کارکرد امروز سارا (در انتظار بررسی مدیر)
        sara_log_today, _ = DailyShiftLog.objects.update_or_create(
            employee=employees["sara"],
            date=today,
            shift=morning_shift,
            defaults={
                "main_department": depts["شلوار"],
                "main_hours": Decimal("6.0"),
                "has_support_line": False,
                "support_hours": Decimal("0.0"),
                "total_hours": Decimal("6.0"),
                "status": DailyShiftLog.Status.PENDING,
                "employee_note": "حضور در شیفت صبح لاین شلوار",
            }
        )

        # کارکرد امروز فاطمه (با دو لاین کمکی پیراهن و اکسسوری - در انتظار بررسی مدیر)
        fatemeh_log, _ = DailyShiftLog.objects.update_or_create(
            employee=employees["fatemeh"],
            date=today,
            shift=morning_shift,
            defaults={
                "main_department": depts["شلوار"],
                "main_hours": Decimal("4.0"),
                "has_support_line": True,
                "support_hours": Decimal("2.0"),
                "total_hours": Decimal("6.0"),
                "status": DailyShiftLog.Status.PENDING,
                "employee_note": "کمک به لاین‌های اکسسوری و پیراهن در تایم شلوغی",
            }
        )
        fatemeh_log.support_departments.set([depts["اکسسوری"], depts["پیراهن"]])

        # کارکرد امروز علی (در انتظار بررسی مدیر)
        ali_log, _ = DailyShiftLog.objects.update_or_create(
            employee=employees["ali"],
            date=today,
            shift=morning_shift,
            defaults={
                "main_department": depts["پیراهن"],
                "main_hours": Decimal("6.0"),
                "has_support_line": False,
                "support_hours": Decimal("0.0"),
                "total_hours": Decimal("6.0"),
                "status": DailyShiftLog.Status.PENDING,
                "employee_note": "فروش شیفت صبح پیراهن",
            }
        )

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("داده‌های اولیه، تارگت‌های ماهانه و پرسنل با موفقیت ایجاد شدند:"))
        self.stdout.write("  ۱. مدیر سیستم: نام کاربری `manager` | رمز: `Elinor123!`")
        self.stdout.write("  ۲. کارمند نمونه ۱: نام کاربری `sara` (کد: 1002) | رمز: `Elinor123!` | گرید A")
        self.stdout.write("  ۳. کارمند نمونه ۲: نام کاربری `ali` (کد: 1003) | رمز: `Elinor123!` | گرید B")
        self.stdout.write("  ۴. کارمند نمونه ۳: نام کاربری `fatemeh` (کد: 1004) | رمز: `Elinor123!` | گرید A")
        self.stdout.write("  ۵. کارمند نمونه ۴: نام کاربری `maryam` (کد: 1005) | رمز: `Elinor123!` | گرید C")
        self.stdout.write(self.style.SUCCESS("=" * 60))
