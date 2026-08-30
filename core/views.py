from datetime import date, timedelta
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
import jdatetime
from .decorators import manager_required, reviewer_required
from .forms import (
    ActivityForm,
    ActivityTypeForm,
    BrandingForm,
    DailyShiftLogForm,
    SupportLineIntervalFormSet,
    EmployeeCreateForm,
    EmployeeEditForm,
    JalaliDateField,
    LineShiftPerformanceForm,
    ManagerPasswordResetForm,
    ProfilePhotoForm,
    ReviewForm,
    ShiftForm,
    ViolationForm,
)
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
    LineCommissionRate,
    LineShiftPerformance,
    Shift,
    SupportLineInterval,
    SystemSettings,
    Violation,
)
from .services import audit, change_employee_level, employee_metrics, transition_activity

def health(request):
    return JsonResponse({"status": "ok"})

def month_range(day=None):
    day = day or timezone.localdate()
    start = day.replace(day=1)
    end = start.replace(month=start.month % 12 + 1, year=start.year + (start.month == 12)) - timedelta(days=1)
    return start, end

def supervised_employees(employee):
    qs = Employee.objects.filter(is_active=True)
    return qs

@login_required
def dashboard(request):
    employee = getattr(request.user, "employee", None)
    if not employee:
        if request.user.is_staff:
            return redirect("admin:index")
        raise PermissionDenied("برای این حساب پروفایل کارمند تعریف نشده است.")
    return manager_dashboard(request) if employee.can_review else employee_dashboard(request)

@login_required
def employee_dashboard(request):
    emp = request.user.employee
    start, end = month_range()
    metrics = employee_metrics(emp, start, end)
    recent = emp.activities.select_related("activity_type")[:8]
    recent_shift_logs = emp.shift_logs.select_related("shift", "main_department").prefetch_related("support_departments")[:5]
    return render(
        request,
        "core/employee_dashboard.html",
        {
            "employee": emp,
            "metrics": metrics,
            "recent": recent,
            "recent_shift_logs": recent_shift_logs,
            "start": start,
        },
    )

@login_required
@reviewer_required
def manager_dashboard(request):
    start, end = month_range()
    employees = supervised_employees(request.user.employee).select_related("commission_level")
    rows = [{"employee": e, **employee_metrics(e, start, end)} for e in employees]
    pending = Activity.objects.filter(status=Activity.Status.PENDING, employee__in=employees).select_related("employee", "activity_type")
    today_shift_logs = DailyShiftLog.objects.filter(date=timezone.localdate()).select_related("employee", "shift", "main_department")
    today_performances = LineShiftPerformance.objects.filter(date=timezone.localdate()).select_related("shift", "department")
    return render(
        request,
        "core/manager_dashboard.html",
        {
            "rows": rows,
            "pending": pending[:6],
            "pending_count": pending.count(),
            "today_shift_logs": today_shift_logs[:6],
            "today_shift_logs_count": today_shift_logs.count(),
            "today_performances": today_performances[:6],
            "today_performances_count": today_performances.count(),
            "total_score": sum(r["score"] for r in rows),
            "total_commission": sum(r["commission"] for r in rows),
            "today_count": Activity.objects.filter(activity_date=timezone.localdate()).count(),
        },
    )

# ==========================================
# Shift Logs (کارکرد روزانه شیفت و لاین)
# ==========================================

def shift_log_snapshot(obj):
    supp_names = list(obj.support_departments.values_list("name", flat=True))
    return {
        "employee": obj.employee_id,
        "date": str(obj.date),
        "shift": obj.shift.code,
        "main_department": obj.main_department.name,
        "main_hours": str(obj.main_hours),
        "has_support_line": obj.has_support_line,
        "support_departments": supp_names,
        "support_hours": str(obj.support_hours),
        "total_hours": str(obj.total_hours),
        "support_intervals": [
            {
                "id": item.pk,
                "department": item.department.name,
                "start_time": item.start_time.strftime("%H:%M"),
                "end_time": item.end_time.strftime("%H:%M"),
                "duration_minutes": item.duration_minutes,
            }
            for item in obj.support_intervals.select_related("department").all()
        ],
    }


def save_support_intervals(*, request, log, formset, previous=None):
    previous = previous or {}
    old_by_id = {item["id"]: item for item in previous.get("support_intervals", [])}
    instances = formset.save()
    log.recalculate_allocations()
    current = shift_log_snapshot(log)
    new_by_id = {item["id"]: item for item in current["support_intervals"]}
    for interval_id, old in old_by_id.items():
        if interval_id not in new_by_id:
            audit(actor=request.user, action="support_interval.deleted", instance=log, old_values=old)
    for interval_id, new in new_by_id.items():
        old = old_by_id.get(interval_id)
        action = "support_interval.created" if old is None else "support_interval.updated"
        if old != new:
            audit(actor=request.user, action=action, instance=log, old_values=old or {}, new_values=new)
    return instances


def support_formset_data(request):
    if request.method != "POST":
        return None
    data = request.POST.copy()
    if "support-TOTAL_FORMS" not in data:
        data.update({
            "support-TOTAL_FORMS": "0", "support-INITIAL_FORMS": "0",
            "support-MIN_NUM_FORMS": "0", "support-MAX_NUM_FORMS": "1000",
        })
    return data

