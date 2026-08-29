from datetime import date, timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .decorators import manager_required, reviewer_required
from .forms import ActivityForm, ActivityTypeForm, BrandingForm, EmployeeCreateForm, EmployeeEditForm, JalaliDateField, ManagerPasswordResetForm, ProfilePhotoForm, ReviewForm, ViolationForm
from .models import Activity, ActivityCategory, ActivityStatusHistory, ActivityType, AuditLog, CommissionLevel, Department, Employee, SystemSettings, Violation
from .services import audit, change_employee_level, employee_metrics, transition_activity

def health(request): return JsonResponse({"status":"ok"})
def month_range(day=None):
    day = day or timezone.localdate(); start = day.replace(day=1)
    end = (start.replace(month=start.month % 12 + 1, year=start.year + (start.month == 12)) - timedelta(days=1))
    return start, end

def supervised_employees(employee):
    qs = Employee.objects.filter(is_active=True)
    return qs

@login_required
def dashboard(request):
    employee = getattr(request.user, "employee", None)
    if not employee:
        if request.user.is_staff: return redirect("admin:index")
        raise PermissionDenied("برای این حساب پروفایل کارمند تعریف نشده است.")
    return manager_dashboard(request) if employee.can_review else employee_dashboard(request)

@login_required
def employee_dashboard(request):
    emp = request.user.employee; start, end = month_range(); metrics = employee_metrics(emp, start, end)
    recent = emp.activities.select_related("activity_type")[:8]
    return render(request, "core/employee_dashboard.html", {"employee":emp, "metrics":metrics, "recent":recent, "start":start})

@login_required
@reviewer_required
def manager_dashboard(request):
    start, end = month_range(); employees = supervised_employees(request.user.employee).select_related("commission_level")
    rows = [{"employee": e, **employee_metrics(e, start, end)} for e in employees]
    pending = Activity.objects.filter(status=Activity.Status.PENDING, employee__in=employees).select_related("employee", "activity_type")
    return render(request, "core/manager_dashboard.html", {"rows":rows, "pending":pending[:6], "pending_count":pending.count(),
        "total_score":sum(r["score"] for r in rows), "total_commission":sum(r["commission"] for r in rows),
        "today_count":Activity.objects.filter(activity_date=timezone.localdate()).count()})

@login_required
def activity_create(request):
    employee=getattr(request.user,"employee",None)
    if not employee: raise PermissionDenied
    form = ActivityForm(request.POST or None, request.FILES or None, employee=employee)
    if request.method == "POST" and form.is_valid():
        action=request.POST.get("action","submit")
        try:
            with transaction.atomic():
                Employee.objects.select_for_update().get(pk=employee.pk)
                obj=form.save(commit=False); obj.employee=employee; obj.submitted_by=request.user; kind=obj.activity_type
                if action=="submit": validate_daily_limit(employee,kind,obj.activity_date)
                obj.definition_score_snapshot=kind.score_value; obj.multiplier_snapshot=kind.multiplier
                obj.calculated_score=kind.calculate_score(obj.value); obj.final_score=obj.calculated_score; obj.status=Activity.Status.DRAFT; obj.save()
                ActivityStatusHistory.objects.create(activity=obj,previous_status="",new_status=Activity.Status.DRAFT,actor=request.user,note="ایجاد فعالیت")
                audit(actor=request.user,action="activity.created",instance=obj,new_values={"status":obj.status,"value":str(obj.value),"score":str(obj.calculated_score)})
                if action=="submit": transition_activity(obj,Activity.Status.PENDING if kind.requires_manager_approval else Activity.Status.APPROVED,request.user,audit_action="activity.submitted")
        except ValidationError as exc: form.add_error(None,exc)
        else:
            messages.success(request,"فعالیت ذخیره شد."); return redirect("activity_detail",pk=obj.pk)
    return render(request, "activities/form.html", {"form":form, "title":"ثبت فعالیت روزانه", "activity_type_data": activity_type_form_data(form)})

