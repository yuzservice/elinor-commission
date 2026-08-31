from django.contrib import admin
from .models import (
    AuditLog,
    CommissionLevel,
    DailyShiftLog,
    Department,
    Employee,
    EmployeeLevelHistory,
    LineCommissionRate,
    LineShiftPerformance,
    Shift,
    SystemSettings,
    Target,
    Violation,
    ViolationRule,
)
from .services import audit

admin.site.site_header = "مدیریت سامانه"
admin.site.site_title = "مدیریت"

@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "start_time", "end_time", "standard_hours", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("title", "code")

@admin.register(DailyShiftLog)
class DailyShiftLogAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "shift", "main_department", "main_hours", "has_support_line", "support_departments_display", "support_hours", "total_hours")
    list_filter = ("date", "shift", "main_department", "has_support_line")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_code")
    filter_horizontal = ("support_departments",)

@admin.register(LineShiftPerformance)
class LineShiftPerformanceAdmin(admin.ModelAdmin):
    list_display = ("date", "shift", "department", "sold_units", "sales_amount", "recorded_by", "created_at")
    list_filter = ("date", "shift", "department")
    search_fields = ("department__name", "description")

@admin.register(LineCommissionRate)
class LineCommissionRateAdmin(admin.ModelAdmin):
    list_display = ("department", "commission_level", "rate_per_unit", "is_active", "updated_at")
    list_filter = ("department", "commission_level", "is_active")

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display=("employee_code","full_name","mobile","role","default_shift","commission_level","is_active")
    list_filter=("role","default_shift","commission_level","is_active","departments")
    search_fields=("employee_code","first_name","last_name","mobile","user__username")
    filter_horizontal=("departments",)
    def has_delete_permission(self, request, obj=None): return False
    def save_model(self, request, obj, form, change):
        old = Employee.objects.get(pk=obj.pk) if change else None
        super().save_model(request,obj,form,change)
        if not old:
            audit(actor=request.user,action="employee.created",instance=obj,new_values={"employee_code":obj.employee_code})
        else:
            if old.commission_level_id != obj.commission_level_id:
                EmployeeLevelHistory.objects.create(employee=obj,previous_level=old.commission_level,new_level=obj.commission_level,changed_by=request.user,reason="تغییر از Django Admin")
                audit(actor=request.user,action="employee.level_changed",instance=obj,old_values={"commission_level":old.commission_level.code},new_values={"commission_level":obj.commission_level.code})
            if old.is_active != obj.is_active:
                audit(actor=request.user,action="employee.activated" if obj.is_active else "employee.deactivated",instance=obj,old_values={"is_active":old.is_active},new_values={"is_active":obj.is_active})

@admin.register(Violation)
class ViolationAdmin(admin.ModelAdmin):
    list_display=("employee","rule","violation_date","occurrence","points_snapshot")
    list_filter=("violation_date","rule")
    readonly_fields=("points_snapshot","created_at")

@admin.register(EmployeeLevelHistory)
class EmployeeLevelHistoryAdmin(admin.ModelAdmin):
    list_display=("employee","previous_level","new_level","changed_by","changed_at")
    readonly_fields=("employee","previous_level","new_level","changed_by","reason","changed_at")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display=("action","entity_type","entity_id","actor","created_at")
    list_filter=("action","entity_type")
    search_fields=("description","entity_id")
    readonly_fields=("actor","action","entity_type","entity_id","description","old_values","new_values","created_at")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False

admin.site.register([Department, CommissionLevel, ViolationRule, Target, SystemSettings])
