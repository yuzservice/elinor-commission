from datetime import date, timedelta
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
import jdatetime
from .decorators import manager_required, reviewer_required
from .forms import (
    BrandingForm,
    DailyShiftLogForm,
    SupportLineIntervalFormSet,
    DepartmentForm,
    EmployeeCreateForm,
    EmployeeEditForm,
    JalaliDateField,
    LineShiftPerformanceForm,
    ManagerPasswordResetForm,
    ProfilePhotoForm,
    ShiftForm,
    ShiftLogReviewForm,
    ViolationForm,
    ViolationRuleForm,
)
from .models import (
    AuditLog,
    CommissionLevel,
    DailyShiftLog,
    Department,
    Employee,
    LineCommissionRate,
    LineShiftPerformance,
    LineTarget,
    Shift,
    SupportLineInterval,
    SystemSettings,
    Violation,
    ViolationRule,
)
from .services import (
    approve_shift_log,
    audit,
    calculate_single_shift_log,
    change_employee_level,
    employee_metrics,
    reject_shift_log,
)

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
    recent_shift_logs = emp.shift_logs.select_related("shift", "main_department").prefetch_related("support_departments")[:6]
    return render(
        request,
        "core/employee_dashboard.html",
        {
            "employee": emp,
            "metrics": metrics,
            "recent_shift_logs": recent_shift_logs,
            "start": start,
        },
    )

