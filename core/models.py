from decimal import Decimal
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.validators import RegexValidator
from django.db import models

class Department(models.Model):
    name = models.CharField("نام بخش", max_length=100, unique=True)
    is_active = models.BooleanField("فعال", default=True)
    def __str__(self): return self.name

class CommissionLevel(models.Model):
    code = models.CharField("سطح", max_length=1, unique=True)
    performance_rate = models.PositiveIntegerField("ضریب عملکرد")
    violation_rate = models.PositiveIntegerField("ضریب تخلف")
    morning_rate = models.DecimalField("ضریب صبح", max_digits=8, decimal_places=2, default=1)
    def __str__(self): return f"سطح {self.code}"

class Employee(models.Model):
    class Role(models.TextChoices):
        MANAGER = "MANAGER", "مدیر"
        EMPLOYEE = "EMPLOYEE", "کارمند"
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="employee")
    employee_code = models.CharField("کد کارمند", max_length=20, unique=True)
    first_name = models.CharField("نام", max_length=75)
    last_name = models.CharField("نام خانوادگی", max_length=75)
    mobile = models.CharField("شماره موبایل", max_length=11, unique=True, validators=[RegexValidator(r"^09\d{9}$", "شماره موبایل باید ۱۱ رقم و با 09 شروع شود.")])
    profile_photo = models.ImageField("عکس پروفایل", upload_to="profiles/%Y/%m/", blank=True)
    role = models.CharField("نقش", max_length=12, choices=Role.choices, default=Role.EMPLOYEE)
    commission_level = models.ForeignKey(CommissionLevel, on_delete=models.PROTECT, related_name="employees")
    primary_department = models.ForeignKey(Department, on_delete=models.PROTECT, null=True, blank=True, related_name="primary_employees", verbose_name="بخش اصلی")
    departments = models.ManyToManyField(Department, blank=True, related_name="employees")
    start_date = models.DateField("تاریخ شروع", null=True, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["last_name", "first_name", "employee_code"]
    @property
    def full_name(self): return f"{self.first_name} {self.last_name}".strip()
    def __str__(self): return self.full_name
    @property
    def can_review(self): return self.role == self.Role.MANAGER
    @property
    def level(self): return self.commission_level
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.user_id and self.user.is_active != self.is_active:
            User.objects.filter(pk=self.user_id).update(is_active=self.is_active)
            self.user.is_active = self.is_active

class EmployeeLevelHistory(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="level_history")
    previous_level = models.ForeignKey(CommissionLevel, on_delete=models.PROTECT, null=True, blank=True, related_name="level_history_from")
    new_level = models.ForeignKey(CommissionLevel, on_delete=models.PROTECT, related_name="level_history_to")
    changed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="employee_level_changes")
    reason = models.TextField("دلیل", blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-changed_at"]
    def __str__(self): return f"{self.employee} → {self.new_level}"

class AuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    action = models.CharField(max_length=80, db_index=True)
    entity_type = models.CharField(max_length=80, db_index=True)
    entity_id = models.CharField(max_length=80, db_index=True)
    description = models.TextField(blank=True)
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    class Meta: ordering = ["-created_at"]
    def __str__(self): return f"{self.action}: {self.entity_type}#{self.entity_id}"

class SystemSettings(models.Model):
    panel_name = models.CharField("نام پنل", max_length=120, default="سامانه عملکرد")
    organization_name = models.CharField("نام مجموعه", max_length=120, default="الینور")
    logo = models.ImageField("لوگو", upload_to="branding/", blank=True)
    favicon = models.ImageField("فاوآیکون", upload_to="branding/", blank=True)
    primary_color = models.CharField("رنگ اصلی", max_length=7, default="#237554", validators=[RegexValidator(r"^#[0-9A-Fa-f]{6}$", "رنگ باید مانند #237554 باشد.")])
    updated_at = models.DateTimeField(auto_now=True)
    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
    def __str__(self): return self.panel_name

class ActivityCategory(models.Model):
    code = models.CharField("کد", max_length=40, unique=True)
    title = models.CharField("عنوان", max_length=120)
    description = models.TextField("توضیحات", blank=True)
    sort_order = models.PositiveIntegerField("ترتیب", default=0)
    active = models.BooleanField("فعال", default=True)
    class Meta: ordering = ["sort_order", "title"]
    def __str__(self): return self.title

class ActivityType(models.Model):
    class ScoringMethod(models.TextChoices):
        FIXED="FIXED","ثابت"
        QUANTITY_MULTIPLIER="QUANTITY_MULTIPLIER","مقدار × ضریب"
        DIRECT_VALUE="DIRECT_VALUE","مقدار مستقیم"
    class RecurrenceType(models.TextChoices):
        DAILY="DAILY","روزانه"; WEEKLY="WEEKLY","هفتگی"; MONTHLY="MONTHLY","ماهانه"; OCCASIONAL="OCCASIONAL","موردی"; UNLIMITED="UNLIMITED","بدون محدودیت"
    code = models.CharField("کد", max_length=20, unique=True)
    title = models.CharField("عنوان", max_length=150)
    category = models.ForeignKey(ActivityCategory, on_delete=models.PROTECT, related_name="activity_types", verbose_name="دسته‌بندی")
    description = models.TextField("توضیحات", blank=True)
    unit = models.CharField("واحد", max_length=50, default="تعداد")
    scoring_method = models.CharField("روش امتیازدهی", max_length=24, choices=ScoringMethod.choices, default=ScoringMethod.DIRECT_VALUE)
    score_value = models.DecimalField("امتیاز ثابت", max_digits=12, decimal_places=2, default=1)
    multiplier = models.DecimalField("ضریب", max_digits=12, decimal_places=2, default=1)
    is_commission_eligible = models.BooleanField("مشمول پورسانت", default=True)
    requires_manager_approval = models.BooleanField("نیازمند تأیید مدیر", default=True)
    requires_evidence = models.BooleanField("نیازمند مدرک", default=False)
    requires_time_tracking = models.BooleanField("نیازمند ثبت ساعت شروع و پایان", default=True)
    requires_quantity = models.BooleanField("نیازمند ثبت مقدار", default=False)
    allow_employee_note = models.BooleanField("اجازه توضیح کارمند", default=True)
    recurrence_type = models.CharField("تناوب", max_length=12, choices=RecurrenceType.choices, default=RecurrenceType.OCCASIONAL)
    max_daily_submissions = models.PositiveIntegerField("حداکثر ثبت روزانه", null=True, blank=True)
    minimum_value = models.DecimalField("حداقل مقدار", max_digits=14, decimal_places=2, null=True, blank=True)
    maximum_value = models.DecimalField("حداکثر مقدار", max_digits=14, decimal_places=2, null=True, blank=True)
    all_departments = models.BooleanField("قابل استفاده برای همه بخش‌ها", default=False)
    departments = models.ManyToManyField(Department, blank=True, related_name="activity_types")
    active = models.BooleanField("فعال", default=True)
    sort_order = models.PositiveIntegerField("ترتیب", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: ordering = ["sort_order", "title"]
    def __str__(self): return self.title
    def calculate_score(self, value):
        value = Decimal(value or 1)
        if self.scoring_method == self.ScoringMethod.FIXED: return self.score_value
        if self.scoring_method == self.ScoringMethod.QUANTITY_MULTIPLIER: return value * self.multiplier
        return value

class Activity(models.Model):
    class Status(models.TextChoices):
        DRAFT="DRAFT","پیش‌نویس"; PENDING="PENDING","در انتظار بررسی"; APPROVED="APPROVED","تأییدشده"; REJECTED="REJECTED","ردشده"; NEEDS_REVISION="NEEDS_REVISION","نیازمند اصلاح"
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="activities")
    activity_type = models.ForeignKey(ActivityType, on_delete=models.PROTECT, related_name="activities")
    activity_date = models.DateField("تاریخ فعالیت")
    start_time = models.TimeField("ساعت شروع", null=True, blank=True)
    end_time = models.TimeField("ساعت پایان", null=True, blank=True)
    duration_minutes = models.PositiveIntegerField("مدت فعالیت به دقیقه", null=True, blank=True)
    value = models.DecimalField("مقدار", max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))], default=1)
    definition_score_snapshot = models.DecimalField("مقدار امتیاز تعریف هنگام ثبت", max_digits=12, decimal_places=2, default=1)
    multiplier_snapshot = models.DecimalField("ضریب هنگام ثبت", max_digits=12, decimal_places=2, default=1)
    calculated_score = models.DecimalField("امتیاز محاسبه‌شده", max_digits=14, decimal_places=2, default=0)
    final_score = models.DecimalField("امتیاز نهایی", max_digits=14, decimal_places=2, default=0)
    employee_note = models.TextField("توضیحات کارمند", blank=True)
    evidence = models.FileField("مدرک", upload_to="evidence/%Y/%m/", blank=True)
    status = models.CharField("وضعیت", max_length=20, choices=Status.choices, default=Status.PENDING)
    submitted_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="submitted_activities")
    reviewed_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_activities")
    manager_note = models.TextField("یادداشت مدیر", blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: ordering = ["-activity_date", "-created_at"]
    @property
    def total_points(self): return self.final_score
    @property
    def quantity(self): return self.value
    @property
    def description(self): return self.employee_note

    @property
    def duration_display(self):
        if self.duration_minutes is None:
            return "—"
        hours, minutes = divmod(self.duration_minutes, 60)
        if hours and minutes:
            return f"{hours} ساعت و {minutes} دقیقه"
        if hours:
            return f"{hours} ساعت"
        return f"{minutes} دقیقه"

    def update_duration(self):
        if not self.start_time or not self.end_time:
            self.duration_minutes = None
            return
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        self.duration_minutes = end - start

class ActivityStatusHistory(models.Model):
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="status_history")
    previous_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, choices=Activity.Status.choices)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="activity_status_changes")
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["created_at"]
    def __str__(self): return f"{self.activity_id}: {self.previous_status} → {self.new_status}"

