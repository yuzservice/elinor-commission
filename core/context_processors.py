from .models import Branch, SystemSettings

def system_settings(request):
    data = {"system_settings": None, "active_branch": None, "is_super_admin": False, "all_branches": []}
    try:
        data["system_settings"] = SystemSettings.load()
    except Exception:
        return data
    employee = getattr(request, "branch_employee", None)
    data["active_branch"] = getattr(request, "branch", None)
    data["is_super_admin"] = bool(employee and employee.is_super_admin)
    if data["is_super_admin"]:
        data["all_branches"] = list(Branch.objects.filter(is_active=True))
    return data