@login_required
@reviewer_required
def manager_dashboard(request):
    start, end = month_range()
    employees = supervised_employees(request.user.employee).select_related("commission_level", "primary_department")
    rows = [{"employee": e, **employee_metrics(e, start, end)} for e in employees]

    pending_shift_logs = DailyShiftLog.objects.filter(status=DailyShiftLog.Status.PENDING).select_related("employee", "shift", "main_department")
    today_shift_logs = DailyShiftLog.objects.filter(date=timezone.localdate()).select_related("employee", "shift", "main_department")
    today_performances = LineShiftPerformance.objects.filter(date=timezone.localdate()).select_related("shift", "department")

    return render(
        request,
        "core/manager_dashboard.html",
        {
            "rows": rows,
            "pending_shift_logs": pending_shift_logs[:6],
            "pending_shift_logs_count": pending_shift_logs.count(),
            "today_shift_logs": today_shift_logs[:6],
            "today_shift_logs_count": today_shift_logs.count(),
            "today_performances": today_performances[:6],
            "today_performances_count": today_performances.count(),
            "total_score": sum(r.get("score", 0) for r in rows),
            "total_commission": sum(r.get("commission", 0) for r in rows),
            "total_wallet_balance": sum(r.get("wallet_balance", 0) for r in rows),
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
        "status": obj.status,
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
    formset.save()
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
    # Managers review shift logs, they don't submit daily shift logs for themselves
    if employee.can_review:
        messages.info(request, "به‌عنوان مدیر می‌توانید کارکردهای پرسنل را در صفحه بررسی و تأیید کارکردها مشاهده و تأیید نمایید.")
        return redirect("management_shift_log_reviews")

    form = DailyShiftLogForm(request.POST or None, employee=employee)
    formset = SupportLineIntervalFormSet(
        support_formset_data(request), prefix="support", instance=DailyShiftLog()
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                log = form.save(commit=False)
                log.employee = employee
                log.status = DailyShiftLog.Status.PENDING
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
            form.add_error(None, "برای این تاریخ و شیفت قبلاً کارکرد ثبت کرده‌ای. می‌تونی از بخش کارکردهای من ویرایشش کنی.")
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "کارکرد شیفتت ثبت شد و برای تأیید و واریز به مدیر ارسال گردید! 👏")
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
    status_val = request.GET.get("status", "")

    if date_val:
        try:
            qs = qs.filter(date=JalaliDateField().clean(date_val))
        except ValidationError:
            pass
    if shift_val:
        qs = qs.filter(shift_id=shift_val)
    if dept_val:
        qs = qs.filter(Q(main_department_id=dept_val) | Q(support_departments__id=dept_val)).distinct()
    if status_val:
        qs = qs.filter(status=status_val)

    return render(
        request,
        "shift_logs/list.html",
        {
            "logs": qs[:200],
            "shifts": Shift.objects.filter(is_active=True),
            "departments": Department.objects.filter(is_active=True),
            "employee": employee,
            "statuses": DailyShiftLog.Status.choices,
        },
    )

@login_required
def shift_log_detail(request, pk):
    employee = getattr(request.user, "employee", None)
    if not employee:
        raise PermissionDenied
    qs = DailyShiftLog.objects.select_related("employee", "shift", "main_department", "reviewed_by").prefetch_related("support_departments", "support_intervals__department")
    if not employee.can_review:
        qs = qs.filter(employee=employee)
    log = get_object_or_404(qs, pk=pk)
    calc = calculate_single_shift_log(log)
    return render(request, "shift_logs/detail.html", {"log": log, "calc": calc, "employee": employee})

@login_required
def shift_log_edit(request, pk):
    employee = getattr(request.user, "employee", None)
    if not employee:
        raise PermissionDenied
    log = get_object_or_404(
        DailyShiftLog.objects.prefetch_related("support_intervals__department"), pk=pk, employee=employee
    )
    if log.status == DailyShiftLog.Status.APPROVED and not employee.can_review:
        messages.error(request, "این کارکرد توسط مدیر تأیید و فریز شده و امکان ویرایش آن وجود ندارد.")
        return redirect("shift_log_detail", pk=log.pk)

    old = shift_log_snapshot(log)
    form = DailyShiftLogForm(request.POST or None, instance=log, employee=employee)
    formset = SupportLineIntervalFormSet(
        support_formset_data(request), prefix="support", instance=log
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        try:
            with transaction.atomic():
                obj = form.save(commit=False)
                # If edited by employee, it goes back to PENDING for manager review
                if not employee.can_review:
                    obj.status = DailyShiftLog.Status.PENDING
                    obj.is_frozen = False
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

# ==========================================
# Manager Shift Log Reviews & Approvals (بررسی و تأیید کارکرد پرسنل)
# ==========================================

@login_required
@manager_required
def management_shift_log_reviews(request):
    """صف مشاهده، بررسی و تأیید کارکردهای ثبت‌شده پرسنل توسط مدیر."""
    status_filter = request.GET.get("status", "PENDING")
    date_val = request.GET.get("date", "")
    shift_val = request.GET.get("shift", "")
    dept_val = request.GET.get("department", "")
    emp_val = request.GET.get("employee", "")
    q = request.GET.get("q", "").strip()

    qs = DailyShiftLog.objects.select_related(
        "employee", "shift", "main_department", "reviewed_by"
    ).prefetch_related("support_departments", "support_intervals__department")

    if status_filter in {"PENDING", "APPROVED", "REJECTED"}:
        qs = qs.filter(status=status_filter)

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

    # Calculate pending count for badge
    pending_count = DailyShiftLog.objects.filter(status=DailyShiftLog.Status.PENDING).count()
    approved_count = DailyShiftLog.objects.filter(status=DailyShiftLog.Status.APPROVED).count()
    rejected_count = DailyShiftLog.objects.filter(status=DailyShiftLog.Status.REJECTED).count()

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))

    # Attach calculated metrics for each shift log in page
    log_rows = []
    for log in page:
        calc = calculate_single_shift_log(log)
        log_rows.append({
            "log": log,
            "calc": calc,
        })

    return render(
        request,
        "management/shift_log_review_list.html",
        {
            "page": page,
            "log_rows": log_rows,
            "status_filter": status_filter,
            "pending_count": pending_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "shifts": Shift.objects.filter(is_active=True),
            "departments": Department.objects.filter(is_active=True),
            "employees": Employee.objects.filter(is_active=True),
            "filters": request.GET,
        },
    )

@login_required
@manager_required
def management_shift_log_review_detail(request, pk):
    """مشاهده ریز جزئیات کارکرد و انجام تأیید یا رد با یادداشت مدیر."""
    log = get_object_or_404(
        DailyShiftLog.objects.select_related("employee", "shift", "main_department", "reviewed_by").prefetch_related("support_departments", "support_intervals__department"),
        pk=pk
    )
    calc = calculate_single_shift_log(log, force_dynamic=(log.status != DailyShiftLog.Status.APPROVED))

    form = ShiftLogReviewForm(request.POST or None, initial={"action": "APPROVED" if log.status != DailyShiftLog.Status.REJECTED else "REJECTED", "manager_note": log.manager_note})
    if request.method == "POST" and form.is_valid():
        action = form.cleaned_data["action"]
        note = form.cleaned_data.get("manager_note", "")
        if action == "APPROVED":
            approve_shift_log(log, request.user, note)
            messages.success(request, f"کارکرد روز {log.date} کارمند {log.employee.full_name} با موفقیت تأیید شد و پورسانت به مبلغ {log.frozen_commission_amount:,} ریال قطعی و واریز گردید.")
        else:
            reject_shift_log(log, request.user, note)
            messages.warning(request, f"کارکرد روز {log.date} کارمند {log.employee.full_name} رد شد.")
        return redirect("management_shift_log_reviews")

    return render(
        request,
        "management/shift_log_review_detail.html",
        {
            "log": log,
            "calc": calc,
            "form": form,
        },
    )

@login_required
@manager_required
@require_POST
def management_shift_log_quick_approve(request, pk):
    """تأیید سریع تک‌کلیکه کارکرد پرسنل از لیست."""
    log = get_object_or_404(DailyShiftLog, pk=pk)
    approve_shift_log(log, request.user, "تأیید سریع توسط مدیر")
    messages.success(request, f"کارکرد {log.employee.full_name} در تاریخ {log.date} تأیید و واریز شد.")
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("management_shift_log_reviews")
    return redirect(next_url)

@login_required
@manager_required
def management_shift_logs(request):
    """هدایت گزارش کلی به صف بررسی کارکردها."""
    return redirect("management_shift_log_reviews")

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

def dependency_message(entity_label, blockers):
    details = "، ".join(f"{count} {label}" for label, count in blockers if count)
    return f"{entity_label} فعلاً قابل حذف نیست. ابتدا موارد زیر را تعیین تکلیف کنید: {details}."

def delete_with_audit(*, request, obj, action, description, old_values=None):
    with transaction.atomic():
        audit(actor=request.user, action=action, instance=obj, description=description,
              old_values=old_values or {})
        obj.delete()

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
@require_POST
def management_line_performance_delete(request, pk):
    obj = get_object_or_404(
        LineShiftPerformance.objects.select_related("shift", "department"),
        pk=pk,
    )
    snapshot = line_performance_snapshot(obj)
    label = f"{obj.department.name} - {obj.date} - {obj.shift.title}"

    delete_with_audit(request=request, obj=obj, action="line_performance.deleted",
                      description=f"حذف فروش روزانه لاین: {label}", old_values=snapshot)

    messages.success(request, f"رکورد فروش «{label}» حذف شد.")
    return redirect("management_line_performances")


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
    if request.method == "GET":
        messages.info(request, "ضرایب و تارگت‌ها اکنون از مرکز کنترل هر لاین مدیریت می‌شوند.")
        return redirect("management_departments")
    departments = Department.objects.filter(is_active=True).order_by("name")
    levels = CommissionLevel.objects.all().order_by("code")

    existing = {
        (r.department_id, r.commission_level_id): r
        for r in LineCommissionRate.objects.all()
    }

    if request.method == "POST":
        try:
            with transaction.atomic():
                for dept in departments:
                    for lvl in levels:
                        field_name = f"rate_{dept.pk}_{lvl.pk}"
                        val = request.POST.get(field_name)
                        if val is not None and val.strip() != "":
                            rate_val = int(val)
                            if rate_val < 0:
                                raise ValueError("ضرایب نمی‌توانند منفی باشند.")
                            LineCommissionRate.objects.update_or_create(
                                department=dept,
                                commission_level=lvl,
                                defaults={"rate_per_unit": rate_val, "is_active": True},
                            )

                    target, _ = LineTarget.objects.get_or_create(department=dept)
                    values = {}
                    for field in (
                        "bronze_units", "bronze_reward", "silver_units",
                        "silver_reward", "gold_units", "gold_reward",
                    ):
                        raw = request.POST.get(f"target_{dept.pk}_{field}")
                        values[field] = getattr(target, field) if raw is None or raw.strip() == "" else int(raw)
                        if values[field] < 0:
                            raise ValueError("اعداد تارگت و پاداش نمی‌توانند منفی باشند.")
                    if not (values["bronze_units"] < values["silver_units"] < values["gold_units"]):
                        raise ValueError(f"ترتیب تارگت‌های لاین «{dept.name}» باید برنزی < نقره‌ای < طلایی باشد.")
                    for field, value in values.items():
                        setattr(target, field, value)
                    target.is_active = True
                    target.save()

                audit(
                    actor=request.user,
                    action="line_rates_and_targets.updated",
                    instance=departments.first() if departments.exists() else SystemSettings.load(),
                    description="به‌روزرسانی یکپارچه ضرایب و تارگت‌های لاین‌ها",
                )
        except (TypeError, ValueError) as exc:
            messages.error(request, str(exc) or "مقادیر واردشده معتبر نیستند.")
        else:
            messages.success(request, "تمام ضرایب و تارگت‌های لاین‌ها با موفقیت ذخیره شد.")
            return redirect("management_line_rates")

    targets = {target.department_id: target for target in LineTarget.objects.filter(department__in=departments)}
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
            "target": targets.get(dept.pk) or LineTarget(department=dept),
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
    total_wallet_payout = 0

    for emp in employees:
        m = employee_metrics(emp, start, end)
        rows.append({"employee": emp, "metrics": m})
        total_sales_units += Decimal(str(m.get("total_sales_units_share", 0)))
        total_gross_payout += m.get("gross", 0)
        total_deductions += m.get("deduction", 0)
        total_net_payout += m.get("commission", 0)
        total_wallet_payout += m.get("wallet_balance", 0)

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
            "total_wallet_payout": total_wallet_payout,
            "filters": request.GET,
        },
    )