@login_required
def activity_list(request):
    qs = Activity.objects.select_related("employee", "activity_type")
    if not request.user.employee.can_review: qs = qs.filter(employee=request.user.employee)
    status=request.GET.get("status",""); kind=request.GET.get("type",""); date_value=request.GET.get("date",""); search=request.GET.get("q","").strip()
    if status: qs=qs.filter(status=status)
    if kind: qs=qs.filter(activity_type_id=kind)
    if date_value:
        try: qs=qs.filter(activity_date=JalaliDateField().clean(date_value))
        except Exception: pass
    if search: qs=qs.filter(employee_note__icontains=search)
    return render(request,"activities/list.html",{"activities":qs[:200],"activity_types":ActivityType.objects.filter(active=True),"statuses":Activity.Status.choices})

@login_required
@reviewer_required
def review_queue(request):
    return redirect("management_activity_reviews")

@login_required
@reviewer_required
def activity_review(request, pk):
    return redirect("management_activity_review_detail",pk=pk)

def validate_daily_limit(employee,kind,activity_date,exclude_pk=None):
    if not kind.max_daily_submissions: return
    qs=Activity.objects.filter(employee=employee,activity_type=kind,activity_date=activity_date).exclude(status__in=[Activity.Status.DRAFT,Activity.Status.REJECTED])
    if exclude_pk: qs=qs.exclude(pk=exclude_pk)
    if qs.count()>=kind.max_daily_submissions: raise ValidationError(f"حداکثر ثبت روزانه این فعالیت {kind.max_daily_submissions} بار است.")

@login_required
def activity_detail(request,pk):
    qs=Activity.objects.select_related("activity_type__category","employee","reviewed_by").prefetch_related("status_history__actor")
    if not request.user.employee.can_review: qs=qs.filter(employee=request.user.employee)
    return render(request,"activities/detail.html",{"activity":get_object_or_404(qs,pk=pk)})

@login_required
def activity_edit(request,pk):
    employee=getattr(request.user,"employee",None)
    activity=get_object_or_404(Activity,pk=pk,employee=employee)
    if activity.status not in {Activity.Status.DRAFT,Activity.Status.NEEDS_REVISION}: raise PermissionDenied("این فعالیت قابل ویرایش نیست.")
    form=ActivityForm(request.POST or None,request.FILES or None,instance=activity,employee=employee)
    if request.method=="POST" and form.is_valid():
        action=request.POST.get("action","submit"); previous=activity.status
        try:
            with transaction.atomic():
                Employee.objects.select_for_update().get(pk=employee.pk); obj=form.save(commit=False); kind=obj.activity_type
                if action=="submit": validate_daily_limit(employee,kind,obj.activity_date,obj.pk)
                obj.definition_score_snapshot=kind.score_value; obj.multiplier_snapshot=kind.multiplier; obj.calculated_score=kind.calculate_score(obj.value); obj.final_score=obj.calculated_score; obj.save()
                audit(actor=request.user,action="activity.updated",instance=obj,new_values={"value":str(obj.value),"score":str(obj.calculated_score)})
                if action=="submit": transition_activity(obj,Activity.Status.PENDING if kind.requires_manager_approval else Activity.Status.APPROVED,request.user,audit_action="activity.resubmitted" if previous==Activity.Status.NEEDS_REVISION else "activity.submitted")
        except ValidationError as exc: form.add_error(None,exc)
        else:
            messages.success(request,"فعالیت به‌روزرسانی شد."); return redirect("activity_detail",pk=obj.pk)
    return render(request,"activities/form.html",{"form":form,"activity":activity,"title":"اصلاح فعالیت","activity_type_data":activity_type_form_data(form)})

def activity_type_form_data(form):
    return [{"id":item.pk,"method":item.scoring_method,"method_label":item.get_scoring_method_display(),"score":str(item.score_value),"multiplier":str(item.multiplier),"unit":item.unit,"requires_evidence":item.requires_evidence} for item in form.fields["activity_type"].queryset]

def activity_type_snapshot(obj):
    return {"title":obj.title,"code":obj.code,"category":obj.category_id,"scoring_method":obj.scoring_method,"score_value":str(obj.score_value),"multiplier":str(obj.multiplier),"active":obj.active}

