from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import DecimalField, Sum
from django.db.models.functions import Coalesce
from django.db import transaction
from django.utils import timezone
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
    Violation,
)

def audit(*, actor, action, instance, description="", old_values=None, new_values=None):
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        entity_type=instance.__class__.__name__,
        entity_id=str(instance.pk),
        description=description,
        old_values=old_values or {},
        new_values=new_values or {},
    )

@transaction.atomic
def change_employee_level(employee, new_level, actor, reason=""):
    previous = employee.commission_level
    if previous_id := getattr(previous, "pk", None):
        if previous_id == new_level.pk:
            return False
    employee.commission_level = new_level
    employee.save(update_fields=["commission_level", "updated_at"])
    EmployeeLevelHistory.objects.create(
        employee=employee, previous_level=previous, new_level=new_level, changed_by=actor, reason=reason
    )
    audit(
        actor=actor,
        action="employee.level_changed",
        instance=employee,
        description=reason,
        old_values={"commission_level": previous.code},
        new_values={"commission_level": new_level.code},
    )
    return True

@transaction.atomic
def get_line_rate(department, commission_level):
    """نرخ پورسانت به ازای هر کالا را بر اساس لاین و گرید کارمند برمی‌گرداند."""
    rate_obj = LineCommissionRate.objects.filter(
        department=department,
        commission_level=commission_level,
        is_active=True,
    ).first()
    if rate_obj:
        return rate_obj.rate_per_unit
    return commission_level.performance_rate if commission_level else 1000

def find_target_shift_for_overtime(overtime_start_time, current_shift):
    """یافتن شیفت متناظری که بازه اضافه‌کاری در محدوده آن واقع شده است."""
    if not overtime_start_time:
        return None
    active_shifts = list(Shift.objects.filter(is_active=True))
    t_min = overtime_start_time.hour * 60 + overtime_start_time.minute
    for s in active_shifts:
        if s.pk == current_shift.pk:
            continue
        s_min = s.start_time.hour * 60 + s.start_time.minute
        e_min = s.end_time.hour * 60 + s.end_time.minute
        if e_min <= s_min:
            e_min += 24 * 60
        if s_min <= t_min < e_min:
            return s
    next_shifts = [s for s in active_shifts if s.pk != current_shift.pk and s.sort_order > current_shift.sort_order]
    if next_shifts:
        return next_shifts[0]
    other_shifts = [s for s in active_shifts if s.pk != current_shift.pk]
    return other_shifts[0] if other_shifts else None