# ==========================================
# Violations & Disciplines
# ==========================================

@login_required
def violation_list(request):
    employee = getattr(request.user, "employee", None)
    if not employee:
        raise PermissionDenied
    qs = Violation.objects.select_related("employee", "rule", "recorded_by")
    if not employee.can_review:
        qs = qs.filter(employee=employee)
    return render(request, "core/violation_list.html", {"violations": qs[:100], "employee": employee})

@login_required
@reviewer_required
def violation_create(request):
    form = ViolationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.recorded_by = request.user
            obj.points_snapshot = obj.rule.points_for(obj.occurrence)
            obj.rule_snapshot = {
                "rule_id": obj.rule_id,
                "code": obj.rule.code,
                "title": obj.rule.title,
                "occurrence": obj.occurrence,
                "points": obj.points_snapshot,
                "first_points": obj.rule.first_points,
                "second_points": obj.rule.second_points,
                "third_points": obj.rule.third_points,
                "recurrence_window": obj.rule.recurrence_window,
            }
            obj.save()
            audit(
                actor=request.user,
                action="violation.created",
                instance=obj,
                new_values={"employee": obj.employee.full_name, "rule": obj.rule.title, "points": obj.points_snapshot},
            )
        messages.success(request, "تخلف ثبت شد.")
        return redirect("violations")
    return render(request, "core/violation_form.html", {"form": form})