@login_required
def shift_log_create(request):
    employee = getattr(request.user, "employee", None)
    if not employee:
        raise PermissionDenied
    form = DailyShiftLogForm(request.POST or None, employee=employee)
    formset = SupportLineIntervalFormSet(support_formset_data(request), prefix="support", instance=DailyShiftLog())
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                log = form.save(commit=False)
                log.employee = employee
                log.main_hours = log.shift.standard_hours
                log.support_hours = Decimal("0")
                log.total_hours = log.shift.standard_hours
                log.has_support_line = False
                log.save()
                formset.instance = log
                if not formset.is_valid():
                    raise ValidationError("بازه‌های کمکی را بررسی کن.")
                save_support_intervals(request=request, log=log, formset=formset)
                audit(
                    actor=request.user,
                    action="shift_log.created",
                    instance=log,
                    new_values=shift_log_snapshot(log),
                )
        except IntegrityError:
            form.add_error(None, "برای این تاریخ و شیفت قبلاً کارکرد ثبت کرده‌اید. می‌توانید از بخش کارکردهای من ویرایشش کنید.")
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "کارکرد شیفتت با موفقیت ثبت شد! خسته نباشی 👏")
            return redirect("shift_log_detail", pk=log.pk)

    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)
    persian_weekdays = {0: "دوشنبه", 1: "سه‌شنبه", 2: "چهارشنبه", 3: "پنج‌شنبه", 4: "جمعه", 5: "شنبه", 6: "یکشنبه"}
    
    def format_date_pill(d):
        j = jdatetime.date.fromgregorian(date=d)
        weekday = persian_weekdays[d.weekday()]
        return {
            "jalali": j.strftime("%Y/%m/%d"),
            "display": f"{weekday} {j.day} {j.strftime('%B')}",
        }

    date_pills = {
        "today": format_date_pill(today),
        "yesterday": format_date_pill(yesterday),
        "two_days_ago": format_date_pill(two_days_ago),
    }

    return render(
        request,
        "shift_logs/form.html",
        {
            "form": form,
            "formset": formset,
            "title": "ثبت کارکرد شیفت امروزت",
            "employee": employee,
            "submit": "✅ ثبت نهایی کارکرد",
            "date_pills": date_pills,
            "standard_hours": employee.standard_daily_hours or Decimal("6.0"),
        },
    )

@login_required
def shift_log_list(request):
    employee = getattr(request.user, "employee", None)
    if not employee:
        raise PermissionDenied
    qs = DailyShiftLog.objects.select_related("employee", "shift", "main_department").prefetch_related("support_departments", "support_intervals__department")
    if not employee.can_review:
        qs = qs.filter(employee=employee)

    date_val = request.GET.get("date", "")
    shift_val = request.GET.get("shift", "")
    dept_val = request.GET.get("department", "")
    if date_val:
        try:
            qs = qs.filter(date=JalaliDateField().clean(date_val))
        except ValidationError:
            pass
    if shift_val:
        qs = qs.filter(shift_id=shift_val)
    if dept_val:
        qs = qs.filter(Q(main_department_id=dept_val) | Q(support_departments__id=dept_val)).distinct()

    return render(
        request,
        "shift_logs/list.html",
        {
            "logs": qs[:200],
            "shifts": Shift.objects.filter(is_active=True),
            "departments": Department.objects.filter(is_active=True),
            "employee": employee,
        },
    )

@login_required
def shift_log_detail(request, pk):
    employee = getattr(request.user, "employee", None)
    if not employee:
        raise PermissionDenied
    qs = DailyShiftLog.objects.select_related("employee", "shift", "main_department").prefetch_related("support_departments", "support_intervals__department")
    if not employee.can_review:
        qs = qs.filter(employee=employee)
    log = get_object_or_404(qs, pk=pk)
    return render(request, "shift_logs/detail.html", {"log": log, "employee": employee})

@login_required
def shift_log_edit(request, pk):
    employee = getattr(request.user, "employee", None)
    if not employee:
        raise PermissionDenied
    qs = DailyShiftLog.objects.select_related("employee", "shift", "main_department").prefetch_related("support_intervals__department")
    if not employee.can_review:
        qs = qs.filter(employee=employee)
    log = get_object_or_404(qs, pk=pk)
    old = shift_log_snapshot(log)
    form = DailyShiftLogForm(request.POST or None, instance=log, employee=employee)
    formset = SupportLineIntervalFormSet(support_formset_data(request), prefix="support", instance=log)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        try:
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.main_hours = obj.shift.standard_hours
                obj.support_hours = Decimal("0")
                obj.total_hours = obj.shift.standard_hours
                obj.save()
                save_support_intervals(request=request, log=obj, formset=formset, previous=old)
                new = shift_log_snapshot(obj)
                audit(
                    actor=request.user,
                    action="shift_log.updated",
                    instance=obj,
                    old_values=old,
                    new_values=new,
                )
        except IntegrityError:
            form.add_error(None, "برای این تاریخ و شیفت قبلاً کارکرد ثبت شده است.")
        else:
            messages.success(request, "کارکرد شیفت با موفقیت به‌روزرسانی شد.")
            return redirect("shift_log_detail", pk=obj.pk)

    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)
    persian_weekdays = {0: "دوشنبه", 1: "سه‌شنبه", 2: "چهارشنبه", 3: "پنج‌شنبه", 4: "جمعه", 5: "شنبه", 6: "یکشنبه"}
    
    def format_date_pill(d):
        j = jdatetime.date.fromgregorian(date=d)
        weekday = persian_weekdays[d.weekday()]
        return {
            "jalali": j.strftime("%Y/%m/%d"),
            "display": f"{weekday} {j.day} {j.strftime('%B')}",
        }

    date_pills = {
        "today": format_date_pill(today),
        "yesterday": format_date_pill(yesterday),
        "two_days_ago": format_date_pill(two_days_ago),
    }

    return render(
        request,
        "shift_logs/form.html",
        {
            "form": form,
            "formset": formset,
            "title": "ویرایش کارکرد شیفت",
            "log": log,
            "employee": employee,
            "submit": "💾 ذخیره تغییرات کارکرد",
            "date_pills": date_pills,
            "standard_hours": employee.standard_daily_hours or Decimal("6.0"),
        },
    )

