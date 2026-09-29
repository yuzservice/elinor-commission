from .models import Branch, Employee
from .scoping import activate_scope, clear_scope


class BranchScopeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_scope()
        request.branch = None
        request.branch_employee = None
        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            employee = Employee._base_manager.filter(user=request.user).first()
            request.branch_employee = employee
            branch = resolve_branch(request, employee)
            request.branch = branch
            activate_scope(
                branch_id=branch.pk if branch else None,
                employee_id=employee.pk if employee else None,
            )
        try:
            return self.get_response(request)
        finally:
            clear_scope()


def resolve_branch(request, employee):
    if employee is None:
        return None
    if employee.is_super_admin:
        raw = request.session.get("active_branch_id")
        if raw:
            chosen = Branch.objects.filter(pk=raw, is_active=True).first()
            if chosen:
                return chosen
        current = Branch.objects.filter(name="فروشگاه ساری", is_active=True).first()
        return current or Branch.objects.filter(is_active=True).order_by("sort_order", "pk").first()
    return employee.branch