@login_required
@manager_required
def management_violation_rules(request):
    rules = ViolationRule.objects.prefetch_related("departments").order_by("title")
    return render(request, "management/violation_rule_list.html", {"rules": rules})


@login_required
@manager_required
def management_violation_rule_create(request):
    form = ViolationRuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            rule = form.save()
            audit(actor=request.user, action="violation_rule.created", instance=rule,
                  new_values={"code": rule.code, "title": rule.title, "is_active": rule.is_active})
        messages.success(request, f"قانون تخلف «{rule.title}» ایجاد شد.")
        return redirect("management_violation_rules")
    return render(request, "management/violation_rule_form.html", {"form": form, "title": "تعریف قانون تخلف"})


@login_required
@manager_required
def management_violation_rule_edit(request, pk):
    rule = get_object_or_404(ViolationRule, pk=pk)
    form = ViolationRuleForm(request.POST or None, instance=rule)
    if request.method == "POST" and form.is_valid():
        old_values = {"code": rule.code, "title": rule.title, "is_active": rule.is_active}
        with transaction.atomic():
            rule = form.save()
            audit(actor=request.user, action="violation_rule.updated", instance=rule,
                  old_values=old_values,
                  new_values={"code": rule.code, "title": rule.title, "is_active": rule.is_active})
        messages.success(request, f"قانون تخلف «{rule.title}» به‌روزرسانی شد؛ سوابق قبلی بدون تغییر ماندند.")
        return redirect("management_violation_rules")
    return render(request, "management/violation_rule_form.html", {"form": form, "rule": rule, "title": "ویرایش قانون تخلف"})