@login_required
@manager_required
def management_activity_types(request):
    qs=ActivityType.objects.select_related("category").prefetch_related("departments")
    q=request.GET.get("q","").strip(); category=request.GET.get("category",""); department=request.GET.get("department",""); active=request.GET.get("active","")
    if q: qs=qs.filter(Q(title__icontains=q)|Q(code__icontains=q))
    if category: qs=qs.filter(category_id=category)
    if department: qs=qs.filter(Q(all_departments=True)|Q(departments__id=department)).distinct()
    if active in {"1","0"}: qs=qs.filter(active=active=="1")
    return render(request,"management/activity_type_list.html",{"activity_types":qs,"categories":ActivityCategory.objects.filter(active=True),"departments":Department.objects.filter(is_active=True)})

@login_required
@manager_required
def management_activity_type_create(request):
    form=ActivityTypeForm(request.POST or None)
    if request.method=="POST" and form.is_valid():
        obj=form.save(); audit(actor=request.user,action="activity_type.created",instance=obj,new_values=activity_type_snapshot(obj)); messages.success(request,"تعریف فعالیت ساخته شد."); return redirect("management_activity_types")
    return render(request,"management/activity_type_form.html",{"form":form,"title":"تعریف فعالیت جدید"})

@login_required
@manager_required
def management_activity_type_edit(request,pk):
    obj=get_object_or_404(ActivityType,pk=pk); old=activity_type_snapshot(obj); form=ActivityTypeForm(request.POST or None,instance=obj)
    if request.method=="POST" and form.is_valid():
        obj=form.save(); new=activity_type_snapshot(obj); audit(actor=request.user,action="activity_type.updated",instance=obj,old_values=old,new_values=new)
        if old["active"]!=new["active"]: audit(actor=request.user,action="activity_type.activated" if new["active"] else "activity_type.deactivated",instance=obj,old_values={"active":old["active"]},new_values={"active":new["active"]})
        messages.success(request,"تعریف فعالیت به‌روزرسانی شد."); return redirect("management_activity_types")
    return render(request,"management/activity_type_form.html",{"form":form,"title":"ویرایش تعریف فعالیت","activity_type":obj})

@login_required
@manager_required
def management_activity_reviews(request):
    qs=Activity.objects.filter(status=Activity.Status.PENDING).select_related("employee","activity_type__category","employee__primary_department")
    q=request.GET.get("q","").strip(); employee=request.GET.get("employee",""); department=request.GET.get("department",""); kind=request.GET.get("type",""); date_value=request.GET.get("date",""); sort=request.GET.get("sort","oldest")
    if q: qs=qs.filter(Q(employee__first_name__icontains=q)|Q(employee__last_name__icontains=q)|Q(employee_note__icontains=q))
    if employee: qs=qs.filter(employee_id=employee)
    if department: qs=qs.filter(employee__primary_department_id=department)
    if kind: qs=qs.filter(activity_type_id=kind)
    if date_value:
        try: qs=qs.filter(activity_date=JalaliDateField().clean(date_value))
        except ValidationError: pass
    qs=qs.order_by("-submitted_at" if sort=="newest" else "submitted_at")
    return render(request,"management/activity_review_list.html",{"activities":qs,"employees":Employee.objects.filter(is_active=True),"departments":Department.objects.filter(is_active=True),"activity_types":ActivityType.objects.filter(active=True)})

@login_required
@manager_required
def management_activity_review_detail(request,pk):
    activity=get_object_or_404(Activity.objects.select_related("employee","activity_type__category").prefetch_related("status_history__actor"),pk=pk)
    form=ReviewForm(request.POST or None)
    if request.method=="POST" and form.is_valid():
        if activity.status!=Activity.Status.PENDING: raise PermissionDenied("این فعالیت دیگر در انتظار بررسی نیست.")
        note=form.cleaned_data["manager_note"]; new_status=form.cleaned_data["action"]; activity.manager_note=note; activity.reviewed_by=request.user; activity.reviewed_at=timezone.now(); activity.save(update_fields=["manager_note","reviewed_by","reviewed_at","updated_at"])
        action_map={Activity.Status.APPROVED:"activity.approved",Activity.Status.REJECTED:"activity.rejected",Activity.Status.NEEDS_REVISION:"activity.needs_revision"}
        transition_activity(activity,new_status,request.user,note,audit_action=action_map[new_status]); messages.success(request,"نتیجه بررسی ثبت شد."); return redirect("management_activity_reviews")
    return render(request,"management/activity_review_detail.html",{"activity":activity,"form":form})

