from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect
from django.core.exceptions import PermissionDenied

def reviewer_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not hasattr(request.user, "employee") or not request.user.employee.can_review:
            messages.error(request, "شما اجازه دسترسی به این بخش را ندارید.")
            return redirect("dashboard")
        return view(request, *args, **kwargs)
    return wrapped

def manager_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        employee = getattr(request.user, "employee", None)
        if not employee or employee.role != employee.Role.MANAGER:
            raise PermissionDenied("دسترسی به این بخش فقط برای مدیر امکان‌پذیر است.")
        return view(request, *args, **kwargs)
    return wrapped
