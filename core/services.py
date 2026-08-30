from decimal import Decimal
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.db import transaction
from .models import (
    AuditLog,
    CommissionLevel,
    DailyShiftLog,
    Department,
    Employee,
    EmployeeLevelHistory,
    LineCommissionRate,
    LineShiftPerformance,
    Target,
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

def calculate_single_shift_log(shift_log):
    """محاسبه جزئیات سهم فروش و پورسانت یک رکورد کارکرد شیفت (پشتیبانی از چندین لاین کمکی)."""
    date = shift_log.date
    shift = shift_log.shift
    employee = shift_log.employee
    level = employee.commission_level

    # تمام کارکردهای همان تاریخ و شیفت برای تسهیم ساعات
    sibling_logs = list(
        DailyShiftLog.objects.filter(date=date, shift=shift).select_related(
            "employee", "main_department"
        ).prefetch_related("support_departments")
    )

    # محاسبه ساعات کل حضور پرسنل در هر لاین در این شیفت
    dept_total_hours = {}
    for log in sibling_logs:
        if log.main_department_id:
            dept_total_hours[log.main_department_id] = dept_total_hours.get(log.main_department_id, Decimal("0.0")) + (log.main_hours or Decimal("0.0"))

        if log.has_support_line and (log.support_hours or Decimal("0.0")) > Decimal("0.0"):
            supp_list = list(log.support_departments.all())
            if supp_list:
                hours_each = (log.support_hours or Decimal("0.0")) / Decimal(len(supp_list))
                for s_dept in supp_list:
                    dept_total_hours[s_dept.pk] = dept_total_hours.get(s_dept.pk, Decimal("0.0")) + hours_each

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
        supp_list = list(shift_log.support_departments.all())
        if supp_list:
            hours_each = (shift_log.support_hours or Decimal("0.0")) / Decimal(len(supp_list))
            for s_dept in supp_list:
                info = compute_line(s_dept, hours_each)
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
    }

def employee_metrics(employee, start, end):
    """محاسبه جامع پورسانت، عملکرد فروش، تخلفات و تارگت برای دوره مشخص."""
    # ۱. محاسبه فروش لاین‌ها از کارکردهای روزانه
    shift_logs = list(
        employee.shift_logs.filter(date__range=(start, end)).select_related(
            "shift", "main_department"
        ).prefetch_related("support_departments")
    )

    shift_log_details = [calculate_single_shift_log(log) for log in shift_logs]

    total_sales_units_share = sum(d["total_units_share"] for d in shift_log_details)
    gross_sales_commission = sum(d["total_commission"] for d in shift_log_details)

    # ۲. تخلفات
    violation_points = employee.violations.filter(violation_date__range=(start, end)).aggregate(
        v=Coalesce(Sum("points_snapshot"), 0)
    )["v"]
    deduction = int(violation_points * employee.level.violation_rate)

    # ۳. تارگت‌ها بر اساس سهم فروش
    total_effective_score = float(total_sales_units_share)
    reached = Target.objects.filter(is_active=True, points__lte=total_effective_score).order_by("-points").first()
    reward = reached.reward if reached else 0
    targets = list(Target.objects.filter(is_active=True))
    next_target = next((t for t in targets if t.points > total_effective_score), None)

    total_gross = gross_sales_commission
    net_commission = max(0, total_gross - deduction + reward)

    return {
        "score": round(Decimal(str(total_effective_score)), 2),
        "total_sales_units_share": round(total_sales_units_share, 2),
        "gross_sales_commission": gross_sales_commission,
        "gross": total_gross,
        "violation_points": violation_points,
        "deduction": deduction,
        "reward": reward,
        "commission": net_commission,
        "next_target": next_target,
        "target_progress": min(100, int(total_effective_score * 100 / next_target.points)) if next_target else 100,
        "shift_logs_count": len(shift_logs),
        "shift_log_details": shift_log_details,
    }