@login_required
@reviewer_required
def violation_create(request):
    form=ViolationForm(request.POST or None)
    form.fields["employee"].queryset = supervised_employees(request.user.employee)
    if request.method == "POST" and form.is_valid():
        obj=form.save(commit=False); obj.recorded_by=request.user; obj.points_snapshot=obj.rule.points_for(obj.occurrence); obj.save()
        messages.success(request, "تخلف ثبت شد."); return redirect("violations")
    return render(request, "core/form.html", {"form":form, "title":"ثبت تخلف", "submit":"ثبت تخلف"})

@login_required
def violation_list(request):
    qs=Violation.objects.select_related("employee", "rule", "recorded_by")
    if not request.user.employee.can_review: qs=qs.filter(employee=request.user.employee)
    return render(request, "core/violation_list.html", {"violations":qs[:100]})

@login_required
@reviewer_required
def employee_list(request):
    return redirect("management_employees")

def employee_snapshot(employee):
    return {"first_name":employee.first_name,"last_name":employee.last_name,"mobile":employee.mobile,"employee_code":employee.employee_code,
        "primary_department":employee.primary_department_id,"commission_level":employee.commission_level_id,"start_date":str(employee.start_date or ""),"is_active":employee.is_active}

@login_required
@manager_required
def management_employees(request):
    qs = Employee.objects.select_related("commission_level", "primary_department").prefetch_related("departments")
    search = request.GET.get("q", "").strip()
    if search: qs = qs.filter(Q(first_name__icontains=search)|Q(last_name__icontains=search)|Q(mobile__icontains=search)|Q(employee_code__icontains=search))
    status = request.GET.get("status", "")
    if status in {"active","inactive"}: qs = qs.filter(is_active=status=="active")
    level = request.GET.get("level", "")
    if level: qs = qs.filter(commission_level_id=level)
    department = request.GET.get("department", "")
    if department: qs = qs.filter(Q(primary_department_id=department)|Q(departments__id=department)).distinct()
    sort_map = {"name":"last_name","-name":"-last_name","start_date":"start_date","-start_date":"-start_date","code":"employee_code","-code":"-employee_code"}
    sort = request.GET.get("sort", "name"); qs = qs.order_by(sort_map.get(sort, "last_name"), "first_name")
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "management/employee_list.html", {"page":page,"levels":CommissionLevel.objects.all(),"departments":Department.objects.filter(is_active=True),"filters":request.GET,"sort":sort})

@login_required
@manager_required
def management_employee_create(request):
    form = EmployeeCreateForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = request.user.__class__.objects.create_user(username=form.cleaned_data["employee_code"], password=form.cleaned_data["initial_password"],
                first_name=form.cleaned_data["first_name"], last_name=form.cleaned_data["last_name"], is_active=form.cleaned_data["is_active"])
            employee = form.save(commit=False); employee.user=user; employee.save(); form.save_m2m()
            audit(actor=request.user, action="employee.created", instance=employee, new_values=employee_snapshot(employee))
        messages.success(request, "کارمند با موفقیت ساخته شد."); return redirect("management_employee_detail", pk=employee.pk)
    return render(request, "management/employee_form.html", {"form":form,"title":"ساخت کارمند جدید","submit":"ساخت کارمند"})

@login_required
@manager_required
def management_employee_detail(request, pk):
    employee=get_object_or_404(Employee.objects.select_related("commission_level","primary_department","user").prefetch_related("departments","level_history__previous_level","level_history__new_level"),pk=pk)
    tab=request.GET.get("tab","summary")
    allowed={"summary","performance","activities","violations","commission","levels","info"}
    if tab not in allowed: tab="summary"
    return render(request,"management/employee_detail.html",{"employee":employee,"tab":tab,"activities":employee.activities.select_related("activity_type")[:20],"violations":employee.violations.select_related("rule")[:20]})