class ViolationRule(models.Model):
    code = models.CharField("کد", max_length=20, unique=True)
    title = models.CharField("عنوان", max_length=180)
    first_points = models.PositiveIntegerField("مرتبه اول")
    second_points = models.PositiveIntegerField("مرتبه دوم")
    third_points = models.PositiveIntegerField("مرتبه سوم")
    is_active = models.BooleanField("فعال", default=True)
    def __str__(self): return self.title
    def points_for(self, occurrence): return [self.first_points, self.second_points, self.third_points][occurrence - 1]

class Violation(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="violations")
    rule = models.ForeignKey(ViolationRule, on_delete=models.PROTECT, related_name="violations")
    violation_date = models.DateField("تاریخ")
    occurrence = models.PositiveSmallIntegerField("مرتبه", validators=[MinValueValidator(1), MaxValueValidator(3)])
    points_snapshot = models.PositiveIntegerField("امتیاز تخلف")
    description = models.TextField("شرح")
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="recorded_violations")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-violation_date", "-created_at"]

class Target(models.Model):
    title = models.CharField("عنوان", max_length=100)
    points = models.PositiveIntegerField("امتیاز هدف")
    reward = models.PositiveBigIntegerField("پاداش", default=0)
    is_active = models.BooleanField("فعال", default=True)
    class Meta: ordering = ["points"]
    def __str__(self): return self.title