@login_required
@manager_required
def management_shift_logs(request):
    qs = DailyShiftLog.objects.select_related("employee", "shift", "main_department").prefetch_related("support_departments", "support_intervals__department")
    q = request.GET.get("q", "").strip()
    date_val = request.GET.get("date", "")
    shift_val = request.GET.get("shift", "")
    dept_val = request.GET.get("department", "")
    emp_val = request.GET.get("employee", "")

    if q:
        qs = qs.filter(
            Q(employee__first_name__icontains=q)
            | Q(employee__last_name__icontains=q)
            | Q(employee__employee_code__icontains=q)
            | Q(employee_note__icontains=q)
        )
    if date_val:
        try:
            qs = qs.filter(date=JalaliDateField().clean(date_val))
        except ValidationError:
            pass
    if shift_val:
        qs = qs.filter(shift_id=shift_val)
    if dept_val:
        qs = qs.filter(Q(main_department_id=dept_val) | Q(support_departments__id=dept_val)).distinct()
    if emp_val:
        qs = qs.filter(employee_id=emp_val)

    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "management/shift_log_list.html",
        {
            "page": page,
            "shifts": Shift.objects.filter(is_active=True),
            "departments": Department.objects.filter(is_active=True),
            "employees": Employee.objects.filter(is_active=True),
            "filters": request.GET,
        },
    )

# ==========================================
# Line Shift Performance (عملکرد فروش لاین‌ها)
# ==========================================

def line_performance_snapshot(obj):
    return {
        "date": str(obj.date),
        "shift": obj.shift.code,
        "department": obj.department.name,
        "sold_units": obj.sold_units,
        "sales_amount": obj.sales_amount,
    }

@login_required
@manager_required
def management_line_performances(request):
    qs = LineShiftPerformance.objects.select_related("shift", "department", "recorded_by")
    date_val = request.GET.get("date", "")
    shift_val = request.GET.get("shift", "")
    dept_val = request.GET.get("department", "")

    if date_val:
        try:
            qs = qs.filter(date=JalaliDateField().clean(date_val))
        except ValidationError:
            pass
    if shift_val:
        qs = qs.filter(shift_id=shift_val)
    if dept_val:
        qs = qs.filter(department_id=dept_val)

    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "management/line_performance_list.html",
        {
            "page": page,
            "shifts": Shift.objects.filter(is_active=True),
            "departments": Department.objects.filter(is_active=True),
            "filters": request.GET,
        },
    )

@login_required
@manager_required
def management_line_performance_create(request):
    form = LineShiftPerformanceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.recorded_by = request.user
                obj.save()
                audit(
                    actor=request.user,
                    action="line_performance.created",
                    instance=obj,
                    new_values=line_performance_snapshot(obj),
                )
        except IntegrityError:
            form.add_error(None, "برای این تاریخ، شیفت و لاین قبلاً فروش ثبت شده است. لطفاً همان رکورد را ویرایش کنید.")
        else:
            messages.success(request, "عملکرد فروش لاین با موفقیت ثبت شد.")
            return redirect("management_line_performances")
    return render(
        request,
        "management/line_performance_form.html",
        {"form": form, "title": "ثبت فروش روزانه لاین", "submit": "ثبت فروش"},
    )

@login_required
@manager_required
def management_line_performance_edit(request, pk):
    obj = get_object_or_404(LineShiftPerformance, pk=pk)
    old = line_performance_snapshot(obj)
    form = LineShiftPerformanceForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                item = form.save()
                new = line_performance_snapshot(item)
                audit(
                    actor=request.user,
                    action="line_performance.updated",
                    instance=item,
                    old_values=old,
                    new_values=new,
                )
        except IntegrityError:
            form.add_error(None, "رکورد دیگری با همین تاریخ، شیفت و لاین وجود دارد.")
        else:
            messages.success(request, "عملکرد فروش لاین به‌روزرسانی شد.")
            return redirect("management_line_performances")
    return render(
        request,
        "management/line_performance_form.html",
        {"form": form, "title": "ویرایش فروش لاین", "item": obj, "submit": "ذخیره تغییرات"},
    )