def calculate_single_shift_log(shift_log, force_dynamic=False):
    """محاسبه جزئیات سهم فروش و پورسانت یک رکورد کارکرد شیفت (پشتیبانی از فریز، چند لاین کمکی و اضافه‌کاری)."""
    # در صورت فریز بودن و عدم درخواست محاسبه مجدد، مقادیر فریز شده برگردانده می‌شوند
    if shift_log.is_frozen and not force_dynamic and shift_log.frozen_snapshot_data:
        snap = shift_log.frozen_snapshot_data
        return {
            "shift_log": shift_log,
            "main_info": snap.get("main_info"),
            "support_infos": snap.get("support_infos", []),
            "support_info": snap.get("support_infos", [None])[0] if snap.get("support_infos") else None,
            "overtime_info": snap.get("overtime_info"),
            "total_units_share": Decimal(str(shift_log.frozen_total_units_share)),
            "total_commission": shift_log.frozen_commission_amount,
            "is_frozen": True,
        }

    date = shift_log.date
    shift = shift_log.shift
    employee = shift_log.employee
    level = employee.commission_level

    # تمام کارکردهای همان تاریخ و شیفت برای تسهیم ساعات (به جز کارکردهای ردشده)
    sibling_logs = list(
        DailyShiftLog.objects.filter(date=date, shift=shift).exclude(
            status=DailyShiftLog.Status.REJECTED
        ).select_related(
            "employee", "main_department"
        ).prefetch_related("support_departments", "support_intervals__department")
    )

    def support_hours_by_department(log):
        intervals = list(log.support_intervals.all())
        if intervals:
            result = {}
            for interval in intervals:
                result[interval.department_id] = result.get(interval.department_id, Decimal("0")) + interval.duration_hours
            return result
        departments = list(log.support_departments.all())
        if not departments:
            return {}
        hours_each = (log.support_hours or Decimal("0")) / Decimal(len(departments))
        return {department.pk: hours_each for department in departments}

    # محاسبه ساعات کل حضور پرسنل در هر لاین در این شیفت
    dept_total_hours = {}
    for log in sibling_logs:
        log_emp = log.employee
        log_main_h = log.main_hours
        if (log_main_h is None or log_main_h <= Decimal("0.0")) and log.shift:
            log_main_h = max(Decimal("0.0"), (log.shift.standard_hours or Decimal("6.0")) - (log.support_hours or Decimal("0.0")))

        # تمام لاین‌های اصلی کارمند در شیفت منظور می‌شوند
        p_depts = log_emp.get_primary_departments() if hasattr(log_emp, "get_primary_departments") else []
        if not p_depts and log.main_department:
            p_depts = [log.main_department]

        for p_dept in p_depts:
            if log_main_h > Decimal("0.0"):
                dept_total_hours[p_dept.pk] = dept_total_hours.get(p_dept.pk, Decimal("0.0")) + log_main_h

        for department_id, hours in support_hours_by_department(log).items():
            dept_total_hours[department_id] = dept_total_hours.get(department_id, Decimal("0.0")) + hours

    # احتساب ساعت‌های اضافه‌کاری پرسنل سایر شیفت‌ها که به این شیفت اختصاص یافته است
    other_logs_with_ot = DailyShiftLog.objects.filter(
        date=date,
        has_overtime=True,
        overtime_hours__gt=Decimal("0.0"),
    ).exclude(shift=shift).exclude(status=DailyShiftLog.Status.REJECTED).select_related("overtime_department", "main_department")

    for o_log in other_logs_with_ot:
        ot_target = find_target_shift_for_overtime(o_log.overtime_start_time, o_log.shift)
        if ot_target and ot_target.pk == shift.pk:
            ot_dept = o_log.overtime_department or o_log.main_department
            if ot_dept:
                dept_total_hours[ot_dept.pk] = dept_total_hours.get(ot_dept.pk, Decimal("0.0")) + (o_log.overtime_hours or Decimal("0.0"))

    def compute_line(dept, hours):
        if not dept or hours <= 0:
            return None

        # قانون لاین صندوقدار: محاسبه مستقیم بر اساس تعداد فاکتورهای صادرشده کارمند
        if getattr(dept, "is_cashier", False):
            inv_count = shift_log.invoice_count or 0
            share_units = Decimal(inv_count)
            rate = get_line_rate(dept, level)
            commission = int(share_units * Decimal(rate))
            return {
                "department": dept,
                "department_id": dept.pk,
                "department_name": dept.name,
                "is_cashier": True,
                "hours": round(hours, 2),
                "total_dept_hours": round(hours, 2),
                "total_sold_units": inv_count,
                "share_units": round(share_units, 2),
                "rate_per_unit": rate,
                "commission": commission,
                "has_performance_recorded": True,
            }

        total_dept_hours = dept_total_hours.get(dept.pk, Decimal("0.0"))

        # خواندن آمار فروش ثبت‌شده توسط مدیر
        perf = LineShiftPerformance.objects.filter(date=date, shift=shift, department=dept).first()
        total_sold = perf.sold_units if perf else 0

        # محاسبه سهم کارمند
        if total_dept_hours > Decimal("0.0"):
            share_units = (Decimal(hours) / total_dept_hours) * Decimal(total_sold)
        else:
            share_units = Decimal("0.0")

        rate = get_line_rate(dept, level)
        commission = int(share_units * Decimal(rate))

        return {
            "department": dept,
            "department_id": dept.pk if dept else None,
            "department_name": dept.name if dept else "",
            "hours": round(hours, 2),
            "total_dept_hours": round(total_dept_hours, 2),
            "total_sold_units": total_sold,
            "share_units": round(share_units, 2),
            "rate_per_unit": rate,
            "commission": commission,
            "has_performance_recorded": perf is not None,
        }

    shift_log_main_h = shift_log.main_hours
    if (shift_log_main_h is None or shift_log_main_h <= Decimal("0.0")) and shift_log.shift:
        shift_log_main_h = max(Decimal("0.0"), (shift_log.shift.standard_hours or Decimal("6.0")) - (shift_log.support_hours or Decimal("0.0")))

    # محاسبه برای تمام لاین‌های اصلی کارمند
    emp_p_depts = employee.get_primary_departments() if hasattr(employee, "get_primary_departments") else []
    if not emp_p_depts and shift_log.main_department:
        emp_p_depts = [shift_log.main_department]

    primary_infos = []
    for p_dept in emp_p_depts:
        info = compute_line(p_dept, shift_log_main_h)
        if info:
            primary_infos.append(info)

    main_info = primary_infos[0] if primary_infos else None

    support_infos = []
    if shift_log.has_support_line and (shift_log.support_hours or Decimal("0.0")) > Decimal("0.0"):
        departments = {department.pk: department for department in shift_log.support_departments.all()}
        for department_id, hours in support_hours_by_department(shift_log).items():
            s_dept = departments.get(department_id)
            if s_dept:
                info = compute_line(s_dept, hours)
                if info:
                    support_infos.append(info)

    total_units_share = Decimal("0.0")
    total_commission = 0

    for p_info in primary_infos:
        total_units_share += Decimal(str(p_info["share_units"]))
        total_commission += p_info["commission"]

    for s_info in support_infos:
        total_units_share += Decimal(str(s_info["share_units"]))
        total_commission += s_info["commission"]

    # محاسبه سهم فروش و پورسانت اضافه‌کاری از شیفت متناظر
    overtime_info = None
    if shift_log.has_overtime and (shift_log.overtime_hours or Decimal("0.0")) > Decimal("0.0"):
        ot_dept = shift_log.overtime_department or shift_log.main_department
        ot_target_shift = find_target_shift_for_overtime(shift_log.overtime_start_time, shift)
        if ot_dept and ot_target_shift:
            target_sibling_logs = list(
                DailyShiftLog.objects.filter(date=date, shift=ot_target_shift).exclude(
                    status=DailyShiftLog.Status.REJECTED
                ).select_related("employee", "main_department").prefetch_related("support_departments", "support_intervals__department")
            )
            target_dept_hours = Decimal("0.0")
            for t_log in target_sibling_logs:
                t_main_h = t_log.main_hours
                if (t_main_h is None or t_main_h <= Decimal("0.0")) and t_log.shift:
                    t_main_h = max(Decimal("0.0"), (t_log.shift.standard_hours or Decimal("6.0")) - (t_log.support_hours or Decimal("0.0")))
                t_p_depts = t_log.employee.get_primary_departments() if hasattr(t_log.employee, "get_primary_departments") else []
                if not t_p_depts and t_log.main_department:
                    t_p_depts = [t_log.main_department]
                if any(p.pk == ot_dept.pk for p in t_p_depts):
                    target_dept_hours += t_main_h
                for department_id, hours in support_hours_by_department(t_log).items():
                    if department_id == ot_dept.pk:
                        target_dept_hours += hours

            target_ot_logs = DailyShiftLog.objects.filter(
                date=date,
                has_overtime=True,
                overtime_hours__gt=Decimal("0.0"),
            ).exclude(shift=ot_target_shift).exclude(status=DailyShiftLog.Status.REJECTED).select_related("overtime_department", "main_department")

            for t_ot_log in target_ot_logs:
                if find_target_shift_for_overtime(t_ot_log.overtime_start_time, t_ot_log.shift) == ot_target_shift:
                    t_ot_d = t_ot_log.overtime_department or t_ot_log.main_department
                    if t_ot_d and t_ot_d.pk == ot_dept.pk:
                        target_dept_hours += (t_ot_log.overtime_hours or Decimal("0.0"))

            target_perf = LineShiftPerformance.objects.filter(
                date=date, shift=ot_target_shift, department=ot_dept
            ).first()
            target_total_sold = target_perf.sold_units if target_perf else 0

            if target_dept_hours > Decimal("0.0"):
                ot_share_units = ((shift_log.overtime_hours or Decimal("0.0")) / target_dept_hours) * Decimal(target_total_sold)
            else:
                ot_share_units = Decimal("0.0")

            ot_rate = get_line_rate(ot_dept, level)
            ot_commission = int(ot_share_units * Decimal(ot_rate))

            overtime_info = {
                "department": ot_dept,
                "department_id": ot_dept.pk,
                "department_name": ot_dept.name,
                "target_shift": ot_target_shift,
                "target_shift_title": ot_target_shift.title,
                "hours": round(shift_log.overtime_hours, 2),
                "start_time": shift_log.overtime_start_time.strftime("%H:%M") if shift_log.overtime_start_time else "",
                "end_time": shift_log.overtime_end_time.strftime("%H:%M") if shift_log.overtime_end_time else "",
                "total_dept_hours": round(target_dept_hours, 2),
                "total_sold_units": target_total_sold,
                "share_units": round(ot_share_units, 2),
                "rate_per_unit": ot_rate,
                "commission": ot_commission,
                "has_performance_recorded": target_perf is not None,
            }
            total_units_share += Decimal(str(round(ot_share_units, 2)))
            total_commission += ot_commission

    return {
        "shift_log": shift_log,
        "primary_infos": primary_infos,
        "main_info": main_info,
        "support_infos": support_infos,
        "support_info": support_infos[0] if len(support_infos) == 1 else None,
        "overtime_info": overtime_info,
        "total_units_share": round(total_units_share, 2),
        "total_commission": total_commission,
        "is_frozen": False,
    }