@login_required
@manager_required
@require_POST
def management_violation_rule_delete(request, pk):
    rule = get_object_or_404(ViolationRule, pk=pk)
    blockers = [("تخلف ثبت‌شده", rule.violations.count()), ("لاین مرتبط", rule.departments.count())]
    if any(count for _, count in blockers):
        messages.error(request, dependency_message("این قانون تخلف", blockers))
        return redirect("management_violation_rule_edit", pk=pk)
    title = rule.title
    delete_with_audit(request=request, obj=rule, action="violation_rule.deleted",
                      description=f"حذف قانون تخلف: {title}", old_values={"title": title, "code": rule.code})
    messages.success(request, f"قانون تخلف «{title}» حذف شد.")
    return redirect("management_violation_rules")

@login_required
@manager_required
def management_violation_detail(request, pk):
    violation = get_object_or_404(Violation.objects.select_related("employee", "rule", "recorded_by"), pk=pk)
    return render(request, "management/violation_detail.html", {"violation": violation})

@login_required
@manager_required
@require_POST
def management_violation_delete(request, pk):
    violation = get_object_or_404(Violation.objects.select_related("employee", "rule"), pk=pk)
    snapshot = {"employee": violation.employee.full_name, "rule": violation.rule.title,
                "date": str(violation.violation_date), "points": violation.points_snapshot}
    label = f"{violation.rule.title} برای {violation.employee.full_name}"
    delete_with_audit(request=request, obj=violation, action="violation.deleted",
                      description=f"حذف تخلف ثبت‌شده: {label}", old_values=snapshot)
    messages.success(request, f"تخلف «{label}» حذف شد.")
    return redirect("violations")

# ==========================================
# Shifts Management
# ==========================================

@login_required
@manager_required
def management_shifts(request):
    shifts = Shift.objects.all().order_by("sort_order", "start_time")
    return render(request, "management/shift_list.html", {"shifts": shifts})

