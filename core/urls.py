from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    # Employee Shift Logs & Commission
    path("shift-logs/", views.shift_log_list, name="shift_logs"),
    path("shift-logs/new/", views.shift_log_create, name="shift_log_create"),
    path("shift-logs/<int:pk>/", views.shift_log_detail, name="shift_log_detail"),
    path("shift-logs/<int:pk>/edit/", views.shift_log_edit, name="shift_log_edit"),
    path("my-commission/", views.my_commission_report, name="my_commission_report"),

    # Manager Shift Log Reviews & Approvals
    path("management/shift-log-reviews/", views.management_shift_log_reviews, name="management_shift_log_reviews"),
    path("management/shift-log-reviews/<int:pk>/", views.management_shift_log_review_detail, name="management_shift_log_review_detail"),
    path("management/shift-log-reviews/<int:pk>/quick-approve/", views.management_shift_log_quick_approve, name="management_shift_log_quick_approve"),
    path("management/shift-log-reviews/<int:pk>/revert/", views.management_shift_log_revert, name="management_shift_log_revert"),
    path("management/shift-log-reviews/<int:pk>/delete/", views.management_shift_log_delete, name="management_shift_log_delete"),
    path("management/shift-logs/", views.management_shift_logs, name="management_shift_logs"),

    # Manager Line Sales Performance
    path("management/line-performances/", views.management_line_performances, name="management_line_performances"),
    path("management/line-performances/batch/", views.management_line_performance_batch, name="management_line_performance_batch"),
    path("management/line-performances/create/", views.management_line_performance_create, name="management_line_performance_create"),
    path("management/line-performances/<int:pk>/edit/", views.management_line_performance_edit, name="management_line_performance_edit"),
    path("management/line-performances/<int:pk>/delete/", views.management_line_performance_delete, name="management_line_performance_delete"),

    # Manager Line Rates & Commissions Settlement
    path("management/line-rates/", views.management_line_rates, name="management_line_rates"),
    path("management/commissions/", views.management_commission_report, name="management_commission_report"),

    # Violations
    path("violations/", views.violation_list, name="violations"),
    path("violations/new/", views.violation_create, name="violation_create"),
    path("management/violations/<int:pk>/", views.management_violation_detail, name="management_violation_detail"),
    path("management/violations/<int:pk>/delete/", views.management_violation_delete, name="management_violation_delete"),
    path("management/violation-rules/", views.management_violation_rules, name="management_violation_rules"),
    path("management/violation-rules/create/", views.management_violation_rule_create, name="management_violation_rule_create"),
    path("management/violation-rules/<int:pk>/edit/", views.management_violation_rule_edit, name="management_violation_rule_edit"),
    path("management/violation-rules/<int:pk>/delete/", views.management_violation_rule_delete, name="management_violation_rule_delete"),

    # Employees & Management
    path("employees/", views.employee_list, name="employees"),
    path("management/employees/", views.management_employees, name="management_employees"),
    path("management/employees/create/", views.management_employee_create, name="management_employee_create"),
    path("management/employees/<int:pk>/", views.management_employee_detail, name="management_employee_detail"),
    path("management/employees/<int:pk>/edit/", views.management_employee_edit, name="management_employee_edit"),
    path("management/employees/<int:pk>/photo/", views.management_employee_photo, name="management_employee_photo"),
    path("management/employees/<int:pk>/delete/", views.management_employee_delete, name="management_employee_delete"),
    path("management/employees/<int:pk>/password/", views.management_employee_password, name="management_employee_password"),

    # Settings & Definitions
    path("management/settings/branding/", views.branding_settings, name="branding_settings"),
    path("management/settings/backup/", views.management_backup_view, name="management_backup"),
    path("management/settings/backup/create/", views.management_backup_create, name="management_backup_create"),
    path("management/settings/backup/download/<str:filename>/", views.management_backup_download, name="management_backup_download"),
    path("management/settings/backup/restore/", views.management_backup_restore, name="management_backup_restore"),
    path("management/settings/backup/delete/<str:filename>/", views.management_backup_delete, name="management_backup_delete"),
    path("management/shifts/", views.management_shifts, name="management_shifts"),
    path("management/shifts/create/", views.management_shift_create, name="management_shift_create"),
    path("management/shifts/<int:pk>/edit/", views.management_shift_edit, name="management_shift_edit"),
    path("management/shifts/<int:pk>/delete/", views.management_shift_delete, name="management_shift_delete"),
    path("management/departments/", views.management_departments, name="management_departments"),
    path("management/departments/create/", views.management_department_create, name="management_department_create"),
    path("management/departments/<int:pk>/edit/", views.management_department_edit, name="management_department_edit"),
    path("management/departments/<int:pk>/delete/", views.management_department_delete, name="management_department_delete"),
    path("management/departments/<int:pk>/", views.management_department_detail, name="management_department_detail"),
    path("management/commission-levels/", views.management_commission_levels, name="management_commission_levels"),
    path("management/commission-levels/create/", views.management_commission_level_create, name="management_commission_level_create"),
    path("management/commission-levels/<int:pk>/edit/", views.management_commission_level_edit, name="management_commission_level_edit"),
    path("management/commission-levels/<int:pk>/delete/", views.management_commission_level_delete, name="management_commission_level_delete"),

    # Profile
    path("profile/", views.profile, name="profile"),
    path("profile/photo/", views.profile_photo, name="profile_photo"),
    path("profile/password/", views.profile_password, name="profile_password"),
]