def check_shift_completion(date, shift):
    """بررسی پیش‌شرط مرحله اول: همه کارمندان موظف این شیفت باید تعیین تکلیف شده باشند."""
    expected_employees = list(Employee.objects.filter(
        is_active=True,
        role=Employee.Role.EMPLOYEE,
        default_shift=shift,
    ))
    if not expected_employees:
        return

    logged_emp_ids = set(DailyShiftLog.objects.filter(
        date=date, shift=shift
    ).values_list("employee_id", flat=True))

    missing = [emp for emp in expected_employees if emp.pk not in logged_emp_ids]
    if missing:
        missing_names = "، ".join(emp.full_name for emp in missing)
        raise ValidationError(
            f"تأیید نهایی امکان‌پذیر نیست: هنوز تمام کارمندان این شیفت تعیین تکلیف نشده‌اند. پرسنل ثبت‌نشده: {missing_names} (باید کارکرد ثبت شود یا مرخصی رد گردد)."
        )

def sync_shift_logs_for_performance(date, shift, exclude_log_id=None):
    """به‌روزرسانی خودکار سهم کالا و پورسانت تمام کارکردهای تأییدشده شیفت پس از تغییر ساعات یا ثبت فروش لاین."""
    qs = DailyShiftLog.objects.filter(date=date, shift=shift, status=DailyShiftLog.Status.APPROVED)
    if exclude_log_id:
        qs = qs.exclude(pk=exclude_log_id)

    for other_log in qs:
        c = calculate_single_shift_log(other_log, force_dynamic=True)
        other_log.frozen_main_share_units = Decimal(str(c["main_info"]["share_units"])) if c.get("main_info") else Decimal("0.0")
        other_log.frozen_support_share_units = sum(Decimal(str(s["share_units"])) for s in c.get("support_infos", []))
        other_log.frozen_total_units_share = Decimal(str(c["total_units_share"]))
        other_log.frozen_commission_amount = c["total_commission"]

        s_main = None
        if c.get("main_info"):
            m = c["main_info"]
            s_main = {
                "department_id": m["department"].pk,
                "department_name": m["department"].name,
                "hours": float(m["hours"]),
                "total_dept_hours": float(m["total_dept_hours"]),
                "total_sold_units": m["total_sold_units"],
                "share_units": float(m["share_units"]),
                "rate_per_unit": m["rate_per_unit"],
                "commission": m["commission"],
            }
        s_supp = []
        for s in c.get("support_infos", []):
            s_supp.append({
                "department_id": s["department"].pk,
                "department_name": s["department"].name,
                "hours": float(s["hours"]),
                "total_dept_hours": float(s["total_dept_hours"]),
                "total_sold_units": s["total_sold_units"],
                "share_units": float(s["share_units"]),
                "rate_per_unit": s["rate_per_unit"],
                "commission": s["commission"],
            })
        s_ot = None
        if c.get("overtime_info"):
            ot = c["overtime_info"]
            s_ot = {
                "department_id": ot["department"].pk,
                "department_name": ot["department"].name,
                "target_shift_title": ot.get("target_shift_title", ""),
                "hours": float(ot["hours"]),
                "start_time": ot.get("start_time", ""),
                "end_time": ot.get("end_time", ""),
                "total_dept_hours": float(ot["total_dept_hours"]),
                "total_sold_units": ot["total_sold_units"],
                "share_units": float(ot["share_units"]),
                "rate_per_unit": ot["rate_per_unit"],
                "commission": ot["commission"],
            }
        other_log.frozen_overtime_share_units = Decimal(str(c["overtime_info"]["share_units"])) if c.get("overtime_info") else Decimal("0.0")
        other_log.frozen_snapshot_data = {
            "main_info": s_main,
            "support_infos": s_supp,
            "overtime_info": s_ot,
            "total_units_share": float(c["total_units_share"]),
            "total_commission": c["total_commission"],
            "frozen_at": timezone.now().isoformat(),
            "actor": "system_sync",
        }
        other_log.save(update_fields=[
            "frozen_main_share_units",
            "frozen_support_share_units",
            "frozen_overtime_share_units",
            "frozen_total_units_share",
            "frozen_commission_amount",
            "frozen_snapshot_data",
        ])

