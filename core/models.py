from decimal import Decimal
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.validators import RegexValidator
from django.db import models

class Department(models.Model):
    name = models.CharField("نام بخش", max_length=100, unique=True)
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "لاین / بخش"
        verbose_name_plural = "لاین‌ها و بخش‌ها"

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

def generate_next_employee_code():
    codes = Employee.objects.values_list("employee_code", flat=True)
    numeric_codes = []
    for c in codes:
        try:
            numeric_codes.append(int(c))
        except (ValueError, TypeError):
            pass
    if numeric_codes:
        return str(max(numeric_codes) + 1)
    return "1001"

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
        if not self.employee_code:
            self.employee_code = generate_next_employee_code()
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
    class RecurrenceWindow(models.TextChoices):
        SAME_MONTH = "SAME_MONTH", "همان ماه"
        ROLLING_30_DAYS = "ROLLING_30_DAYS", "۳۰ روز گذشته"
        MANUAL_PERIOD = "MANUAL_PERIOD", "دوره قابل تنظیم"

    code = models.CharField("کد", max_length=20, unique=True)
    title = models.CharField("عنوان", max_length=180)
    first_points = models.PositiveIntegerField("مرتبه اول")
    second_points = models.PositiveIntegerField("مرتبه دوم")
    third_points = models.PositiveIntegerField("مرتبه سوم")
    recurrence_window = models.CharField(
        "بازه محاسبه تکرار",
        max_length=20,
        choices=RecurrenceWindow.choices,
        default=RecurrenceWindow.SAME_MONTH,
        help_text="این گزینه زیرساخت مدیریتی است؛ محاسبه خودکار تکرار تا نهایی‌شدن قانون کسب‌وکار فعال نمی‌شود.",
    )
    all_departments = models.BooleanField("قابل استفاده برای همه لاین‌ها", default=True)
    departments = models.ManyToManyField(Department, blank=True, related_name="violation_rules")
    is_active = models.BooleanField("فعال", default=True)
    def __str__(self): return self.title
    def points_for(self, occurrence): return [self.first_points, self.second_points, self.third_points][occurrence - 1]

class Violation(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="violations")
    rule = models.ForeignKey(ViolationRule, on_delete=models.PROTECT, related_name="violations")
    violation_date = models.DateField("تاریخ")
    occurrence = models.PositiveSmallIntegerField("مرتبه", validators=[MinValueValidator(1), MaxValueValidator(3)])
    points_snapshot = models.PositiveIntegerField("امتیاز تخلف")
    rule_snapshot = models.JSONField("نسخه قانون هنگام ثبت", default=dict, blank=True)
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
    class ReviewStatus(models.TextChoices):
        PENDING = "PENDING", "در انتظار تأیید مدیر"
        APPROVED = "APPROVED", "تأییدشده و واریز نهایی"
        REJECTED = "REJECTED", "ردشده"

    # Backward-compatible public name used throughout the shift-log workflow.
    Status = ReviewStatus

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
    status = models.CharField(
        "وضعیت تأیید",
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        db_index=True
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_shift_logs",
        verbose_name="بررسی‌کننده"
    )
    reviewed_at = models.DateTimeField("زمان بررسی", null=True, blank=True)
    manager_note = models.TextField("یادداشت / بازخورد مدیر", blank=True)
    is_frozen = models.BooleanField("محاسبات فریز شده", default=False)
    frozen_main_share_units = models.DecimalField(
        "سهم فریز شده لاین اصلی (کالا)", max_digits=10, decimal_places=2, default=Decimal("0.0")
    )
    frozen_support_share_units = models.DecimalField(
        "سهم فریز شده لاین‌های کمکی (کالا)", max_digits=10, decimal_places=2, default=Decimal("0.0")
    )
    frozen_total_units_share = models.DecimalField(
        "مجموع سهم فریز شده کالا", max_digits=10, decimal_places=2, default=Decimal("0.0")
    )
    frozen_commission_amount = models.PositiveBigIntegerField(
        "مبلغ پورسانت فریز شده (ریال)", default=0
    )
    frozen_snapshot_data = models.JSONField(
        "جزئیات فریز شده محاسبات شیفت", default=dict, blank=True
    )
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
        for other in self.shift_log.support_intervals.exclude(pk=self.pk):
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

