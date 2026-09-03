from decimal import Decimal
from django import forms
from django.utils import timezone
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db.models import Q
import jdatetime
from PIL import Image, UnidentifiedImageError
from .models import (
    DailyShiftLog,
    Department,
    DepartmentMonthlyTarget,
    Employee,
    LineShiftPerformance,
    Shift,
    SupportLineInterval,
    SystemSettings,
    Violation,
    ViolationRule,
)

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

class JalaliDateField(forms.CharField):
    default_error_messages = {"invalid": "تاریخ را به‌شکل ۱۴۰۵/۰۶/۰۷ وارد کنید."}
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label", "تاریخ")
        kwargs.setdefault("widget", forms.TextInput(attrs={"placeholder":"۱۴۰۵/۰۶/۰۷", "inputmode":"numeric", "autocomplete":"off", "class":"jalali-date"}))
        super().__init__(*args, **kwargs)
    def prepare_value(self, value):
        if hasattr(value, "year"):
            value = jdatetime.date.fromgregorian(date=value).strftime("%Y/%m/%d")
        return value
    def clean(self, value):
        value = super().clean(value)
        if not value:
            return None
        try:
            normalized = value.translate(PERSIAN_DIGITS).replace("-", "/").strip()
            year, month, day = map(int, normalized.split("/"))
            return jdatetime.date(year, month, day).togregorian()
        except (ValueError, TypeError):
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")

class ReviewForm(forms.Form):
    action = forms.ChoiceField(label="تصمیم مدیر", choices=[("APPROVED","تأیید"),("REJECTED","رد"),("NEEDS_REVISION","نیازمند اصلاح")])
    manager_note = forms.CharField(label="یادداشت مدیر", required=False, widget=forms.Textarea(attrs={"rows":3}))
    def clean(self):
        data = super().clean()
        if data.get("action") in {"REJECTED","NEEDS_REVISION"} and not data.get("manager_note", "").strip():
            self.add_error("manager_note", "برای رد یا درخواست اصلاح، درج توضیح الزامی است.")
        return data

class ShiftLogReviewForm(forms.Form):
    action = forms.ChoiceField(
        label="تصمیم مدیر",
        choices=[("APPROVED", "✅ تأیید کارکرد و واریز قطعی پورسانت"), ("REJECTED", "❌ رد کارکرد")],
        widget=forms.RadioSelect
    )
    manager_note = forms.CharField(
        label="یادداشت / بازخورد برای کارمند",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "توضیح یا یادداشت برای کارمند (در صورت رد کارکرد درج توضیح الزامی است)..."})
    )

    def clean(self):
        data = super().clean()
        if data.get("action") == "REJECTED" and not data.get("manager_note", "").strip():
            self.add_error("manager_note", "برای رد کارکرد، درج توضیح یا دلیل الزامی است.")
        return data

class ShiftForm(forms.ModelForm):
    start_time = forms.TimeField(
        label="ساعت شروع",
        widget=forms.TimeInput(attrs={"type": "time"})
    )
    end_time = forms.TimeField(
        label="ساعت پایان",
        widget=forms.TimeInput(attrs={"type": "time"})
    )

    class Meta:
        model = Shift
        fields = [
            "title",
            "code",
            "start_time",
            "end_time",
            "standard_hours",
            "is_active",
            "sort_order",
        ]
        widgets = {
            "standard_hours": forms.NumberInput(attrs={"step": "0.5", "min": "0.5", "inputmode": "decimal"}),
        }

    def clean(self):
        data = super().clean()
        start = data.get("start_time")
        end = data.get("end_time")
        if start and end and start == end:
            self.add_error("end_time", "ساعت شروع و پایان نمی‌تواند یکسان باشد.")
        return data

class DailyShiftLogForm(forms.ModelForm):
    date = JalaliDateField(label="تاریخ کارکرد")
    has_support_line = forms.BooleanField(
        label="حضور در لاین کمکی هم داشتم",
        required=False,
    )

    class Meta:
        model = DailyShiftLog
        fields = [
            "date",
            "shift",
            "main_department",
            "has_support_line",
            "employee_note",
        ]
        widgets = {
            "employee_note": forms.Textarea(attrs={
                "rows": 2,
                "placeholder": "مثلاً: ۲ ساعت آخر شیفت رفتم اکسسوری و پیراهن چون پیک شلوغی بود..."
            }),
        }

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee

        self.fields["shift"].queryset = Shift.objects.filter(is_active=True)
        self.fields["main_department"].queryset = Department.objects.filter(is_active=True)
        self.fields["shift"].label = "شیفت کاری"
        self.fields["main_department"].label = "لاین اصلی"
        self.fields["employee_note"].label = "یادداشت یا توضیح برای مدیر"

        if not self.is_bound and not self.instance.pk:
            self.fields["date"].initial = jdatetime.date.fromgregorian(date=timezone.localdate()).strftime("%Y/%m/%d")
            if employee:
                if employee.default_shift:
                    self.fields["shift"].initial = employee.default_shift
                if employee.primary_department:
                    self.fields["main_department"].initial = employee.primary_department