@transaction.atomic
def approve_shift_log(shift_log, actor, manager_note=""):
    """تأیید کارکرد روزانه شیفت و فریز کردن قطعی محاسبات سهم فروش و پورسانت."""
    check_shift_completion(shift_log.date, shift_log.shift)

    calc = calculate_single_shift_log(shift_log, force_dynamic=True)

    shift_log.status = DailyShiftLog.Status.APPROVED
    shift_log.reviewed_by = actor
    shift_log.reviewed_at = timezone.now()
    shift_log.manager_note = manager_note
    shift_log.is_frozen = True
    shift_log.frozen_main_share_units = Decimal(str(calc["main_info"]["share_units"])) if calc.get("main_info") else Decimal("0.0")

    supp_units = sum(Decimal(str(s["share_units"])) for s in calc.get("support_infos", []))
    shift_log.frozen_support_share_units = supp_units
    shift_log.frozen_overtime_share_units = Decimal(str(calc["overtime_info"]["share_units"])) if calc.get("overtime_info") else Decimal("0.0")
    shift_log.frozen_total_units_share = Decimal(str(calc["total_units_share"]))
    shift_log.frozen_commission_amount = calc["total_commission"]

    # ساخت ساختار سریالایزپذیر برای JSONField
    serializable_main_info = None
    if calc.get("main_info"):
        m = calc["main_info"]
        serializable_main_info = {
            "department_id": m["department"].pk,
            "department_name": m["department"].name,
            "hours": float(m["hours"]),
            "total_dept_hours": float(m["total_dept_hours"]),
            "total_sold_units": m["total_sold_units"],
            "share_units": float(m["share_units"]),
            "rate_per_unit": m["rate_per_unit"],
            "commission": m["commission"],
        }

    serializable_supp_infos = []
    for s in calc.get("support_infos", []):
        serializable_supp_infos.append({
            "department_id": s["department"].pk,
            "department_name": s["department"].name,
            "hours": float(s["hours"]),
            "total_dept_hours": float(s["total_dept_hours"]),
            "total_sold_units": s["total_sold_units"],
            "share_units": float(s["share_units"]),
            "rate_per_unit": s["rate_per_unit"],
            "commission": s["commission"],
        })

    serializable_ot_info = None
    if calc.get("overtime_info"):
        ot = calc["overtime_info"]
        serializable_ot_info = {
            "department_id": ot["department"].pk,
            "department_name": ot["department"].name,
            "target_shift_title": ot.get("target_shift_title", ""),
            "hours": float(ot["hours"]),
            "start_time": ot.get("start_time", ""),
            "end_time": ot.get("end_time", ""),
            "total_dept_hours": float(ot["total_dept_hours"]),
            "total_sold_units": ot["total_sold_units"],
            "share_units": float(ot["share_units"]),
            "rate_per_unit": ot["rate_per_unit"],
            "commission": ot["commission"],
        }

    shift_log.frozen_snapshot_data = {
        "main_info": serializable_main_info,
        "support_infos": serializable_supp_infos,
        "overtime_info": serializable_ot_info,
        "total_units_share": float(calc["total_units_share"]),
        "total_commission": calc["total_commission"],
        "frozen_at": timezone.now().isoformat(),
        "actor": actor.username,
    }
    shift_log.save()

    audit(
        actor=actor,
        action="shift_log.approved",
        instance=shift_log,
        description=manager_note,
        new_values={
            "status": DailyShiftLog.Status.APPROVED,
            "commission": shift_log.frozen_commission_amount,
            "total_units_share": str(shift_log.frozen_total_units_share),
        }
    )
    return shift_log

