from decimal import Decimal
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

def calculate_single_shift_log(shift_log, force_dynamic=False):
    """محاسبه جزئیات سهم فروش و پورسانت یک رکورد کارکرد شیفت (پشتیبانی از فریز و چند لاین کمکی)."""
    # در صورت فریز بودن و عدم درخواست محاسبه مجدد، مقادیر فریز شده برگردانده می‌شوند
    if shift_log.is_frozen and not force_dynamic and shift_log.frozen_snapshot_data:
        snap = shift_log.frozen_snapshot_data
        return {
            "shift_log": shift_log,
            "main_info": snap.get("main_info"),
            "support_infos": snap.get("support_infos", []),
            "support_info": snap.get("support_infos", [None])[0] if snap.get("support_infos") else None,
            "total_units_share": Decimal(str(shift_log.frozen_total_units_share)),
            "total_commission": shift_log.frozen_commission_amount,
            "is_frozen": True,
        }

    date = shift_log.date
    shift = shift_log.shift
    employee = shift_log.employee
    level = employee.commission_level

    # تمام کارکردهای همان تاریخ و شیفت برای تسهیم ساعات
    sibling_logs = list(
        DailyShiftLog.objects.filter(date=date, shift=shift).select_related(
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
        if log.main_department_id:
            dept_total_hours[log.main_department_id] = dept_total_hours.get(log.main_department_id, Decimal("0.0")) + (log.main_hours or Decimal("0.0"))

        for department_id, hours in support_hours_by_department(log).items():
            dept_total_hours[department_id] = dept_total_hours.get(department_id, Decimal("0.0")) + hours

    def compute_line(dept, hours):
        if not dept or hours <= 0:
            return None

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

    main_info = compute_line(shift_log.main_department, shift_log.main_hours)

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

    if main_info:
        total_units_share += Decimal(str(main_info["share_units"]))
        total_commission += main_info["commission"]

    for s_info in support_infos:
        total_units_share += Decimal(str(s_info["share_units"]))
        total_commission += s_info["commission"]

    return {
        "shift_log": shift_log,
        "main_info": main_info,
        "support_infos": support_infos,
        "support_info": support_infos[0] if len(support_infos) == 1 else None,
        "total_units_share": round(total_units_share, 2),
        "total_commission": total_commission,
        "is_frozen": False,
    }

@transaction.atomic
def approve_shift_log(shift_log, actor, manager_note=""):
    """تأیید کارکرد روزانه شیفت و فریز کردن قطعی محاسبات سهم فروش و پورسانت."""
    calc = calculate_single_shift_log(shift_log, force_dynamic=True)

    shift_log.status = DailyShiftLog.Status.APPROVED
    shift_log.reviewed_by = actor
    shift_log.reviewed_at = timezone.now()
    shift_log.manager_note = manager_note
    shift_log.is_frozen = True
    shift_log.frozen_main_share_units = Decimal(str(calc["main_info"]["share_units"])) if calc.get("main_info") else Decimal("0.0")

    supp_units = sum(Decimal(str(s["share_units"])) for s in calc.get("support_infos", []))
    shift_log.frozen_support_share_units = supp_units
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

    shift_log.frozen_snapshot_data = {
        "main_info": serializable_main_info,
        "support_infos": serializable_supp_infos,
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
