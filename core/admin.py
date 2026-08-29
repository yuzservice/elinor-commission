from django.contrib import admin
from .models import Activity, ActivityCategory, ActivityStatusHistory, ActivityType, AuditLog, CommissionLevel, Department, Employee, EmployeeLevelHistory, SystemSettings, Target, Violation, ViolationRule
from .services import audit

admin.site.site_header = "مدیریت سامانه"
admin.site.site_title = "مدیریت"

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display=("employee_code","full_name","mobile","role","commission_level","is_active")
    list_filter=("role","commission_level","is_active","departments")
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

@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display=("employee","activity_type","activity_date","value","final_score","status")
    list_filter=("status","activity_date","activity_type")
    readonly_fields=("definition_score_snapshot","multiplier_snapshot","calculated_score","final_score","created_at","updated_at","submitted_at","reviewed_at")

@admin.register(ActivityStatusHistory)
class ActivityStatusHistoryAdmin(admin.ModelAdmin):
    list_display=("activity","previous_status","new_status","actor","created_at")
    readonly_fields=("activity","previous_status","new_status","actor","note","created_at")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False

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

admin.site.register([Department, CommissionLevel, ActivityCategory, ActivityType, ViolationRule, Target, SystemSettings])
