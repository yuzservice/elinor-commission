import contextvars
from contextlib import contextmanager

_branch_id = contextvars.ContextVar("active_branch_id", default=None)
_employee_id = contextvars.ContextVar("active_employee_id", default=None)


def current_branch_id():
    return _branch_id.get()


def current_employee_id():
    return _employee_id.get()


def activate_scope(*, branch_id, employee_id):
    _branch_id.set(branch_id)
    _employee_id.set(employee_id)


def clear_scope():
    _branch_id.set(None)
    _employee_id.set(None)


@contextmanager
def without_branch_scope():
    """محاسبه روی همه شعبه‌ها، بدون اینکه شعبه فعال درخواست عوض بماند."""
    branch_id = current_branch_id()
    employee_id = current_employee_id()
    clear_scope()
    try:
        yield
    finally:
        activate_scope(branch_id=branch_id, employee_id=employee_id)


def assign_branch(instance):
    """شعبه خالی را از رابطه، شعبه فعال همین درخواست، یا اولین شعبه پر می‌کند."""
    if getattr(instance, "branch_id", None):
        return
    related = _related_branch_id(instance)
    if related:
        instance.branch_id = related
        return
    if current_branch_id():
        instance.branch_id = current_branch_id()
        return
    from .models import Branch
    home = Branch.objects.filter(name="فروشگاه ساری").values_list("pk", flat=True).first()
    if not home:
        home = Branch.objects.order_by("sort_order", "pk").values_list("pk", flat=True).first()
    if home:
        instance.branch_id = home


def _related_branch_id(instance):
    for attr in ("employee", "department", "main_department"):
        related_id = getattr(instance, f"{attr}_id", None)
        if not related_id:
            continue
        related = getattr(instance, attr, None)
        branch_id = getattr(related, "branch_id", None)
        if branch_id:
            return branch_id
    return None