class LineTarget(models.Model):
    department = models.OneToOneField(
        Department,
        on_delete=models.CASCADE,
        related_name="target_settings",
        verbose_name="لاین / بخش"
    )
    bronze_units = models.PositiveIntegerField("تارگت برنزی (تعداد کالا)", default=500)
    bronze_reward = models.PositiveBigIntegerField("پاداش تارگت برنزی (ریال)", default=5000000)
    silver_units = models.PositiveIntegerField("تارگت نقره‌ای (تعداد کالا)", default=1000)
    silver_reward = models.PositiveBigIntegerField("پاداش تارگت نقره‌ای (ریال)", default=12000000)
    gold_units = models.PositiveIntegerField("تارگت طلایی (تعداد کالا)", default=3000)
    gold_reward = models.PositiveBigIntegerField("پاداش تارگت طلایی (ریال)", default=30000000)
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["department__name"]
        verbose_name = "تارگت لاین"
        verbose_name_plural = "تارگت‌های لاین‌ها"

    def __str__(self):
        return f"تارگت‌های {self.department.name} (برنزی، نقره‌ای، طلایی)"

    def evaluate_target(self, units_sold):
        """بررسی سطح تارگت محقق‌شده و محاسبه پاداش بر اساس تعداد کالای فروخته‌شده."""
        units = Decimal(str(units_sold or 0))
        achieved_level = 0
        achieved_title = "در مسیر تارگت برنزی 🥉"
        reward_amount = 0
        next_target_units = None
        next_target_reward = None
        next_target_title = None
        progress_percent = 0

        t_bronze_u = Decimal(str(self.bronze_units or 0))
        t_silver_u = Decimal(str(self.silver_units or 0))
        t_gold_u = Decimal(str(self.gold_units or 0))

        if t_gold_u > 0 and units >= t_gold_u:
            achieved_level = 3
            achieved_title = "تکمیل تمام تارگت‌ها 🏆"
            reward_amount = self.gold_reward
            next_target_units = None
            next_target_reward = None
            next_target_title = "تکمیل تمام تارگت‌ها 🏆"
            progress_percent = 100
        elif t_silver_u > 0 and units >= t_silver_u:
            achieved_level = 2
            achieved_title = "تارگت نقره‌ای 🥈"
            reward_amount = self.silver_reward
            next_target_units = self.gold_units
            next_target_reward = self.gold_reward
            next_target_title = "تارگت طلایی 🥇"
            if t_gold_u > t_silver_u:
                progress_percent = min(100, int(((units - t_silver_u) / (t_gold_u - t_silver_u)) * 100))
            else:
                progress_percent = 100
        elif t_bronze_u > 0 and units >= t_bronze_u:
            achieved_level = 1
            achieved_title = "تارگت برنزی 🥉"
            reward_amount = self.bronze_reward
            next_target_units = self.silver_units
            next_target_reward = self.silver_reward
            next_target_title = "تارگت نقره‌ای 🥈"
            if t_silver_u > t_bronze_u:
                progress_percent = min(100, int(((units - t_bronze_u) / (t_silver_u - t_bronze_u)) * 100))
            else:
                progress_percent = 100
        else:
            achieved_level = 0
            achieved_title = "در مسیر تارگت برنزی 🥉"
            reward_amount = 0
            next_target_units = self.bronze_units
            next_target_reward = self.bronze_reward
            next_target_title = "تارگت برنزی 🥉"
            if t_bronze_u > 0:
                progress_percent = min(100, int((units / t_bronze_u) * 100))
            else:
                progress_percent = 0

        return {
            "has_target": True,
            "achieved_level": achieved_level,
            "achieved_title": achieved_title,
            "reward_amount": reward_amount,
            "next_target_units": next_target_units,
            "next_target_reward": next_target_reward,
            "next_target_title": next_target_title,
            "progress_percent": progress_percent,
            "bronze_units": self.bronze_units,
            "bronze_reward": self.bronze_reward,
            "silver_units": self.silver_units,
            "silver_reward": self.silver_reward,
            "gold_units": self.gold_units,
            "gold_reward": self.gold_reward,
            "units_sold": round(float(units), 2),
        }