@login_required
@manager_required
def management_employee_edit(request, pk):
    employee=get_object_or_404(Employee.objects.select_related("commission_level","user"),pk=pk); old=employee_snapshot(employee); old_level=employee.commission_level
    form=EmployeeEditForm(request.POST or None,request.FILES or None,instance=employee)
    if request.method=="POST" and form.is_valid():
        with transaction.atomic():
            requested_level=form.cleaned_data["commission_level"]
            obj=form.save(commit=False); obj.commission_level=old_level; obj.save(); form.save_m2m()
            obj.user.first_name=obj.first_name; obj.user.last_name=obj.last_name; obj.user.save(update_fields=["first_name","last_name"])
            change_employee_level(obj,requested_level,request.user,form.cleaned_data.get("level_reason", ""))
            new=employee_snapshot(obj); changed={k:v for k,v in new.items() if old.get(k)!=v}; old_changed={k:old[k] for k in changed}
            if changed: audit(actor=request.user,action="employee.updated",instance=obj,old_values=old_changed,new_values=changed)
            if old["is_active"]!=obj.is_active: audit(actor=request.user,action="employee.activated" if obj.is_active else "employee.deactivated",instance=obj,old_values={"is_active":old["is_active"]},new_values={"is_active":obj.is_active})
        messages.success(request,"اطلاعات کارمند به‌روزرسانی شد."); return redirect("management_employee_detail",pk=obj.pk)
    return render(request,"management/employee_form.html",{"form":form,"employee":employee,"title":"ویرایش کارمند","submit":"ذخیره تغییرات"})

@login_required
@manager_required
def management_employee_password(request, pk):
    employee=get_object_or_404(Employee.objects.select_related("user"),pk=pk); form=ManagerPasswordResetForm(employee.user,request.POST or None)
    if request.method=="POST" and form.is_valid():
        form.save(); audit(actor=request.user,action="employee.password_reset",instance=employee,description="رمز عبور توسط مدیر بازنشانی شد.")
        messages.success(request,"رمز عبور با موفقیت تغییر کرد."); return redirect("management_employee_detail",pk=employee.pk)
    return render(request,"management/password_form.html",{"form":form,"employee":employee})

@login_required
def profile(request):
    employee=getattr(request.user,"employee",None)
    if not employee: raise PermissionDenied("پروفایل کارمند تعریف نشده است.")
    return render(request,"profile/detail.html",{"employee":employee})

@login_required
def profile_photo(request):
    employee=getattr(request.user,"employee",None)
    if not employee: raise PermissionDenied
    form=ProfilePhotoForm(request.POST or None,request.FILES or None,instance=employee)
    if request.method=="POST" and form.is_valid(): form.save(); messages.success(request,"عکس پروفایل به‌روزرسانی شد."); return redirect("profile")
    return render(request,"profile/photo_form.html",{"form":form})

@login_required
def profile_password(request):
    if not hasattr(request.user,"employee"): raise PermissionDenied
    form=PasswordChangeForm(request.user,request.POST or None)
    if request.method=="POST" and form.is_valid(): user=form.save(); update_session_auth_hash(request,user); messages.success(request,"رمز عبور تغییر کرد."); return redirect("profile")
    return render(request,"profile/password_form.html",{"form":form})

@login_required
@manager_required
def branding_settings(request):
    settings=SystemSettings.load(); form=BrandingForm(request.POST or None,request.FILES or None,instance=settings)
    if request.method=="POST" and form.is_valid():
        old={k:getattr(settings,k) for k in ["panel_name","organization_name","primary_color"]}; obj=form.save()
        audit(actor=request.user,action="settings.branding_updated",instance=obj,old_values=old,new_values={k:getattr(obj,k) for k in old})
        messages.success(request,"تنظیمات ظاهری ذخیره شد."); return redirect("branding_settings")
    return render(request,"management/branding_form.html",{"form":form})
