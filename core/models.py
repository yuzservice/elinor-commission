from decimal import Decimal
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
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

class Shift(models.Model):
    class ShiftCode(models.TextChoices):
        MORNING = "MORNING", "شیفت صبح (۱۰ تا ۱۶)"
        EVENING = "EVENING", "شیفت عصر (۱۶ تا ۲۲)"
        CUSTOM = "CUSTOM", "سفارشی"

    code = models.CharField("کد شیفت", max_length=20, unique=True)
    title = models.CharField("عنوان شیفت", max_length=100)
    start_time = models.TimeField("ساعت شروع")
    end_time = models.TimeField("ساعت پایان")
    standard_hours = models.DecimalField(
        "ساعت کاری استاندارد",
        max_digits=4,
        decimal_places=1,
        default=Decimal("6.0"),
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("24.0"))]
    )
    is_active = models.BooleanField("فعال", default=True)
    sort_order = models.PositiveIntegerField("ترتیب", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "start_time", "title"]
        verbose_name = "شیفت"
        verbose_name_plural = "شیفت‌ها"

    def __str__(self):
        return f"{self.title} ({self.start_time.strftime('%H:%M')} تا {self.end_time.strftime('%H:%M')})"

    @property
    def duration_display(self):
        return f"{self.standard_hours} ساعت"

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
    default_shift = models.ForeignKey(
        'Shift',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name="شیفت پیش‌فرض"
    )
    standard_daily_hours = models.DecimalField(
        "ساعت کاری روزانه",
        max_digits=4,
        decimal_places=1,
        default=Decimal("6.0"),
        validators=[MinValueValidator(Decimal("1.0")), MaxValueValidator(Decimal("24.0"))]
    )
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
    logo = models.FileField("لوگو", upload_to="branding/", blank=True)
    favicon = models.FileField("فاوآیکون", upload_to="branding/", blank=True)
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