class LineGradeTarget(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="grade_targets",
        verbose_name="لاین / بخش"
    )
    commission_level = models.ForeignKey(
        CommissionLevel,
        on_delete=models.CASCADE,
        related_name="line_targets",
        verbose_name="سطح / گرید"
    )
    target_1_units = models.PositiveIntegerField("تارگت ۱ (تعداد کالا)", default=500)
    target_1_reward = models.PositiveBigIntegerField("پاداش تارگت ۱ (ریال)", default=5000000)
    target_2_units = models.PositiveIntegerField("تارگت ۲ (تعداد کالا)", default=1000)
    target_2_reward = models.PositiveBigIntegerField("پاداش تارگت ۲ (ریال)", default=12000000)
    target_3_units = models.PositiveIntegerField("تارگت ۳ (تعداد کالا)", default=3000)
    target_3_reward = models.PositiveBigIntegerField("پاداش تارگت ۳ (ریال)", default=30000000)
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["department__name", "commission_level__code"]
        verbose_name = "تارگت لاین و گرید"
        verbose_name_plural = "تارگت‌های لاین‌ها و گریدها"
        unique_together = [("department", "commission_level")]

    def __str__(self):
        return f"تارگت‌های {self.department.name} - گرید {self.commission_level.code}"

    def evaluate_target(self, units_sold):
        units = Decimal(str(units_sold or 0))
        t1_u = Decimal(str(self.target_1_units or 0))
        t2_u = Decimal(str(self.target_2_units or 0))
        t3_u = Decimal(str(self.target_3_units or 0))

        if t3_u > 0 and units >= t3_u:
            achieved_level = 3
            achieved_title = "تارگت طلایی 🥇"
            reward_amount = self.target_3_reward
            next_target_units = None
            next_target_reward = None
            next_target_title = "تکمیل تمام تارگت‌ها 🏆"
            progress_percent = 100
        elif t2_u > 0 and units >= t2_u:
            achieved_level = 2
            achieved_title = "تارگت نقره‌ای 🥈"
            reward_amount = self.target_2_reward
            next_target_units = self.target_3_units
            next_target_reward = self.target_3_reward
            next_target_title = "تارگت طلایی 🥇"
            progress_percent = min(100, int(((units - t2_u) / (t3_u - t2_u)) * 100)) if t3_u > t2_u else 100
        elif t1_u > 0 and units >= t1_u:
            achieved_level = 1
            achieved_title = "تارگت برنزی 🥉"
            reward_amount = self.target_1_reward
            next_target_units = self.target_2_units
            next_target_reward = self.target_2_reward
            next_target_title = "تارگت نقره‌ای 🥈"
            progress_percent = min(100, int(((units - t1_u) / (t2_u - t1_u)) * 100)) if t2_u > t1_u else 100
        else:
            achieved_level = 0
            achieved_title = "در مسیر تارگت برنزی 🥉"
            reward_amount = 0
            next_target_units = self.target_1_units
            next_target_reward = self.target_1_reward
            next_target_title = "تارگت برنزی 🥉"
            progress_percent = min(100, int((units / t1_u) * 100)) if t1_u > 0 else 0

        return {
            "has_target": True,
            "achieved_level": achieved_level,
            "achieved_title": achieved_title,
            "reward_amount": reward_amount,
            "next_target_units": next_target_units,
            "next_target_reward": next_target_reward,
            "next_target_title": next_target_title,
            "progress_percent": progress_percent,
        }

class DepartmentMonthlyTarget(models.Model):
    year_month = models.CharField(
        "ماه و سال شمسی",
        max_length=7,
        db_index=True,
        help_text="فرمت ۱۴۰۵/۰۶",
        validators=[RegexValidator(r"^\d{4}/\d{2}$", "فرمت تاریخ باید به‌صورت ۱۴۰۵/۰۶ باشد.")]
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="monthly_targets",
        verbose_name="لاین / بخش"
    )
    target_units = models.PositiveIntegerField("تارگت تعداد فروش کالا", default=0)
    target_sales_amount = models.PositiveBigIntegerField("تارگت مبلغ فروش لاین (ریال)", default=0, blank=True)
    target_commission_points = models.PositiveBigIntegerField("تارگت پورسانت ناخالص لاین (ریال)", default=0, blank=True)
    reward_amount = models.PositiveBigIntegerField("پاداش دستیابی به تارگت لاین (ریال)", default=0, blank=True)
    description = models.TextField("توضیحات و اهداف شیفت/لاین برای پرسنل", blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_department_targets",
        verbose_name="تعیین‌کننده"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year_month", "department__name"]
        verbose_name = "تارگت ماهانه لاین"
        verbose_name_plural = "تارگت‌های ماهانه لاین‌ها"
        unique_together = [("year_month", "department")]

    def __str__(self):
        return f"تارگت ماه {self.year_month} - {self.department.name}: {self.target_units} عدد"
