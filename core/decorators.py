from functools import wraps
from decimal import Decimal
from django.contrib import messages
from django.shortcuts import redirect
from django.core.exceptions import PermissionDenied


def get_or_create_manager_employee(user):
    from .models import Employee, CommissionLevel, Department
    employee = getattr(user, "employee", None)
    if not employee and (user.is_superuser or user.is_staff):
        default_level = CommissionLevel.objects.first()
        if not default_level:
            default_level = CommissionLevel.objects.create(
                code="A", performance_rate=1500, violation_rate=6000, morning_rate=Decimal("1.0")
            )
        default_dept = Department.objects.filter(is_active=True).first()
        employee, _ = Employee.objects.get_or_create(
            user=user,
            defaults={
                "first_name": user.first_name or "مدیر",
                "last_name": user.last_name or "سیستم",
                "role": Employee.Role.MANAGER,
                "commission_level": default_level,
                "primary_department": default_dept,
                "standard_daily_hours": Decimal("6.0"),
                "is_active": True,
            },
        )
        if default_dept and not employee.departments.exists():
            employee.departments.add(default_dept)
    return employee


def reviewer_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        employee = get_or_create_manager_employee(request.user)
        if not employee or not employee.can_review:
            messages.error(request, "شما اجازه دسترسی به این بخش را ندارید.")
            return redirect("dashboard")
        return view(request, *args, **kwargs)
    return wrapped


def manager_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        employee = get_or_create_manager_employee(request.user)
        if not employee or employee.role != employee.Role.MANAGER:
            raise PermissionDenied("دسترسی به این بخش فقط برای مدیر امکان‌پذیر است.")
        return view(request, *args, **kwargs)
    return wrapped