@login_required
@manager_required
def management_line_performance_batch(request):
    date_str = request.GET.get("date") or request.POST.get("date")
    shift_id = request.GET.get("shift") or request.POST.get("shift")

    selected_date = timezone.localdate()
    if date_str:
        try:
            selected_date = JalaliDateField().clean(date_str)
        except ValidationError:
            pass

    shifts = Shift.objects.filter(is_active=True)
    selected_shift = None
    if shift_id:
        selected_shift = Shift.objects.filter(pk=shift_id, is_active=True).first()
    if not selected_shift:
        selected_shift = shifts.first()

    departments = Department.objects.filter(is_active=True)
    existing_records = {
        rec.department_id: rec
        for rec in LineShiftPerformance.objects.filter(date=selected_date, shift=selected_shift)
    }

    if request.method == "POST" and "save_batch" in request.POST:
        with transaction.atomic():
            for dept in departments:
                units_val = request.POST.get(f"sold_units_{dept.pk}", "").strip()
                if units_val != "":
                    try:
                        sold_units = max(0, int(units_val))
                    except ValueError:
                        sold_units = 0
                    rec, created = LineShiftPerformance.objects.update_or_create(
                        date=selected_date,
                        shift=selected_shift,
                        department=dept,
                        defaults={
                            "sold_units": sold_units,
                            "recorded_by": request.user,
                        },
                    )
                    audit(
                        actor=request.user,
                        action="line_performance.created" if created else "line_performance.updated",
                        instance=rec,
                        new_values=line_performance_snapshot(rec),
                    )
        messages.success(request, "عملکرد فروش لاین‌ها با موفقیت ذخیره شد.")
        jalali_str = jdatetime.date.fromgregorian(date=selected_date).strftime("%Y/%m/%d")
        shift_param = selected_shift.pk if selected_shift else ""
        return redirect(f"{reverse('management_line_performances')}?date={jalali_str}&shift={shift_param}")

    dept_rows = []
    for dept in departments:
        rec = existing_records.get(dept.pk)
        dept_rows.append({
            "department": dept,
            "sold_units": rec.sold_units if rec else 0,
            "sales_amount": rec.sales_amount if rec else 0,
            "record": rec,
        })

    return render(
        request,
        "management/line_performance_batch.html",
        {
            "selected_date": selected_date,
            "selected_date_jalali": jdatetime.date.fromgregorian(date=selected_date).strftime("%Y/%m/%d"),
            "selected_shift": selected_shift,
            "shifts": shifts,
            "dept_rows": dept_rows,
        },
    )

# ==========================================
# Line Commission Rates Matrix (ضرایب لاین و گرید)
# ==========================================

@login_required
@manager_required
def management_line_rates(request):
    departments = Department.objects.filter(is_active=True).order_by("name")
    levels = CommissionLevel.objects.all().order_by("code")

    existing = {
        (r.department_id, r.commission_level_id): r
        for r in LineCommissionRate.objects.all()
    }

    if request.method == "POST":
        with transaction.atomic():
            for dept in departments:
                for lvl in levels:
                    field_name = f"rate_{dept.pk}_{lvl.pk}"
                    val = request.POST.get(field_name, "").strip()
                    if val != "":
                        try:
                            rate_val = max(0, int(val))
                        except ValueError:
                            rate_val = 1000
                        LineCommissionRate.objects.update_or_create(
                            department=dept,
                            commission_level=lvl,
                            defaults={"rate_per_unit": rate_val, "is_active": True},
                        )
            audit(
                actor=request.user,
                action="line_rates.updated",
                instance=departments.first() if departments.exists() else SystemSettings.load(),
                description="به‌روزرسانی ماتریس ضرایب لاین و گرید",
            )
        messages.success(request, "ماتریس ضرایب لاین‌ها و گریدها با موفقیت ذخیره شد.")
        return redirect("management_line_rates")

    matrix = []
    for dept in departments:
        row_rates = []
        for lvl in levels:
            rec = existing.get((dept.pk, lvl.pk))
            row_rates.append({
                "level": lvl,
                "rate": rec.rate_per_unit if rec else lvl.performance_rate,
            })
        matrix.append({
            "department": dept,
            "rates": row_rates,
        })

    return render(
        request,
        "management/line_rates_matrix.html",
        {
            "departments": departments,
            "levels": levels,
            "matrix": matrix,
        },
    )

# ==========================================
# Commission Reports (گزارش‌های پورسانت و تسویه)
# ==========================================

@login_required
def my_commission_report(request):
    employee = getattr(request.user, "employee", None)
    if not employee:
        raise PermissionDenied
    start, end = month_range()
    date_val = request.GET.get("date", "")
    if date_val:
        try:
            target_date = JalaliDateField().clean(date_val)
            start, end = month_range(target_date)
        except ValidationError:
            pass

    metrics = employee_metrics(employee, start, end)
    return render(
        request,
        "shift_logs/my_commission.html",
        {
            "employee": employee,
            "metrics": metrics,
            "start": start,
            "end": end,
            "filters": request.GET,
        },
    )

@login_required
@manager_required
def management_commission_report(request):
    start, end = month_range()
    date_val = request.GET.get("date", "")
    if date_val:
        try:
            target_date = JalaliDateField().clean(date_val)
            start, end = month_range(target_date)
        except ValidationError:
            pass

    employees = supervised_employees(request.user.employee).select_related("commission_level", "primary_department")
    
    rows = []
    total_sales_units = Decimal("0.0")
    total_gross_payout = 0
    total_deductions = 0
    total_net_payout = 0

    for emp in employees:
        m = employee_metrics(emp, start, end)
        rows.append({"employee": emp, "metrics": m})
        total_sales_units += Decimal(str(m["total_sales_units_share"]))
        total_gross_payout += m["gross"]
        total_deductions += m["deduction"]
        total_net_payout += m["commission"]

    return render(
        request,
        "management/commission_report.html",
        {
            "rows": rows,
            "start": start,
            "end": end,
            "total_sales_units": round(total_sales_units, 2),
            "total_gross_payout": total_gross_payout,
            "total_deductions": total_deductions,
            "total_net_payout": total_net_payout,
            "filters": request.GET,
        },
    )