@login_required
@manager_required
def management_shift_create(request):
    form = ShiftForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            shift = form.save()
            audit(actor=request.user, action="shift.created", instance=shift, new_values={"title": shift.title, "code": shift.code})
        messages.success(request, f"شیفت «{shift.title}» با موفقیت تعریف شد.")
        return redirect("management_shifts")
    return render(request, "management/shift_form.html", {"form": form, "title": "تعریف شیفت کاری جدید", "submit": "تعریف شیفت"})

@login_required
@manager_required
def management_shift_edit(request, pk):
    shift = get_object_or_404(Shift, pk=pk)
    form = ShiftForm(request.POST or None, instance=shift)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            shift = form.save()
            audit(actor=request.user, action="shift.updated", instance=shift, new_values={"title": shift.title, "code": shift.code})
        messages.success(request, f"شیفت «{shift.title}» با موفقیت ویرایش شد.")
        return redirect("management_shifts")
    return render(request, "management/shift_form.html", {"form": form, "shift": shift, "title": "ویرایش شیفت کاری", "submit": "ذخیره تغییرات"})

@login_required
@manager_required
@require_POST
def management_shift_delete(request, pk):
    shift = get_object_or_404(Shift, pk=pk)
    blockers = [("کارمند با شیفت پیش‌فرض", shift.employees.count()),
                ("کارکرد ثبت‌شده", shift.shift_logs.count()),
                ("فروش روزانه لاین", shift.line_performances.count())]
    if any(count for _, count in blockers):
        messages.error(request, dependency_message("این شیفت", blockers))
        return redirect("management_shift_edit", pk=pk)
    title = shift.title
    delete_with_audit(request=request, obj=shift, action="shift.deleted",
                      description=f"حذف شیفت: {title}", old_values={"title": title, "code": shift.code})
    messages.success(request, f"شیفت «{title}» حذف شد.")
    return redirect("management_shifts")

# ==========================================
# Departments Management (غیرقابل حذف)
# ==========================================

@login_required
@manager_required
def management_departments(request):
    start, end = month_range()
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    departments = Department.objects.prefetch_related("commission_rates__commission_level").select_related("target_settings")
    if search:
        departments = departments.filter(name__icontains=search)
    if status == "active":
        departments = departments.filter(is_active=True)
    elif status == "inactive":
        departments = departments.filter(is_active=False)
    performance = dict(
        LineShiftPerformance.objects.filter(date__range=(start, end))
        .values_list("department_id").annotate(total=Coalesce(Sum("sold_units"), 0))
    )
    cards = []
    for department in departments.order_by("name"):
        target = getattr(department, "target_settings", None)
        units = performance.get(department.pk)
        target_result = target.evaluate_target(units or 0) if target and target.is_active else None
        cards.append({
            "department": department,
            "rates": [rate for rate in department.commission_rates.all() if rate.is_active],
            "target": target if target and target.is_active else None,
            "performance_units": units,
            "target_result": target_result,
        })
    return render(request, "management/department_list.html", {
        "cards": cards, "search": search, "status": status, "start": start, "end": end,
    })


