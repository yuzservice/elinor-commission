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
    Branch,
    CommissionLevel,
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
            "has_overtime",
            "overtime_start_time",
            "overtime_end_time",
            "overtime_department",
            "employee_note",
        ]
        widgets = {
            "overtime_start_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "overtime_end_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "employee_note": forms.Textarea(attrs={
                "rows": 2,
                "placeholder": "مثلاً: ۲ ساعت اضافه‌کاری ماندم چون مشتری زیادی در فروشگاه بود...",
            }),
        }

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee

        self.fields["shift"].queryset = Shift.objects.filter(is_active=True)
        self.fields["main_department"].queryset = Department.objects.filter(is_active=True)
        self.fields["overtime_department"].queryset = Department.objects.filter(is_active=True)
        self.fields["shift"].label = "شیفت کاری"
        self.fields["main_department"].label = "لاین اصلی"
        self.fields["has_overtime"].label = "ثبت اضافه‌کاری"
        self.fields["overtime_start_time"].label = "ساعت شروع اضافه‌کاری"
        self.fields["overtime_end_time"].label = "ساعت پایان اضافه‌کاری"
        self.fields["overtime_department"].label = "لاین اضافه‌کاری"
        self.fields["employee_note"].label = "یادداشت یا توضیح برای مدیر"

        self.fields["has_overtime"].required = False
        self.fields["overtime_start_time"].required = False
        self.fields["overtime_end_time"].required = False
        self.fields["overtime_department"].required = False

        if not self.is_bound and not self.instance.pk:
            self.fields["date"].initial = jdatetime.date.fromgregorian(date=timezone.localdate()).strftime("%Y/%m/%d")
            if employee:
                target_shift = employee.default_shift or Shift.objects.filter(is_active=True).first()
                if target_shift:
                    self.initial["shift"] = target_shift.pk
                    self.fields["shift"].initial = target_shift.pk
                if employee.primary_department:
                    self.initial["main_department"] = employee.primary_department_id
                    self.fields["main_department"].initial = employee.primary_department_id
                    self.initial["overtime_department"] = employee.primary_department_id
                    self.fields["overtime_department"].initial = employee.primary_department_id

    def clean(self):
        cleaned_data = super().clean()
        main_dept = cleaned_data.get("main_department")

        has_ot = cleaned_data.get("has_overtime")
        ot_start = cleaned_data.get("overtime_start_time")
        ot_end = cleaned_data.get("overtime_end_time")
        ot_dept = cleaned_data.get("overtime_department")

        if has_ot:
            if not ot_start or not ot_end:
                raise ValidationError("در صورت ثبت اضافه‌کاری، ساعت شروع و پایان آن الزامی است.")
            s_m = ot_start.hour * 60 + ot_start.minute
            e_m = ot_end.hour * 60 + ot_end.minute
            if e_m <= s_m:
                e_m += 24 * 60
            if e_m - s_m <= 0:
                raise ValidationError("ساعت پایان اضافه‌کاری باید بعد از ساعت شروع باشد.")
            if not ot_dept and main_dept:
                cleaned_data["overtime_department"] = main_dept
        else:
            cleaned_data["overtime_start_time"] = None
            cleaned_data["overtime_end_time"] = None
            cleaned_data["overtime_department"] = None
        return cleaned_data


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
        fields = ["employee", "rule", "violation_date", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows":3})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["violation_date"].initial = jdatetime.date.fromgregorian(date=timezone.localdate()).strftime("%Y/%m/%d")
        self.fields["rule"].queryset = ViolationRule.objects.filter(is_active=True).order_by("title")
        self.fields["employee"].queryset = Employee.objects.filter(
            is_active=True, role=Employee.Role.EMPLOYEE
        ).order_by("first_name", "last_name")


class EmployeeBaseForm(forms.ModelForm):
    start_date = JalaliDateField(label="تاریخ شروع همکاری", required=False)
    class Meta:
        model = Employee
        fields = [
            "first_name",
            "last_name",
            "mobile",
            "card_number",
            "default_shift",
            "standard_daily_hours",
            "primary_departments",
            "commission_level",
            "departments",
            "start_date",
            "profile_photo",
            "is_active",
        ]
        widgets = {
            "primary_departments": forms.SelectMultiple(attrs={"class": "custom-multiselect"}),
            "departments": forms.SelectMultiple(attrs={"class": "custom-multiselect"}),
            "standard_daily_hours": forms.NumberInput(attrs={"step": "0.5", "min": "1", "inputmode": "decimal"}),
            "card_number": forms.TextInput(attrs={"placeholder": "۶۰۳۷-xxxx-xxxx-xxxx", "dir": "ltr", "inputmode": "numeric"}),
        }
    def __init__(self, *args, **kwargs):
        self.actor = kwargs.pop("actor", None)
        super().__init__(*args, **kwargs)
        self.fields["commission_level"].label = "گرید پورسانت"
        self.fields["commission_level"].required = True
        self.fields["mobile"].required = True
        self.fields["primary_departments"].label = "لاین‌های اصلی"
        self.fields["primary_departments"].help_text = "یک یا چند لاین را به عنوان لاین اصلی انتخاب کنید."
        self.fields["departments"].label = "لاین‌های مجاز (حضور اصلی و کمکی)"
        self.fields["departments"].help_text = "لاین‌هایی که کارمند مجاز به حضور در آن‌ها به عنوان لاین اصلی یا کمکی است را انتخاب کنید."
        self.fields["card_number"].label = "شماره کارت بانکی"
        self.fields["card_number"].help_text = "شماره کارت ۱۶ رقمی جهت تسویه و واریز پورسانت"
        self.fields["card_number"].required = False
        if not self.is_bound and self.instance.pk and self.instance.start_date:
            self.initial["start_date"] = jdatetime.date.fromgregorian(date=self.instance.start_date).strftime("%Y/%m/%d")

    def clean_card_number(self):
        val = self.cleaned_data.get("card_number", "").strip().translate(PERSIAN_DIGITS)
        cleaned = val.replace("-", "").replace(" ", "")
        if cleaned and not cleaned.isdigit():
            raise forms.ValidationError("شماره کارت فقط باید شامل ارقام عددی باشد.")
        if cleaned and len(cleaned) != 16:
            raise forms.ValidationError("شماره کارت بانکی باید دقیقاً ۱۶ رقم باشد.")
        if len(cleaned) == 16:
            return f"{cleaned[:4]}-{cleaned[4:8]}-{cleaned[8:12]}-{cleaned[12:]}"
        return val
    def clean(self):
        data = super().clean()
        primary_depts = data.get("primary_departments")
        if primary_depts:
            data["primary_department"] = primary_depts.first()
        departments = data.get("departments")
        if departments is not None and primary_depts:
            data["departments"] = departments | primary_depts
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
            "card_number",
            "start_date",
            "default_shift",
            "standard_daily_hours",
            "primary_departments",
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
            "card_number",
            "default_shift",
            "standard_daily_hours",
            "primary_departments",
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

class AdminAccountForm(forms.Form):
    first_name = forms.CharField(label="نام", max_length=75)
    last_name = forms.CharField(label="نام خانوادگی", max_length=75)
    username = forms.CharField(
        label="نام کاربری",
        max_length=150,
        help_text="نام کاربری انگلیسی برای ورود به سامانه",
    )
    access_level = forms.ChoiceField(
        label="نوع دسترسی",
        choices=[
            ("BRANCH", "ادمین یک شعبه"),
            ("SUPER", "سوپر ادمین همه شعبه‌ها"),
        ],
        help_text="ادمین شعبه فقط شعبه انتخاب‌شده را می‌بیند. سوپر ادمین بین شعبه‌ها جابه‌جا می‌شود.",
    )
    branch = forms.ModelChoiceField(label="شعبه", queryset=Branch.objects.none(), required=False)
    is_active = forms.BooleanField(label="حساب فعال باشد", required=False, initial=True)
    password = forms.CharField(label="رمز عبور", widget=forms.PasswordInput, required=False, strip=False)

    def __init__(self, *args, instance=None, active_branch=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        branches = Branch.objects.filter(is_active=True)
        if instance and instance.branch_id:
            branches = Branch.objects.filter(Q(is_active=True) | Q(pk=instance.branch_id))
        self.fields["branch"].queryset = branches.order_by("sort_order", "name")
        if instance is None:
            self.fields["password"].required = True
            self.fields["password"].label = "رمز عبور اولیه"
        else:
            self.fields["password"].help_text = "اگر خالی بماند، رمز فعلی تغییر نمی‌کند."
        if not self.is_bound:
            selected = instance.branch if instance and instance.branch_id else active_branch
            self.initial.update({
                "first_name": instance.first_name if instance else "",
                "last_name": instance.last_name if instance else "",
                "username": instance.user.username if instance else "",
                "access_level": "SUPER" if instance and instance.is_super_admin else "BRANCH",
                "branch": selected.pk if selected else None,
                "is_active": instance.is_active if instance else True,
            })

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        from django.contrib.auth.models import User
        qs = User.objects.filter(username__iexact=username)
        if self.instance and self.instance.user_id:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("این نام کاربری قبلاً ثبت شده است.")
        return username

    def clean_password(self):
        password = self.cleaned_data.get("password") or ""
        if not password:
            if self.instance is None:
                raise forms.ValidationError("رمز عبور را وارد کنید.")
            return ""
        try:
            validate_password(password)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)
        return password

    def clean(self):
        data = super().clean()
        if data.get("access_level") == "SUPER":
            data["branch"] = None
        elif not data.get("branch"):
            self.add_error("branch", "شعبه این ادمین را انتخاب کنید.")
        return data

class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["name", "sort_order", "is_active"]

    def clean_name(self):
        name = " ".join(self.cleaned_data.get("name", "").split())
        qs = Branch.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("شعبه‌ای با این نام وجود دارد.")
        return name

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

class ProfileCardForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ["card_number"]
        widgets = {
            "card_number": forms.TextInput(attrs={
                "placeholder": "مثال: ۶۰۳۷۹۹۱۸۱۲۳۴۵۶۷۸",
                "dir": "ltr",
                "maxlength": "24",
                "inputmode": "numeric",
                "style": "font-family: monospace; letter-spacing: 2px; font-size: 16px; font-weight: bold; text-align: center;",
            })
        }

    def clean_card_number(self):
        val = self.cleaned_data.get("card_number", "").strip().translate(PERSIAN_DIGITS)
        cleaned = val.replace("-", "").replace(" ", "")
        if cleaned and not cleaned.isdigit():
            raise forms.ValidationError("شماره کارت فقط باید شامل ارقام عددی باشد.")
        if cleaned and len(cleaned) != 16:
            raise forms.ValidationError("شماره کارت بانکی باید دقیقاً ۱۶ رقم باشد.")
        if len(cleaned) == 16:
            return f"{cleaned[:4]}-{cleaned[4:8]}-{cleaned[8:12]}-{cleaned[12:]}"
        return val
