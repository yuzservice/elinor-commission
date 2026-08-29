import jdatetime
from django import template

register = template.Library()
PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

@register.filter
def jalali(value, fmt="%Y/%m/%d"):
    if not value:
        return "—"
    try:
        result = jdatetime.date.fromgregorian(date=value).strftime(fmt)
        return result.translate(PERSIAN_DIGITS)
    except (TypeError, ValueError):
        return value

@register.filter
def jalali_datetime(value):
    if not value:
        return "—"
    try:
        result = jdatetime.datetime.fromgregorian(datetime=value).strftime("%Y/%m/%d · %H:%M")
        return result.translate(PERSIAN_DIGITS)
    except (TypeError, ValueError):
        return value
