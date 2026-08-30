# وضعیت پروژه الینور

آخرین به‌روزرسانی: 2026-08-30  
معماری قطعی: Django 5 + PostgreSQL 17 + Docker Compose

## وضعیت فعلی

- ورود و نقش‌های Manager/Employee: تکمیل
- مدیریت کارکنان، بخش‌ها، Level و تاریخچه Level + نام کاربری اختصاصی: تکمیل
- تعریف شیفت‌ها و ساعت کاری (Shift & Working Hours): تکمیل در گام ۱
- ثبت کارکرد روزانه شیفت، لاین اصلی و چند لاین کمکی (DailyShiftLog with Multi-Support Lines): تکمیل در گام ۲ و ارتقا یافته
- ثبت چند بازه زمانی دقیق برای لاین‌های کمکی با محاسبه server-side: تکمیل
- ثبت عملکرد فروش روزانه لاین‌ها در شیفت (LineShiftPerformance): تکمیل در گام ۳
- ماتریس ضرایب لاین و گرید + موتور تسهیم ساعتی و محاسبه پورسانت (LineCommissionRate & Engine): تکمیل در گام ۴
- کارنامه پورسانت کارمند با ریز محاسبات هر شیفت و هر لاین کمکی: تکمیل در گام ۴
- گزارش جامع تسویه پورسانت پرسنل برای مدیر: تکمیل در گام ۴
- رابط کاربری مدرن، صمیمی و سریع ثبت کارکرد با Date Pills و Live Summary: تکمیل
- برندینگ و پروفایل: تکمیل
- تعریف فعالیت و دسته‌بندی توسعه‌پذیر: تکمیل
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

Migration `0003_activity_workflow` ساختار قبلی ActivityType/Activity را با rename و data migration ارتقا می‌دهد. امتیاز و وضعیت رکوردهای قبلی حفظ و برای آن‌ها تاریخچه اولیه ساخته می‌شود.
Migration `0010_dailyshiftlog_support_departments` فیلد تکی `support_department` را به فیلد `support_departments` (ManyToManyField) تبدیل و داده‌های قبلی را به آن منتقل کرده و فیلد تکی قدیمی را حذف می‌کند.
Migration `0011_supportlineinterval` مدل فرزند و غیرمخرب `SupportLineInterval` را برای نگهداری لاین مقصد، شروع، پایان و مدت هر بازه اضافه می‌کند و دقت فیلدهای خلاصه ساعت را به دو رقم اعشار افزایش می‌دهد.

## امنیت و دسترسی

- کارمند نمی‌تواند کارمند دیگری را برای ثبت انتخاب کند.
- دسترسی جزئیات فعالیت و کارکرد روزانه کارمند به مالک رکورد محدود است.
- کارنامه پورسانت کارمند تنها پورسانت و کارکرد خود کارمند را نمایش می‌دهد.
- مدیر به گزارش تجمیعی و تسویه تمام پرسنل دسترسی دارد.
- امتیاز، سهم کالاها و مبالغ پورسانت در سرور محاسبه می‌شود و ورودی امتیاز/مبلغ از کارمند وجود ندارد.
- نوع واقعی فایل با امضای PDF یا decode تصویر کنترل می‌شود.
- رد و درخواست اصلاح بدون یادداشت مدیر پذیرفته نمی‌شود.
- تغییر وضعیت، شیفت، کارکرد روزانه، فروش لاین‌ها و ماتریس ضرایب Audit می‌شود.
- ایجاد، ویرایش و حذف هر بازه کمکی به‌صورت مستقل در `AuditLog` ثبت می‌شود.

## Step 5: Timed Support-Line Intervals — 2026-08-30
- Added `SupportLineInterval` as a child of `DailyShiftLog`.
- Added repeatable RTL form rows: destination line, start time, end time.
- Server calculates every interval duration, total support hours, main-line hours and total shift hours; posted summary values are ignored.
- Validates end-after-start, no overlap, within-shift bounds (including overnight shifts), and support line different from main line.
- Existing summary fields and `support_departments` remain synchronized for compatibility with current reports.
- Employee and manager detail pages show exact intervals and calculated totals.
- No new commission rule was introduced; intervals are structured input for later Rule Engine work.
- Test suite: 62 tests.

## Step 1: Shifts & Working Hours — 2026-08-29
- Added `Shift` model.
- Added `default_shift` and `standard_daily_hours` to `Employee`.
- Shift management CRUD for manager.

## Step 2: Main & Multiple Support Lines Daily Shift Log — 2026-08-29
- Redesigned `DailyShiftLog` model with `support_departments` (ManyToManyField).
- Complete removal of legacy single `support_department` field.
- Server-side calculation of `total_hours = main_hours + support_hours`.
- Multi-support line distribution engine: support hours are divided equally among selected support departments.
- Quick date pills (امروز، دیروز، پریروز، تقویم).
- Conversational, friendly Persian UI.
- Live calculation summary preview.
- Migration: `0010_dailyshiftlog_support_departments`.

## Step 3: Line Shift Performance (Daily Line Sales) — 2026-08-29
- Added `LineShiftPerformance` model.
- Batch sales entry interface for managers.

## Step 4: Line & Grade Matrix & Proportional Engine — 2026-08-29
- Added `LineCommissionRate` model and manager editable rates matrix.
- Proportional sharing calculation engine in `core/services.py`.
- Employee Commission Report page (`/my-commission/`) showing breakdown per shift and per support line.
- Manager Commission Settlement Report (`/management/commissions/`).