# ==========================================
# Activities
# ==========================================

@login_required
def activity_create(request):
    employee = getattr(request.user, "employee", None)
    if not employee:
        raise PermissionDenied
    form = ActivityForm(request.POST or None, request.FILES or None, employee=employee)
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action", "submit")
        try:
            with transaction.atomic():
                Employee.objects.select_for_update().get(pk=employee.pk)
                obj = form.save(commit=False)
                obj.employee = employee
                obj.submitted_by = request.user
                kind = obj.activity_type
                if action == "submit":
                    validate_daily_limit(employee, kind, obj.activity_date)
                obj.definition_score_snapshot = kind.score_value
                obj.multiplier_snapshot = kind.multiplier
                obj.update_duration()
                obj.calculated_score = kind.calculate_score(obj.value)
                obj.final_score = obj.calculated_score
                obj.status = Activity.Status.DRAFT
                obj.save()
                ActivityStatusHistory.objects.create(
                    activity=obj, previous_status="", new_status=Activity.Status.DRAFT, actor=request.user, note="ایجاد فعالیت"
                )
                audit(
                    actor=request.user,
                    action="activity.created",
                    instance=obj,
                    new_values={
                        "status": obj.status,
                        "start_time": str(obj.start_time or ""),
                        "end_time": str(obj.end_time or ""),
                        "duration_minutes": obj.duration_minutes,
                        "value": str(obj.value) if kind.requires_quantity else None,
                        "score": str(obj.calculated_score),
                    },
                )
                if action == "submit":
                    transition_activity(
                        obj,
                        Activity.Status.PENDING if kind.requires_manager_approval else Activity.Status.APPROVED,
                        request.user,
                        audit_action="activity.submitted",
                    )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "فعالیت ذخیره شد.")
            return redirect("activity_detail", pk=obj.pk)
    return render(
        request,
        "activities/form.html",
        {"form": form, "title": "ثبت فعالیت روزانه", "activity_type_data": activity_type_form_data(form)},
    )

@login_required
def activity_list(request):
    qs = Activity.objects.select_related("employee", "activity_type")
    if not request.user.employee.can_review:
        qs = qs.filter(employee=request.user.employee)
    status = request.GET.get("status", "")
    kind = request.GET.get("type", "")
    date_value = request.GET.get("date", "")
    search = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(status=status)
    if kind:
        qs = qs.filter(activity_type_id=kind)
    if date_value:
        try:
            qs = qs.filter(activity_date=JalaliDateField().clean(date_value))
        except Exception:
            pass
    if search:
        qs = qs.filter(employee_note__icontains=search)
    return render(
        request,
        "activities/list.html",
        {
            "activities": qs[:200],
            "activity_types": ActivityType.objects.filter(active=True),
            "statuses": Activity.Status.choices,
        },
    )

@login_required
@reviewer_required
def review_queue(request):
    return redirect("management_activity_reviews")

@login_required
@reviewer_required
def activity_review(request, pk):
    return redirect("management_activity_review_detail", pk=pk)

def validate_daily_limit(employee, kind, activity_date, exclude_pk=None):
    if not kind.max_daily_submissions:
        return
    qs = Activity.objects.filter(
        employee=employee, activity_type=kind, activity_date=activity_date
    ).exclude(status__in=[Activity.Status.DRAFT, Activity.Status.REJECTED])
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.count() >= kind.max_daily_submissions:
        raise ValidationError(f"حداکثر ثبت روزانه این فعالیت {kind.max_daily_submissions} بار است.")

@login_required
def activity_detail(request, pk):
    qs = Activity.objects.select_related("activity_type__category", "employee", "reviewed_by").prefetch_related(
        "status_history__actor"
    )
    if not request.user.employee.can_review:
        qs = qs.filter(employee=request.user.employee)
    return render(request, "activities/detail.html", {"activity": get_object_or_404(qs, pk=pk)})

@login_required
def activity_edit(request, pk):
    employee = getattr(request.user, "employee", None)
    activity = get_object_or_404(Activity, pk=pk, employee=employee)
    if activity.status not in {Activity.Status.DRAFT, Activity.Status.NEEDS_REVISION}:
        raise PermissionDenied("این فعالیت قابل ویرایش نیست.")
    form = ActivityForm(request.POST or None, request.FILES or None, instance=activity, employee=employee)
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action", "submit")
        previous = activity.status
        try:
            with transaction.atomic():
                Employee.objects.select_for_update().get(pk=employee.pk)
                obj = form.save(commit=False)
                kind = obj.activity_type
                if action == "submit":
                    validate_daily_limit(employee, kind, obj.activity_date, obj.pk)
                obj.definition_score_snapshot = kind.score_value
                obj.multiplier_snapshot = kind.multiplier
                obj.update_duration()
                obj.calculated_score = kind.calculate_score(obj.value)
                obj.final_score = obj.calculated_score
                obj.save()
                audit(
                    actor=request.user,
                    action="activity.updated",
                    instance=obj,
                    new_values={
                        "start_time": str(obj.start_time or ""),
                        "end_time": str(obj.end_time or ""),
                        "duration_minutes": obj.duration_minutes,
                        "value": str(obj.value) if kind.requires_quantity else None,
                        "score": str(obj.calculated_score),
                    },
                )
                if action == "submit":
                    transition_activity(
                        obj,
                        Activity.Status.PENDING if kind.requires_manager_approval else Activity.Status.APPROVED,
                        request.user,
                        audit_action="activity.resubmitted" if previous == Activity.Status.NEEDS_REVISION else "activity.submitted",
                    )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "فعالیت به‌روزرسانی شد.")
            return redirect("activity_detail", pk=obj.pk)
    return render(
        request,
        "activities/form.html",
        {
            "form": form,
            "activity": activity,
            "title": "اصلاح فعالیت",
            "activity_type_data": activity_type_form_data(form),
        },
    )