@transaction.atomic
def reject_shift_log(shift_log, actor, manager_note=""):
    """رد کارکرد روزانه شیفت."""
    shift_log.status = DailyShiftLog.Status.REJECTED
    shift_log.reviewed_by = actor
    shift_log.reviewed_at = timezone.now()
    shift_log.manager_note = manager_note
    shift_log.is_frozen = False
    shift_log.frozen_commission_amount = 0
    shift_log.frozen_total_units_share = Decimal("0.0")
    shift_log.save()

    audit(
        actor=actor,
        action="shift_log.rejected",
        instance=shift_log,
        description=manager_note,
        new_values={"status": DailyShiftLog.Status.REJECTED}
    )
    return shift_log

@transaction.atomic
def revert_shift_log_to_pending(shift_log, actor, reason=""):
    """خروج از حالت فریز/تأیید و بازگشت کارکرد به وضعیت در انتظار بررسی."""
    old_values = {
        "status": shift_log.status,
        "is_frozen": shift_log.is_frozen,
        "frozen_commission_amount": shift_log.frozen_commission_amount,
        "frozen_total_units_share": str(shift_log.frozen_total_units_share),
    }
    shift_log.status = DailyShiftLog.Status.PENDING
    shift_log.reviewed_by = None
    shift_log.reviewed_at = None
    shift_log.manager_note = reason
    shift_log.is_frozen = False
    shift_log.frozen_main_share_units = Decimal("0.0")
    shift_log.frozen_support_share_units = Decimal("0.0")
    shift_log.frozen_total_units_share = Decimal("0.0")
    shift_log.frozen_commission_amount = 0
    shift_log.frozen_snapshot_data = {}
    shift_log.save()

    audit(
        actor=actor,
        action="shift_log.reverted_to_pending",
        instance=shift_log,
        description=reason or "بازگشت به وضعیت در انتظار بررسی توسط مدیر",
        old_values=old_values,
        new_values={"status": DailyShiftLog.Status.PENDING, "is_frozen": False},
    )
    return shift_log