class SupportLineIntervalForm(forms.ModelForm):
    class Meta:
        model = SupportLineInterval
        fields = ["department", "start_time", "end_time"]
        widgets = {
            "start_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "end_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)


SupportLineIntervalFormSet = forms.inlineformset_factory(
    DailyShiftLog,
    SupportLineInterval,
    form=SupportLineIntervalForm,
    extra=0,
    can_delete=True,
    min_num=0,
    validate_min=False,
)

class LineShiftPerformanceForm(forms.ModelForm):
    date = JalaliDateField(label="تاریخ فروش")
    sold_units = forms.IntegerField(
        label="تعداد کالای فروخته‌شده",
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
    )
    sales_amount = forms.IntegerField(
        label="مبلغ فروش (ریال)",
        min_value=0,
        initial=0,
        required=False,
        widget=forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
    )

    class Meta:
        model = LineShiftPerformance
        fields = [
            "date",
            "shift",
            "department",
            "sold_units",
            "sales_amount",
            "description",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["shift"].queryset = Shift.objects.filter(is_active=True)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["department"].label = "لاین / بخش"

        if not self.is_bound and not self.instance.pk:
            self.fields["date"].initial = jdatetime.date.fromgregorian(date=timezone.localdate()).strftime("%Y/%m/%d")

class DepartmentMonthlyTargetForm(forms.ModelForm):
    class Meta:
        model = DepartmentMonthlyTarget
        fields = [
            "year_month",
            "department",
            "target_units",
            "target_sales_amount",
            "target_commission_points",
            "reward_amount",
            "description",
        ]
        widgets = {
            "year_month": forms.TextInput(attrs={"placeholder": "۱۴۰۵/۰۶", "dir": "ltr"}),
            "target_units": forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
            "target_sales_amount": forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
            "target_commission_points": forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
            "reward_amount": forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
            "description": forms.Textarea(attrs={"rows": 2, "placeholder": "توضیحات انگیزه و هدف برای پرسنل این لاین..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        if not self.is_bound and not self.instance.pk:
            j_now = jdatetime.date.fromgregorian(date=timezone.localdate())
            self.fields["year_month"].initial = f"{j_now.year:04d}/{j_now.month:02d}"

    def clean_year_month(self):
        ym = self.cleaned_data.get("year_month", "").translate(PERSIAN_DIGITS).strip()
        import re
        if not re.match(r"^\d{4}/\d{2}$", ym):
            raise forms.ValidationError("فرمت ماه شمسی باید به‌صورت ۱۴۰۵/۰۶ باشد.")
        return ym

class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "is_active"]

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        duplicate = Department.objects.filter(name__iexact=name)
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("لاین دیگری با این نام وجود دارد.")
        return name

class ViolationForm(forms.ModelForm):
    violation_date = JalaliDateField(label="تاریخ تخلف")
    class Meta:
        model = Violation
        fields = ["employee", "rule", "violation_date", "occurrence", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows":3})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["violation_date"].initial = jdatetime.date.fromgregorian(date=timezone.localdate()).strftime("%Y/%m/%d")
        self.fields["rule"].queryset = ViolationRule.objects.filter(is_active=True).order_by("title")


class ViolationRuleForm(forms.ModelForm):
    class Meta:
        model = ViolationRule
        fields = [
            "code", "title", "first_points", "second_points", "third_points",
            "recurrence_window", "all_departments", "departments", "is_active",
        ]
        widgets = {"departments": forms.CheckboxSelectMultiple()}

    def clean(self):
        data = super().clean()
        points = [data.get("first_points"), data.get("second_points"), data.get("third_points")]
        if all(value is not None for value in points) and not (points[0] <= points[1] <= points[2]):
            self.add_error("third_points", "مقادیر تکرار باید به‌ترتیب مرتبه اول، دوم و سوم صعودی باشند.")
        if not data.get("all_departments") and not data.get("departments"):
            self.add_error("departments", "حداقل یک لاین را انتخاب کنید یا قانون را سراسری قرار دهید.")
        return data

class EmployeeBaseForm(forms.ModelForm):
    start_date = JalaliDateField(label="تاریخ شروع همکاری", required=False)
    class Meta:
        model = Employee
        fields = [
            "first_name",
            "last_name",
            "mobile",
            "default_shift",
            "standard_daily_hours",
            "primary_department",
            "commission_level",
            "departments",
            "start_date",
            "profile_photo",
            "is_active",
        ]
        widgets = {
            "departments": forms.SelectMultiple(attrs={"class": "custom-multiselect"}),
            "standard_daily_hours": forms.NumberInput(attrs={"step": "0.5", "min": "1", "inputmode": "decimal"}),
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["commission_level"].label = "گرید پورسانت"
        self.fields["primary_department"].label = "لاین اصلی"
        self.fields["departments"].label = "لاین‌های مجاز (حضور اصلی و کمکی)"
        self.fields["departments"].help_text = "لاین‌هایی که کارمند مجاز به حضور در آن‌ها به عنوان لاین اصلی یا کمکی است را انتخاب کنید."
        if not self.is_bound and self.instance.pk and self.instance.start_date:
            self.initial["start_date"] = jdatetime.date.fromgregorian(date=self.instance.start_date).strftime("%Y/%m/%d")
    def clean(self):
        data = super().clean()
        primary = data.get("primary_department")
        departments = data.get("departments")
        if departments is not None:
            if primary and primary not in departments:
                # اگر کاربر تیک لاین اصلی قبلی را برداشته ولی دراپ‌داون بالا را تغییر نداده:
                if self.instance.pk and self.instance.primary_department_id == getattr(primary, "pk", None):
                    new_primary = departments.first() if hasattr(departments, "first") else (departments[0] if departments else None)
                    data["primary_department"] = new_primary
                else:
                    data["departments"] = departments | Department.objects.filter(pk=primary.pk)
            elif not primary and departments.exists():
                data["primary_department"] = departments.first()
        return data

class EmployeeCreateForm(EmployeeBaseForm):
    username = forms.CharField(
        label="نام کاربری (جهت ورود به سامانه)",
        max_length=150,
        help_text="نام کاربری انگلیسی برای ورود به سامانه (مثال: fatemeh یا 1004)",
    )
    initial_password = forms.CharField(label="رمز عبور اولیه", widget=forms.PasswordInput, strip=False)

    class Meta(EmployeeBaseForm.Meta):
        fields = [
            "first_name",
            "last_name",
            "username",
            "initial_password",
            "mobile",
            "start_date",
            "default_shift",
            "standard_daily_hours",
            "primary_department",
            "commission_level",
            "departments",
            "profile_photo",
            "is_active",
        ]

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        from django.contrib.auth.models import User
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("این نام کاربری قبلاً در سامانه ثبت شده است. لطفاً نام کاربری دیگری انتخاب کنید.")
        return username

    def clean_initial_password(self):
        password = self.cleaned_data["initial_password"]
        try:
            validate_password(password)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)
        return password

class EmployeeEditForm(EmployeeBaseForm):
    username = forms.CharField(
        label="نام کاربری (جهت ورود به سامانه)",
        max_length=150,
        help_text="نام کاربری انگلیسی جهت ورود به سامانه",
    )

    class Meta(EmployeeBaseForm.Meta):
        fields = [
            "first_name",
            "last_name",
            "username",
            "mobile",
            "default_shift",
            "standard_daily_hours",
            "primary_department",
            "commission_level",
            "start_date",
            "profile_photo",
            "departments",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and hasattr(self.instance, "user") and self.instance.user:
            self.fields["username"].initial = self.instance.user.username

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        from django.contrib.auth.models import User
        current_user = self.instance.user if (self.instance and hasattr(self.instance, "user")) else None
        qs = User.objects.filter(username__iexact=username)
        if current_user:
            qs = qs.exclude(pk=current_user.pk)
        if qs.exists():
            raise forms.ValidationError("این نام کاربری قبلاً توسط کاربر دیگری ثبت شده است.")
        return username

class ManagerPasswordResetForm(SetPasswordForm):
    pass

class ProfilePhotoForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ["profile_photo"]

class BrandingForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = ["panel_name", "organization_name", "logo", "favicon", "primary_color"]
        widgets = {"primary_color": forms.TextInput(attrs={"type": "color"})}

    def clean_logo(self):
        file = self.cleaned_data.get("logo")
        if file and hasattr(file, "size"):
            if file.size > 5 * 1024 * 1024:
                raise forms.ValidationError("حداکثر حجم فایل لوگو ۵ مگابایت است.")
            ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
            if ext not in ["jpg", "jpeg", "png", "webp", "svg", "ico"]:
                raise forms.ValidationError("فرمت فایل لوگو باید یکی از موارد PNG, JPG, SVG, WEBP یا ICO باشد.")
        return file

    def clean_favicon(self):
        file = self.cleaned_data.get("favicon")
        if file and hasattr(file, "size"):
            if file.size > 2 * 1024 * 1024:
                raise forms.ValidationError("حداکثر حجم فایل فاوآیکون ۲ مگابایت است.")
            ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
            if ext not in ["ico", "png", "svg", "jpg", "jpeg", "webp"]:
                raise forms.ValidationError("فرمت فایل فاوآیکون باید یکی از موارد ICO, PNG, SVG یا JPG باشد.")
        return file