def activity_type_form_data(form):
    return [
        {
            "id": item.pk,
            "unit": item.unit,
            "requires_evidence": item.requires_evidence,
            "requires_time_tracking": item.requires_time_tracking,
            "requires_quantity": item.requires_quantity,
        }
        for item in form.fields["activity_type"].queryset
    ]

def activity_type_snapshot(obj):
    return {
        "title": obj.title,
        "code": obj.code,
        "category": obj.category_id,
        "scoring_method": obj.scoring_method,
        "score_value": str(obj.score_value),
        "multiplier": str(obj.multiplier),
        "active": obj.active,
    }

@login_required
@manager_required
def management_activity_types(request):
    qs = ActivityType.objects.select_related("category").prefetch_related("departments")
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    department = request.GET.get("department", "")
    active = request.GET.get("active", "")
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(code__icontains=q))
    if category:
        qs = qs.filter(category_id=category)
    if department:
        qs = qs.filter(Q(all_departments=True) | Q(departments__id=department)).distinct()
    if active in {"1", "0"}:
        qs = qs.filter(active=active == "1")
    return render(
        request,
        "management/activity_type_list.html",
        {
            "activity_types": qs,
            "categories": ActivityCategory.objects.filter(active=True),
            "departments": Department.objects.filter(is_active=True),
        },
    )

@login_required
@manager_required
def management_activity_type_create(request):
    form = ActivityTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        audit(actor=request.user, action="activity_type.created", instance=obj, new_values=activity_type_snapshot(obj))
        messages.success(request, "تعریف فعالیت ساخته شد.")
        return redirect("management_activity_types")
    return render(request, "management/activity_type_form.html", {"form": form, "title": "تعریف فعالیت جدید"})

@login_required
@manager_required
def management_activity_type_edit(request, pk):
    obj = get_object_or_404(ActivityType, pk=pk)
    old = activity_type_snapshot(obj)
    form = ActivityTypeForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        new = activity_type_snapshot(obj)
        audit(actor=request.user, action="activity_type.updated", instance=obj, old_values=old, new_values=new)
        if old["active"] != new["active"]:
            audit(
                actor=request.user,
                action="activity_type.activated" if new["active"] else "activity_type.deactivated",
                instance=obj,
                old_values={"active": old["active"]},
                new_values={"active": new["active"]},
            )
        messages.success(request, "تعریف فعالیت به‌روزرسانی شد.")
        return redirect("management_activity_types")
    return render(request, "management/activity_type_form.html", {"form": form, "title": "ویرایش تعریف فعالیت", "activity_type": obj})

@login_required
@manager_required
def management_activity_reviews(request):
    qs = Activity.objects.filter(status=Activity.Status.PENDING).select_related(
        "employee", "activity_type__category", "employee__primary_department"
    )
    q = request.GET.get("q", "").strip()
    employee = request.GET.get("employee", "")
    department = request.GET.get("department", "")
    kind = request.GET.get("type", "")
    date_value = request.GET.get("date", "")
    sort = request.GET.get("sort", "oldest")
    if q:
        qs = qs.filter(
            Q(employee__first_name__icontains=q)
            | Q(employee__last_name__icontains=q)
            | Q(employee_note__icontains=q)
        )
    if employee:
        qs = qs.filter(employee_id=employee)
    if department:
        qs = qs.filter(employee__primary_department_id=department)
    if kind:
        qs = qs.filter(activity_type_id=kind)
    if date_value:
        try:
            qs = qs.filter(activity_date=JalaliDateField().clean(date_value))
        except ValidationError:
            pass
    qs = qs.order_by("-submitted_at" if sort == "newest" else "submitted_at")
    return render(
        request,
        "management/activity_review_list.html",
        {
            "activities": qs,
            "employees": Employee.objects.filter(is_active=True),
            "departments": Department.objects.filter(is_active=True),
            "activity_types": ActivityType.objects.filter(active=True),
        },
    )

@login_required
@manager_required
def management_activity_review_detail(request, pk):
    activity = get_object_or_404(
        Activity.objects.select_related("employee", "activity_type__category").prefetch_related("status_history__actor"),
        pk=pk,
    )
    form = ReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if activity.status != Activity.Status.PENDING:
            raise PermissionDenied("این فعالیت دیگر در انتظار بررسی نیست.")
        note = form.cleaned_data["manager_note"]
        new_status = form.cleaned_data["action"]
        activity.manager_note = note
        activity.reviewed_by = request.user
        activity.reviewed_at = timezone.now()
        activity.save(update_fields=["manager_note", "reviewed_by", "reviewed_at", "updated_at"])
        action_map = {
            Activity.Status.APPROVED: "activity.approved",
            Activity.Status.REJECTED: "activity.rejected",
            Activity.Status.NEEDS_REVISION: "activity.needs_revision",
        }
        transition_activity(activity, new_status, request.user, note, audit_action=action_map[new_status])
        messages.success(request, "نتیجه بررسی ثبت شد.")
        return redirect("management_activity_reviews")
    return render(request, "management/activity_review_detail.html", {"activity": activity, "form": form})