def employee_metrics(employee, start, end):
    """محاسبه جامع پورسانت، عملکرد فروش، تخلفات و تارگت برای دوره مشخص."""
    # ۱. کارکردهای شیفت در بازه زمانی
    shift_logs = list(
        employee.shift_logs.filter(date__range=(start, end)).select_related(
            "shift", "main_department", "reviewed_by"
        ).prefetch_related("support_departments")
    )

    shift_log_details = [calculate_single_shift_log(log) for log in shift_logs]

    total_sales_units_share = sum(d["total_units_share"] for d in shift_log_details)
    gross_sales_commission = sum(d["total_commission"] for d in shift_log_details)

    # ۲. فعالیت‌های قدیمی از مدل عملیاتی سیستم حذف شده‌اند.
    # این دو مقدار برای سازگاری خروجی گزارش‌های قدیمی فعلاً صفر نگه داشته می‌شوند.
    activity_score = Decimal("0")
    activity_gross = 0

    # ۳. تخلفات
    violation_points = employee.violations.filter(violation_date__range=(start, end)).aggregate(
        v=Coalesce(Sum("points_snapshot"), 0)
    )["v"]
    deduction = int(violation_points * employee.level.violation_rate)

    # ۴. تارگت عملکرد لاین اصلی بر اساس مجموع سهم واقعی کالا در ماه
    total_effective_score = float(total_sales_units_share)
    line_target = None
    target_result = None
    if employee.primary_department_id:
        line_target = LineTarget.objects.filter(
            department_id=employee.primary_department_id,
            is_active=True,
        ).first()
    if line_target:
        target_result = line_target.evaluate_target(total_sales_units_share)
    reward = target_result["reward_amount"] if target_result else 0

    total_gross = gross_sales_commission
    net_commission = max(0, total_gross - deduction + reward)

    approved_shift_logs_count = sum(1 for log in shift_logs if log.status == DailyShiftLog.Status.APPROVED)
    pending_shift_logs_count = sum(1 for log in shift_logs if log.status == DailyShiftLog.Status.PENDING)

    approved_commission = sum(
        d["total_commission"] for d in shift_log_details
        if d["shift_log"].status == DailyShiftLog.Status.APPROVED
    )
    pending_commission = sum(
        d["total_commission"] for d in shift_log_details
        if d["shift_log"].status == DailyShiftLog.Status.PENDING
    )
    wallet_balance = max(0, approved_commission - deduction + reward)

    return {
        "score": round(Decimal(str(total_effective_score)), 2),
        "total_sales_units_share": round(total_sales_units_share, 2),
        "gross_sales_commission": gross_sales_commission,
        "activity_score": activity_score,
        "activity_gross": activity_gross,
        "gross": total_gross,
        "violation_points": violation_points,
        "deduction": deduction,
        "reward": reward,
        "commission": net_commission,
        "approved_commission": approved_commission,
        "pending_commission": pending_commission,
        "wallet_balance": wallet_balance,
        "line_target": line_target,
        "line_target_result": target_result,
        "next_target": target_result["next_target_title"] if target_result else None,
        "target_progress": target_result["progress_percent"] if target_result else 0,
        "shift_logs_count": len(shift_logs),
        "approved_shift_logs_count": approved_shift_logs_count,
        "pending_shift_logs_count": pending_shift_logs_count,
        "shift_log_details": shift_log_details,
        "approved_count": 0,
    }
