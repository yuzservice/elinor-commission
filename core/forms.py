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
from .models import Activity, ActivityCategory, ActivityType, Employee, SystemSettings, Violation

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

class ActivityForm(forms.ModelForm):
    activity_date = JalaliDateField(label="تاریخ فعالیت")
    start_time = forms.TimeField(
        label="ساعت شروع",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"})
    )
    end_time = forms.TimeField(
        label="ساعت پایان",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"})
    )
    evidence = forms.FileField(
        label="مدرک",
        required=False,
        validators=[FileExtensionValidator(
            ["jpg","jpeg","png","webp","pdf"],
            "فقط تصویر یا PDF مجاز است."
        )]
    )

    class Meta:
        model = Activity
        fields = [
            "activity_type",
            "activity_date",
            "start_time",
            "end_time",
            "value",
            "employee_note",
            "evidence",
        ]
        widgets = {
            "employee_note": forms.Textarea(attrs={"rows":3}),
            "value": forms.NumberInput(attrs={
                "step": "0.01",
                "min": "0.01",
                "inputmode": "decimal",
            }),
        }

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee

        self.fields["activity_type"].label = "نوع فعالیت"
        self.fields["value"].label = "مقدار"
        self.fields["value"].required = False

        self.fields["activity_date"].initial = (
            jdatetime.date.fromgregorian(date=timezone.localdate())
            .strftime("%Y/%m/%d")
        )

        qs = ActivityType.objects.filter(active=True).select_related("category")

        if employee and employee.role == Employee.Role.EMPLOYEE:
            qs = qs.filter(
                Q(all_departments=True)
                | Q(departments__in=employee.departments.all())
                | Q(departments=employee.primary_department)
            ).distinct()

        self.fields["activity_type"].queryset = qs

    def clean_evidence(self):
        file = self.cleaned_data.get("evidence")

        if file and file.size > 5 * 1024 * 1024:
            raise forms.ValidationError("حداکثر حجم فایل ۵ مگابایت است.")

        if file:
            extension = file.name.rsplit(".", 1)[-1].lower()

            try:
                if extension == "pdf":
                    if file.read(5) != b"%PDF-":
                        raise forms.ValidationError("فایل PDF معتبر نیست.")
                else:
                    image = Image.open(file)
                    image.verify()

                    allowed = {
                        "jpg": "JPEG",
                        "jpeg": "JPEG",
                        "png": "PNG",
                        "webp": "WEBP",
                    }

                    if image.format != allowed.get(extension):
                        raise forms.ValidationError(
                            "نوع واقعی تصویر با پسوند فایل سازگار نیست."
                        )

            except (UnidentifiedImageError, OSError):
                raise forms.ValidationError("فایل تصویر معتبر نیست.")

            finally:
                file.seek(0)

        return file

    def clean(self):
        data = super().clean()

        kind = data.get("activity_type")
        value = data.get("value")
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        evidence = (
            data.get("evidence")
            or getattr(self.instance, "evidence", None)
        )

        if not kind:
            return data

        # Time tracking
        if kind.requires_time_tracking:
            if not start_time:
                self.add_error("start_time", "ثبت ساعت شروع برای این فعالیت الزامی است.")
            if not end_time:
                self.add_error("end_time", "ثبت ساعت پایان برای این فعالیت الزامی است.")

            if start_time and end_time and end_time <= start_time:
                self.add_error(
                    "end_time",
                    "ساعت پایان باید بعد از ساعت شروع باشد."
                )
        else:
            data["start_time"] = None
            data["end_time"] = None

        # Quantity
        if kind.requires_quantity:
            if value is None:
                self.add_error(
                    "value",
                    f"ثبت مقدار ({kind.unit}) برای این فعالیت الزامی است."
                )
        else:
            # برای فعالیت‌هایی که مقدار ندارند، مقدار داخلی 1 است.
            # این مقدار توسط کارمند وارد نمی‌شود.
            data["value"] = Decimal("1")
            value = Decimal("1")

        value = data.get("value")

        if value is not None:
            if kind.minimum_value is not None and value < kind.minimum_value:
                self.add_error(
                    "value",
                    f"حداقل مقدار {kind.minimum_value} است."
                )

            if kind.maximum_value is not None and value > kind.maximum_value:
                self.add_error(
                    "value",
                    f"حداکثر مقدار {kind.maximum_value} است."
                )

        if kind.requires_evidence and not evidence:
            self.add_error(
                "evidence",
                "برای این فعالیت بارگذاری مدرک الزامی است."
            )

        if not kind.allow_employee_note:
            data["employee_note"] = ""

        return data