@login_required
@manager_required
def management_department_detail(request, pk):
    department = get_object_or_404(Department, pk=pk)
    levels = CommissionLevel.objects.order_by("code")
    target = LineTarget.objects.filter(department=department).first()

    if request.method == "POST":
        section = request.POST.get("section")
        try:
            with transaction.atomic():
                if section == "rates":
                    for level in levels:
                        raw = request.POST.get(f"rate_{level.pk}", "").strip()
                        if raw:
                            value = int(raw)
                            if value < 0:
                                raise ValueError("ضریب پورسانت نمی‌تواند منفی باشد.")
                            LineCommissionRate.objects.update_or_create(
                                department=department, commission_level=level,
                                defaults={"rate_per_unit": value, "is_active": True},
                            )
                    action = "department.rates_updated"
                elif section == "target":
                    target = target or LineTarget(department=department)
                    values = {}
                    for field in ("bronze_units", "bronze_reward", "silver_units", "silver_reward", "gold_units", "gold_reward"):
                        values[field] = int(request.POST.get(field, getattr(target, field)))
                        if values[field] < 0:
                            raise ValueError("مقادیر تارگت و پاداش نمی‌توانند منفی باشند.")
                    if not values["bronze_units"] < values["silver_units"] < values["gold_units"]:
                        raise ValueError("ترتیب تارگت‌ها باید برنزی < نقره‌ای < طلایی باشد.")
                    for field, value in values.items():
                        setattr(target, field, value)
                    target.is_active = request.POST.get("is_active") == "on"
                    target.save()
                    action = "department.target_updated"
                else:
                    raise ValueError("بخش تنظیمات مشخص نیست.")
                audit(actor=request.user, action=action, instance=department,
                      description="به‌روزرسانی از مرکز کنترل لاین")
        except (TypeError, ValueError) as exc:
            messages.error(request, str(exc) or "مقادیر واردشده معتبر نیستند.")
        else:
            messages.success(request, "تنظیمات لاین ذخیره شد.")
            return redirect("management_department_detail", pk=department.pk)

    start, end = month_range()
    units = LineShiftPerformance.objects.filter(department=department, date__range=(start, end)).aggregate(
        total=Coalesce(Sum("sold_units"), 0)
    )["total"]
    rates_by_level = {rate.commission_level_id: rate for rate in department.commission_rates.all()}
    rate_rows = [{"level": level, "rate": rates_by_level.get(level.pk)} for level in levels]
    rules = ViolationRule.objects.filter(Q(all_departments=True) | Q(departments=department)).distinct().order_by("title")
    history = AuditLog.objects.filter(entity_type="Department", entity_id=str(department.pk))[:20]
    recent_performances = department.shift_performances.select_related("shift")[:10]
    return render(request, "management/department_detail.html", {
        "department": department, "rate_rows": rate_rows, "target": target,
        "performance_units": units, "target_result": target.evaluate_target(units) if target and target.is_active else None,
        "rules": rules, "history": history, "recent_performances": recent_performances,
        "start": start, "end": end,
    })

@login_required
@manager_required
def management_department_create(request):
    form = DepartmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            dept = form.save()
            audit(actor=request.user, action="department.created", instance=dept, new_values={"name": dept.name})
        messages.success(request, f"لاین «{dept.name}» با موفقیت ایجاد شد.")
        return redirect("management_departments")
    return render(request, "management/department_form.html", {"form": form, "title": "تعریف لاین جدید", "submit": "تعریف لاین"})