# ==========================================
# Shifts Management
# ==========================================

def shift_snapshot(obj):
    return {
        "title": obj.title,
        "code": obj.code,
        "start_time": str(obj.start_time),
        "end_time": str(obj.end_time),
        "standard_hours": str(obj.standard_hours),
        "is_active": obj.is_active,
    }

@login_required
@manager_required
def management_shifts(request):
    qs = Shift.objects.all()
    q = request.GET.get("q", "").strip()
    active = request.GET.get("active", "")
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(code__icontains=q))
    if active in {"1", "0"}:
        qs = qs.filter(is_active=active == "1")
    return render(request, "management/shift_list.html", {"shifts": qs})

@login_required
@manager_required
def management_shift_create(request):
    form = ShiftForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        audit(actor=request.user, action="shift.created", instance=obj, new_values=shift_snapshot(obj))
        messages.success(request, "شیفت با موفقیت ایجاد شد.")
        return redirect("management_shifts")
    return render(request, "management/shift_form.html", {"form": form, "title": "تعریف شیفت جدید", "submit": "ایجاد شیفت"})

@login_required
@manager_required
def management_shift_edit(request, pk):
    obj = get_object_or_404(Shift, pk=pk)
    old = shift_snapshot(obj)
    form = ShiftForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        new = shift_snapshot(obj)
        audit(actor=request.user, action="shift.updated", instance=obj, old_values=old, new_values=new)
        if old["is_active"] != new["is_active"]:
            audit(
                actor=request.user,
                action="shift.activated" if new["is_active"] else "shift.deactivated",
                instance=obj,
                old_values={"is_active": old["is_active"]},
                new_values={"is_active": new["is_active"]},
            )
        messages.success(request, "شیفت به‌روزرسانی شد.")
        return redirect("management_shifts")
    return render(request, "management/shift_form.html", {"form": form, "title": "ویرایش شیفت", "shift": obj, "submit": "ذخیره تغییرات"})

# ==========================================
# Violations
# ==========================================

@login_required
@reviewer_required
def violation_create(request):
    form = ViolationForm(request.POST or None)
    form.fields["employee"].queryset = supervised_employees(request.user.employee)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.recorded_by = request.user
        obj.points_snapshot = obj.rule.points_for(obj.occurrence)
        obj.save()
        messages.success(request, "تخلف ثبت شد.")
        return redirect("violations")
    return render(request, "core/form.html", {"form": form, "title": "ثبت تخلف", "submit": "ثبت تخلف"})

@login_required
def violation_list(request):
    qs = Violation.objects.select_related("employee", "rule", "recorded_by")
    if not request.user.employee.can_review:
        qs = qs.filter(employee=request.user.employee)
    return render(request, "core/violation_list.html", {"violations": qs[:100]})

# ==========================================
# Employees
# ==========================================

@login_required
@reviewer_required
def employee_list(request):
    return redirect("management_employees")

def employee_snapshot(employee):
    return {
        "username": employee.user.username if hasattr(employee, "user") and employee.user else "",
        "first_name": employee.first_name,
        "last_name": employee.last_name,
        "mobile": employee.mobile,
        "employee_code": employee.employee_code,
        "primary_department": employee.primary_department_id,
        "default_shift": employee.default_shift_id,
        "standard_daily_hours": str(employee.standard_daily_hours),
        "commission_level": employee.commission_level_id,
        "start_date": str(employee.start_date or ""),
        "is_active": employee.is_active,
    }

@login_required
@manager_required
def management_employees(request):
    qs = Employee.objects.select_related("commission_level", "primary_department", "default_shift").prefetch_related("departments")
    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(mobile__icontains=search)
            | Q(employee_code__icontains=search)
        )
    status = request.GET.get("status", "")
    if status in {"active", "inactive"}:
        qs = qs.filter(is_active=status == "active")
    level = request.GET.get("level", "")
    if level:
        qs = qs.filter(commission_level_id=level)
    department = request.GET.get("department", "")
    if department:
        qs = qs.filter(Q(primary_department_id=department) | Q(departments__id=department)).distinct()
    sort_map = {
        "name": "last_name",
        "-name": "-last_name",
        "start_date": "start_date",
        "-start_date": "-start_date",
        "code": "employee_code",
        "-code": "-employee_code",
    }
    sort = request.GET.get("sort", "name")
    qs = qs.order_by(sort_map.get(sort, "last_name"), "first_name")
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "management/employee_list.html",
        {
            "page": page,
            "levels": CommissionLevel.objects.all(),
            "departments": Department.objects.filter(is_active=True),
            "filters": request.GET,
            "sort": sort,
        },
    )