class ReviewForm(forms.Form):
    action = forms.ChoiceField(label="تصمیم مدیر", choices=[("APPROVED","تأیید"),("REJECTED","رد"),("NEEDS_REVISION","نیازمند اصلاح")])
    manager_note = forms.CharField(label="یادداشت مدیر", required=False, widget=forms.Textarea(attrs={"rows":3}))
    def clean(self):
        data = super().clean()
        if data.get("action") in {"REJECTED","NEEDS_REVISION"} and not data.get("manager_note", "").strip():
            self.add_error("manager_note", "برای رد یا درخواست اصلاح، درج توضیح الزامی است.")
        return data

class ActivityTypeForm(forms.ModelForm):
    class Meta:
        model=ActivityType
        fields=["title","code","category","description","unit","scoring_method","score_value","multiplier","is_commission_eligible","requires_manager_approval","requires_evidence","requires_time_tracking","requires_quantity","allow_employee_note","recurrence_type","max_daily_submissions","minimum_value","maximum_value","all_departments","departments","active","sort_order"]
        widgets={"description":forms.Textarea(attrs={"rows":3}),"departments":forms.CheckboxSelectMultiple()}
    def clean(self):
        data=super().clean(); minimum=data.get("minimum_value"); maximum=data.get("maximum_value")
        if minimum is not None and maximum is not None and minimum>maximum: self.add_error("maximum_value","حداکثر مقدار نمی‌تواند از حداقل کمتر باشد.")
        if not data.get("all_departments") and not data.get("departments"): self.add_error("departments","حداقل یک بخش انتخاب کنید یا گزینه همه بخش‌ها را فعال کنید.")
        return data

class ViolationForm(forms.ModelForm):
    violation_date = JalaliDateField(label="تاریخ تخلف")
    class Meta:
        model = Violation
        fields = ["employee", "rule", "violation_date", "occurrence", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows":3})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["violation_date"].initial = jdatetime.date.fromgregorian(date=timezone.localdate()).strftime("%Y/%m/%d")

class EmployeeBaseForm(forms.ModelForm):
    start_date = JalaliDateField(label="تاریخ شروع همکاری", required=False)
    class Meta:
        model = Employee
        fields = ["first_name", "last_name", "mobile", "employee_code", "profile_photo", "start_date", "primary_department", "departments", "commission_level", "is_active"]
        widgets = {"departments": forms.CheckboxSelectMultiple()}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and self.instance.pk and self.instance.start_date:
            self.initial["start_date"] = jdatetime.date.fromgregorian(date=self.instance.start_date).strftime("%Y/%m/%d")
    def clean(self):
        data = super().clean()
        primary = data.get("primary_department")
        departments = data.get("departments")
        if primary and departments is not None and primary not in departments:
            self.add_error("departments", "بخش اصلی باید در فهرست بخش‌های کارمند نیز انتخاب شود.")
        return data

class EmployeeCreateForm(EmployeeBaseForm):
    initial_password = forms.CharField(label="رمز عبور اولیه", widget=forms.PasswordInput, strip=False)
    class Meta(EmployeeBaseForm.Meta):
        fields = EmployeeBaseForm.Meta.fields
    def clean_initial_password(self):
        password = self.cleaned_data["initial_password"]
        try: validate_password(password)
        except ValidationError as exc: raise forms.ValidationError(exc.messages)
        return password

class EmployeeEditForm(EmployeeBaseForm):
    level_reason = forms.CharField(label="دلیل تغییر Level", required=False, widget=forms.Textarea(attrs={"rows":2}))

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
        widgets = {"primary_color": forms.TextInput(attrs={"type":"color"})}
