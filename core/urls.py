from django.urls import path
from . import views
urlpatterns = [
 path("", views.dashboard, name="dashboard"), path("activities/", views.activity_list, name="activities"),
 path("activities/new/", views.activity_create, name="activity_create"), path("reviews/", views.review_queue, name="review_queue"),
 path("activities/<int:pk>/", views.activity_detail, name="activity_detail"), path("activities/<int:pk>/edit/", views.activity_edit, name="activity_edit"),
 path("reviews/<int:pk>/", views.activity_review, name="activity_review"), path("violations/", views.violation_list, name="violations"),
 path("violations/new/", views.violation_create, name="violation_create"), path("employees/", views.employee_list, name="employees"),
 path("management/employees/", views.management_employees, name="management_employees"),
 path("management/employees/create/", views.management_employee_create, name="management_employee_create"),
 path("management/employees/<int:pk>/", views.management_employee_detail, name="management_employee_detail"),
 path("management/employees/<int:pk>/edit/", views.management_employee_edit, name="management_employee_edit"),
 path("management/employees/<int:pk>/password/", views.management_employee_password, name="management_employee_password"),
 path("management/settings/branding/", views.branding_settings, name="branding_settings"),
 path("management/activity-types/", views.management_activity_types, name="management_activity_types"),
 path("management/activity-types/create/", views.management_activity_type_create, name="management_activity_type_create"),
 path("management/activity-types/<int:pk>/edit/", views.management_activity_type_edit, name="management_activity_type_edit"),
 path("management/activity-reviews/", views.management_activity_reviews, name="management_activity_reviews"),
 path("management/activity-reviews/<int:pk>/", views.management_activity_review_detail, name="management_activity_review_detail"),
 path("profile/", views.profile, name="profile"), path("profile/photo/", views.profile_photo, name="profile_photo"),
 path("profile/password/", views.profile_password, name="profile_password"),
]