@login_required
@manager_required
def management_employee_create(request):
    form = EmployeeCreateForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            username = form.cleaned_data["username"]
            user = request.user.__class__.objects.create_user(
                username=username,
                password=form.cleaned_data["initial_password"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                is_active=form.cleaned_data["is_active"],
            )
            employee = form.save(commit=False)
            employee.user = user
            employee.save()
            form.save_m2m()
            audit(actor=request.user, action="employee.created", instance=employee, new_values=employee_snapshot(employee))
        messages.success(request, f"کارمند {employee.full_name} با نام کاربری {user.username} ساخته شد.")
        return redirect("management_employee_detail", pk=employee.pk)
    return render(request, "management/employee_form.html", {"form": form, "title": "ساخت کارمند جدید", "submit": "ساخت کارمند"})

@login_required
@manager_required
def management_employee_detail(request, pk):
    employee = get_object_or_404(
        Employee.objects.select_related("commission_level", "primary_department", "default_shift", "user").prefetch_related(
            "departments", "level_history__previous_level", "level_history__new_level"
        ),
        pk=pk,
    )
    tab = request.GET.get("tab", "summary")
    allowed = {"summary", "performance", "activities", "shift_logs", "violations", "commission", "levels", "info"}
    if tab not in allowed:
        tab = "summary"
    return render(
        request,
        "management/employee_detail.html",
        {
            "employee": employee,
            "tab": tab,
            "activities": employee.activities.select_related("activity_type")[:20],
            "shift_logs": employee.shift_logs.select_related("shift", "main_department").prefetch_related("support_departments")[:20],
            "violations": employee.violations.select_related("rule")[:20],
        },
    )

@login_required
@manager_required
def management_employee_edit(request, pk):
    employee = get_object_or_404(Employee.objects.select_related("commission_level", "default_shift", "user"), pk=pk)
    old = employee_snapshot(employee)
    old_level = employee.commission_level
    form = EmployeeEditForm(request.POST or None, request.FILES or None, instance=employee)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            requested_level = form.cleaned_data["commission_level"]
            new_username = form.cleaned_data["username"]
            obj = form.save(commit=False)
            obj.commission_level = old_level
            obj.save()
            form.save_m2m()
            
            user_updated_fields = ["first_name", "last_name"]
            obj.user.first_name = obj.first_name
            obj.user.last_name = obj.last_name
            if obj.user.username != new_username:
                obj.user.username = new_username
                user_updated_fields.append("username")
            obj.user.save(update_fields=user_updated_fields)

            change_employee_level(obj, requested_level, request.user, form.cleaned_data.get("level_reason", ""))
            new = employee_snapshot(obj)
            changed = {k: v for k, v in new.items() if old.get(k) != v}
            old_changed = {k: old[k] for k in changed}
            if changed:
                audit(actor=request.user, action="employee.updated", instance=obj, old_values=old_changed, new_values=changed)
            if old["is_active"] != obj.is_active:
                audit(
                    actor=request.user,
                    action="employee.activated" if obj.is_active else "employee.deactivated",
                    instance=obj,
                    old_values={"is_active": old["is_active"]},
                    new_values={"is_active": obj.is_active},
                )
        messages.success(request, "اطلاعات کارمند و نام کاربری به‌روزرسانی شد.")
        return redirect("management_employee_detail", pk=obj.pk)
    return render(
        request,
        "management/employee_form.html",
        {"form": form, "employee": employee, "title": "ویرایش کارمند", "submit": "ذخیره تغییرات"},
    )

@login_required
@manager_required
def management_employee_password(request, pk):
    employee = get_object_or_404(Employee.objects.select_related("user"), pk=pk)
    form = ManagerPasswordResetForm(employee.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit(actor=request.user, action="employee.password_reset", instance=employee, description="رمز عبور توسط مدیر بازنشانی شد.")
        messages.success(request, "رمز عبور با موفقیت تغییر کرد.")
        return redirect("management_employee_detail", pk=employee.pk)
    return render(request, "management/password_form.html", {"form": form, "employee": employee})

# ==========================================
# Profile & Settings
# ==========================================

@login_required
def profile(request):
    employee = getattr(request.user, "employee", None)
    if not employee:
        raise PermissionDenied("پروفایل کارمند تعریف نشده است.")
    return render(request, "profile/detail.html", {"employee": employee})

@login_required
def profile_photo(request):
    employee = getattr(request.user, "employee", None)
    if not employee:
        raise PermissionDenied
    form = ProfilePhotoForm(request.POST or None, request.FILES or None, instance=employee)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "عکس پروفایل به‌روزرسانی شد.")
        return redirect("profile")
    return render(request, "profile/photo_form.html", {"form": form})

@login_required
def profile_password(request):
    if not hasattr(request.user, "employee"):
        raise PermissionDenied
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "رمز عبور تغییر کرد.")
        return redirect("profile")
    return render(request, "profile/password_form.html", {"form": form})

@login_required
@manager_required
def branding_settings(request):
    settings = SystemSettings.load()
    form = BrandingForm(request.POST or None, request.FILES or None, instance=settings)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                old = {
                    "panel_name": settings.panel_name,
                    "organization_name": settings.organization_name,
                    "primary_color": settings.primary_color,
                    "logo": str(settings.logo) if settings.logo else "",
                    "favicon": str(settings.favicon) if settings.favicon else "",
                }
                obj = form.save()
                new = {
                    "panel_name": obj.panel_name,
                    "organization_name": obj.organization_name,
                    "primary_color": obj.primary_color,
                    "logo": str(obj.logo) if obj.logo else "",
                    "favicon": str(obj.favicon) if obj.favicon else "",
                }
                audit(
                    actor=request.user,
                    action="settings.branding_updated",
                    instance=obj,
                    old_values=old,
                    new_values=new,
                )
            messages.success(request, "تنظیمات ظاهری با موفقیت ذخیره شد.")
            return redirect("branding_settings")
        except Exception as exc:
            form.add_error(None, f"خطا در ذخیره فایل یا تنظیمات: {exc}")
    return render(request, "management/branding_form.html", {"form": form, "settings": settings})
