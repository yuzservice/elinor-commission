# وضعیت پروژه الینور

آخرین به‌روزرسانی: 2026-08-29  
معماری قطعی: Django 5 + PostgreSQL 17 + Docker Compose

## وضعیت فعلی

- ورود و نقش‌های Manager/Employee: تکمیل
- مدیریت کارکنان، بخش‌ها، Level و تاریخچه Level: تکمیل
- برندینگ و پروفایل: تکمیل
- تعریف فعالیت و دسته‌بندی توسعه‌پذیر: تکمیل در Batch 1
- سه روش امتیازدهی Fixed، Quantity × Multiplier و Direct Value: تکمیل
- اتصال تعریف فعالیت به یک/چند/همه بخش‌ها: تکمیل
- ثبت روزانه، پیش‌نویس، ویرایش و ارسال مجدد: تکمیل
- اعتبارسنجی مدرک تصویر/PDF تا ۵ مگابایت: تکمیل
- گردش وضعیت Pending/Approved/Rejected/Needs Revision و History: تکمیل
- صف بررسی و فیلترهای مدیریتی: تکمیل
- اتصال رخدادهای مهم فعالیت به AuditLog: تکمیل
- داشبورد و پورسانت فقط بر اساس رکورد Approved و مشمول پورسانت: تکمیل
- تخلف، تارگت و محاسبات قبلی: حفظ شده

## حفظ داده و Migration

Migration `0003_activity_workflow` ساختار قبلی ActivityType/Activity را با rename و data migration ارتقا می‌دهد. امتیاز و وضعیت رکوردهای قبلی حفظ و برای آن‌ها تاریخچه اولیه ساخته می‌شود. بکاپ پیش از migration در `backups/elinor_20260829_022722.dump` گرفته و فهرست آن با `pg_restore` اعتبارسنجی شده است؛ پوشه بکاپ وارد Git نمی‌شود.

## امنیت و دسترسی

- کارمند نمی‌تواند کارمند دیگری را برای ثبت انتخاب کند.
- دسترسی جزئیات فعالیت کارمند به مالک رکورد محدود است.
- امتیاز در سرور محاسبه می‌شود و ورودی امتیاز از کارمند وجود ندارد.
- نوع واقعی فایل با امضای PDF یا decode تصویر کنترل می‌شود.
- رد و درخواست اصلاح بدون یادداشت مدیر پذیرفته نمی‌شود.
- تغییر وضعیت و تغییر تعریف فعالیت Audit می‌شود؛ اطلاعات حساس وارد Audit نمی‌شود.

## تست و عملیات

مجموعه فعلی شامل ۳۰ تست خودکار PostgreSQL برای کارکنان، دسترسی‌ها، پورسانت، تعریف فعالیت، ثبت، محدودیت روزانه، مدرک و گردش تأیید است. نتیجه نهایی تست و smoke check در گزارش تحویل Batch ثبت می‌شود.

## TODO پیشنهادی

- Manager Adjustment مقدار/امتیاز با reason و Audit کامل (عمداً از Batch 1 خارج ماند تا مدل مالی بدون قاعده نهایی پیچیده نشود)
- مدل مستقل Supervisor و محدوده سرپرستی پس از تعیین ساختار سازمانی
- Object Storage برای media در استقرار نهایی
- قفل دوره محاسبه و snapshot نهایی حقوق
- نهایی‌سازی ضریب صبح و قواعد دقیق شیت
- اعلان درخواست اصلاح و نتیجه بررسی

## Activity Raw Input Correction — 2026-08-29

Completed after Batch 1:

- Employee activity submission no longer exposes score inputs.
- Added `start_time` and `end_time` to Activity.
- Added server-calculated `duration_minutes`.
- Added `requires_time_tracking` to ActivityType.
- Added `requires_quantity` to ActivityType.
- Quantity is shown/required only for definitions that require measurable quantity.
- Quantity unit comes from ActivityType `unit`.
- Existing QUANTITY_MULTIPLIER and DIRECT_VALUE definitions were migrated to `requires_quantity=True`.
- Score remains server-side only.
- POST tampering of score/final score/snapshots is ignored.
- End time must be later than start time.
- Manager review shows start time, end time, duration, quantity and unit.
- Existing activity records were preserved.

Migration:
- `0004_activity_duration_minutes_activity_end_time_and_more`

Validation:
- PostgreSQL test suite: 36 tests passed.
- Django system check: clean.
- Health endpoint: healthy.

Important product rule:
Employee submits raw operational data:
activity type + date + start/end time + optional quantity + note/evidence.
Employee never enters score.
Scoring and commission calculations remain server-side.

Current technical note:
All existing ActivityTypes currently have `requires_time_tracking=True`.
Managers may disable time tracking per ActivityType where it is not applicable.