class DailyShiftLog(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="shift_logs", verbose_name="کارمند")
    date = models.DateField("تاریخ کارکرد")
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="shift_logs", verbose_name="شیفت")
    main_department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="main_shift_logs", verbose_name="لاین اصلی")
    main_hours = models.DecimalField(
        "ساعت در لاین اصلی",
        max_digits=5,
        decimal_places=2,
        default=Decimal("6.0"),
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("24.0"))]
    )
    has_support_line = models.BooleanField("حضور در لاین کمکی", default=False)
    support_departments = models.ManyToManyField(
        Department,
        blank=True,
        related_name="support_shift_logs",
        verbose_name="لاین‌های کمکی"
    )
    support_hours = models.DecimalField(
        "مجموع ساعت در لاین‌های کمکی",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.0"),
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.0")), MaxValueValidator(Decimal("24.0"))]
    )
    total_hours = models.DecimalField(
        "مجموع ساعت کار",
        max_digits=5,
        decimal_places=2,
        default=Decimal("6.0")
    )
    employee_note = models.TextField("یادداشت کارمند", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = "کارکرد روزانه شیفت"
        verbose_name_plural = "کارکردهای روزانه شیفت"
        unique_together = [("employee", "date", "shift")]

    def __str__(self):
        return f"{self.employee.full_name} - {self.date} - {self.shift.title}"

    @property
    def support_departments_display(self):
        if not self.has_support_line:
            return "—"
        depts = list(self.support_departments.all())
        if depts:
            return "، ".join(d.name for d in depts)
        return "—"

    def save(self, *args, **kwargs):
        if not self.has_support_line:
            self.support_hours = Decimal("0.0")
        support_h = self.support_hours or Decimal("0.0")
        self.total_hours = (self.main_hours or Decimal("0.0")) + support_h
        super().save(*args, **kwargs)

    def recalculate_allocations(self, *, save=True):
        """Rebuild legacy summary fields exclusively from persisted intervals."""
        intervals = list(self.support_intervals.all())
        support_minutes = sum(item.duration_minutes for item in intervals)
        total_minutes = int((self.shift.standard_hours or Decimal("0")) * 60)
        self.support_hours = Decimal(support_minutes) / Decimal(60)
        self.main_hours = Decimal(total_minutes - support_minutes) / Decimal(60)
        self.total_hours = Decimal(total_minutes) / Decimal(60)
        self.has_support_line = bool(intervals)
        if save:
            DailyShiftLog.objects.filter(pk=self.pk).update(
                support_hours=self.support_hours,
                main_hours=self.main_hours,
                total_hours=self.total_hours,
                has_support_line=self.has_support_line,
            )
            self.support_departments.set({item.department_id for item in intervals})


class SupportLineInterval(models.Model):
    shift_log = models.ForeignKey(
        DailyShiftLog, on_delete=models.CASCADE, related_name="support_intervals", verbose_name="کارکرد شیفت"
    )
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="support_intervals", verbose_name="لاین مقصد"
    )
    start_time = models.TimeField("ساعت شروع")
    end_time = models.TimeField("ساعت پایان")
    duration_minutes = models.PositiveIntegerField("مدت (دقیقه)", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time", "pk"]
        verbose_name = "بازه کمکی"
        verbose_name_plural = "بازه‌های کمکی"

    @staticmethod
    def minute_offset(value, shift):
        minute = value.hour * 60 + value.minute
        shift_start = shift.start_time.hour * 60 + shift.start_time.minute
        shift_end = shift.end_time.hour * 60 + shift.end_time.minute
        if shift_end <= shift_start and minute < shift_start:
            minute += 24 * 60
        return minute - shift_start

    def clean(self):
        super().clean()
        if not self.shift_log_id or not self.department_id or not self.start_time or not self.end_time:
            return
        shift = self.shift_log.shift
        start = self.minute_offset(self.start_time, shift)
        end = self.minute_offset(self.end_time, shift)
        shift_duration = self.minute_offset(shift.end_time, shift)
        if shift_duration <= 0:
            shift_duration += 24 * 60
        if end <= start:
            raise ValidationError({"end_time": "ساعت پایان باید بعد از ساعت شروع باشد."})
        if start < 0 or end > shift_duration:
            raise ValidationError("بازه کمکی باید داخل ساعت شروع و پایان شیفت باشد.")
        if self.department_id == self.shift_log.main_department_id:
            raise ValidationError({"department": "لاین کمکی نمی‌تواند همان لاین اصلی باشد."})
        overlaps = self.shift_log.support_intervals.exclude(pk=self.pk)
        for other in overlaps:
            other_start = self.minute_offset(other.start_time, shift)
            other_end = self.minute_offset(other.end_time, shift)
            if max(start, other_start) < min(end, other_end):
                raise ValidationError("بازه‌های کمکی نباید با هم هم‌پوشانی داشته باشند.")
        self.duration_minutes = end - start

    @property
    def duration_hours(self):
        return Decimal(self.duration_minutes) / Decimal(60)

    @property
    def duration_display(self):
        hours, minutes = divmod(self.duration_minutes, 60)
        if hours and minutes:
            return f"{hours} ساعت و {minutes} دقیقه"
        return f"{hours} ساعت" if hours else f"{minutes} دقیقه"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class LineShiftPerformance(models.Model):
    date = models.DateField("تاریخ فروش")
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="line_performances", verbose_name="شیفت")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="shift_performances", verbose_name="لاین / بخش")
    sold_units = models.PositiveIntegerField("تعداد کالای فروخته‌شده", default=0)
    sales_amount = models.PositiveBigIntegerField("مبلغ فروش (ریال)", default=0, blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="recorded_line_performances", verbose_name="ثبت‌کننده")
    description = models.TextField("توضیحات / یادداشت مدیر", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "shift__sort_order", "department__name"]
        verbose_name = "عملکرد فروش لاین در شیفت"
        verbose_name_plural = "عملکرد فروش لاین‌ها در شیفت"
        unique_together = [("date", "shift", "department")]

    def __str__(self):
        return f"{self.date} - {self.shift.title} - {self.department.name}: {self.sold_units} عدد"

class LineCommissionRate(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="commission_rates", verbose_name="لاین / بخش")
    commission_level = models.ForeignKey(CommissionLevel, on_delete=models.CASCADE, related_name="line_rates", verbose_name="سطح / گرید")
    rate_per_unit = models.PositiveIntegerField("مبلغ پورسانت به ازای هر کالا", default=1000)
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["department__name", "commission_level__code"]
        verbose_name = "نرخ پورسانت لاین و گرید"
        verbose_name_plural = "نرخ‌های پورسانت لاین‌ها و گریدها"
        unique_together = [("department", "commission_level")]

    def __str__(self):
        return f"{self.department.name} - گرید {self.commission_level.code}: {self.rate_per_unit}"