@login_required
@manager_required
def management_department_edit(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    form = DepartmentForm(request.POST or None, instance=dept)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            dept = form.save()
            audit(actor=request.user, action="department.updated", instance=dept, new_values={"name": dept.name, "is_active": dept.is_active})
        messages.success(request, f"لاین «{dept.name}» به‌روزرسانی شد.")
        return redirect("management_departments")
    return render(request, "management/department_form.html", {"form": form, "department": dept, "title": "ویرایش لاین", "submit": "ذخیره تغییرات"})

def department_delete_blockers(department):
    """وابستگی‌هایی که حذف لاین نباید با پاک‌کردن آن‌ها تاریخچه را از بین ببرد."""
    blockers = []

    checks = [
        ("کارمند با این لاین به‌عنوان لاین اصلی", department.primary_employees.count()),
        ("کارمند عضو این لاین", department.employees.count()),
        ("کارکرد ثبت‌شده در لاین اصلی", department.main_shift_logs.count()),
        ("کارکرد ثبت‌شده در لاین کمکی", department.support_shift_logs.count()),
        ("بازه کمکی ثبت‌شده", department.support_intervals.count()),
        ("فروش روزانه ثبت‌شده", department.shift_performances.count()),
        ("ضریب پورسانت", department.commission_rates.count()),
        ("تارگت لاین", int(LineTarget.objects.filter(department=department).exists())),
        ("تارگت گرید", department.grade_targets.count()),
        ("تارگت ماهانه تاریخی", department.monthly_targets.count()),
        ("اتصال قانون تخلف", department.violation_rules.count()),
    ]

    for label, count in checks:
        if count:
            blockers.append((label, count))

    return blockers


@login_required
@manager_required
@require_POST
def management_department_delete(request, pk):
    department = get_object_or_404(Department, pk=pk)
    blockers = department_delete_blockers(department)

    if blockers:
        messages.error(
            request,
            dependency_message("این لاین", blockers)
        )
        return redirect("management_department_edit", pk=pk)

    department_id = department.pk
    department_name = department.name

    delete_with_audit(request=request, obj=department, action="department.deleted",
                      description=f"حذف لاین بدون وابستگی: {department_name}",
                      old_values={"id": department_id, "name": department_name,
                                  "is_active": department.is_active})

    messages.success(request, f"لاین «{department_name}» با موفقیت حذف شد.")
    return redirect("management_departments")


# ==========================================
# Employees Management
# ==========================================

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
def employee_list(request):
    return redirect("management_employees")

@login_required
@manager_required
def management_employees(request):
    qs = Employee.objects.select_related("commission_level", "primary_department", "default_shift", "user").prefetch_related("departments")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    level = request.GET.get("level", "")
    dept = request.GET.get("department", "")
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(mobile__icontains=q)
            | Q(employee_code__icontains=q)
            | Q(user__username__icontains=q)
        )
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    if level:
        qs = qs.filter(commission_level_id=level)
    if dept:
        qs = qs.filter(Q(primary_department_id=dept) | Q(departments__id=dept)).distinct()

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
    allowed = {"summary", "performance", "shift_logs", "violations", "commission", "levels", "info"}
    if tab not in allowed:
        tab = "summary"
    return render(
        request,
        "management/employee_detail.html",
        {
            "employee": employee,
            "tab": tab,
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
@require_POST
def management_employee_delete(request, pk):
    employee = get_object_or_404(Employee.objects.select_related("user"), pk=pk)
    blockers = [("کارکرد ثبت‌شده", employee.shift_logs.count()),
                ("تخلف ثبت‌شده", employee.violations.count()),
                ("سابقه تغییر گرید", employee.level_history.count())]
    if any(count for _, count in blockers):
        messages.error(request, dependency_message("این کارمند", blockers))
        return redirect("management_employee_edit", pk=pk)
    name, user_id = employee.full_name, employee.user_id
    delete_with_audit(request=request, obj=employee, action="employee.deleted",
                      description=f"حذف پرونده کارمند: {name}",
                      old_values={"employee_code": employee.employee_code, "user_id": user_id})
    messages.success(request, f"پرونده «{name}» حذف شد؛ حساب کاربری برای جلوگیری از حذف ضمنی نگه داشته شد.")
    return redirect("management_employees")

@login_required
@manager_required
@require_POST
def management_shift_log_delete(request, pk):
    log = get_object_or_404(DailyShiftLog.objects.select_related("employee"), pk=pk)
    blockers = [("بازه کمکی", log.support_intervals.count())]
    if log.is_frozen or log.status == DailyShiftLog.Status.APPROVED:
        blockers.insert(0, ("کارکرد تأیید یا فریز‌شده", 1))
    if any(count for _, count in blockers):
        messages.error(request, dependency_message("این کارکرد", blockers))
        return redirect("management_shift_log_review_detail", pk=pk)
    snapshot = {"employee": log.employee.full_name, "date": str(log.date), "status": log.status}
    delete_with_audit(request=request, obj=log, action="shift_log.deleted",
                      description=f"حذف کارکرد {log.employee.full_name} در {log.date}", old_values=snapshot)
    messages.success(request, "کارکرد حذف شد.")
    return redirect("management_shift_log_reviews")

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
