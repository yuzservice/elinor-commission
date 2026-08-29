from django.db.models import DecimalField, Sum
from django.db.models.functions import Coalesce
from django.db import transaction
from .models import Activity, ActivityStatusHistory, AuditLog, EmployeeLevelHistory, Target

def audit(*, actor, action, instance, description="", old_values=None, new_values=None):
    return AuditLog.objects.create(actor=actor, action=action, entity_type=instance.__class__.__name__, entity_id=str(instance.pk),
        description=description, old_values=old_values or {}, new_values=new_values or {})

@transaction.atomic
def change_employee_level(employee, new_level, actor, reason=""):
    previous = employee.commission_level
    if previous_id := getattr(previous, "pk", None):
        if previous_id == new_level.pk: return False
    employee.commission_level = new_level
    employee.save(update_fields=["commission_level", "updated_at"])
    EmployeeLevelHistory.objects.create(employee=employee, previous_level=previous, new_level=new_level, changed_by=actor, reason=reason)
    audit(actor=actor, action="employee.level_changed", instance=employee, description=reason,
        old_values={"commission_level": previous.code}, new_values={"commission_level": new_level.code})
    return True

@transaction.atomic
def transition_activity(activity, new_status, actor, note="", audit_action=None):
    previous = activity.status
    activity.status = new_status
    if new_status == Activity.Status.PENDING:
        from django.utils import timezone
        activity.submitted_at = timezone.now()
    activity.save(update_fields=["status", "submitted_at", "updated_at"] if hasattr(activity, "updated_at") else ["status", "submitted_at"])
    ActivityStatusHistory.objects.create(activity=activity, previous_status=previous, new_status=new_status, actor=actor, note=note)
    audit(actor=actor, action=audit_action or f"activity.{new_status.lower()}", instance=activity, description=note,
        old_values={"status": previous}, new_values={"status": new_status})
    return activity

def employee_metrics(employee, start, end):
    approved = employee.activities.filter(status=Activity.Status.APPROVED, activity_date__range=(start, end), activity_type__is_commission_eligible=True)
    score = approved.aggregate(v=Coalesce(Sum("final_score"), 0, output_field=DecimalField()))["v"]
    violation_points = employee.violations.filter(violation_date__range=(start, end)).aggregate(v=Coalesce(Sum("points_snapshot"), 0))["v"]
    gross = int(score * employee.level.performance_rate)
    deduction = int(violation_points * employee.level.violation_rate)
    reached = Target.objects.filter(is_active=True, points__lte=score).order_by("-points").first()
    reward = reached.reward if reached else 0
    targets = list(Target.objects.filter(is_active=True))
    next_target = next((t for t in targets if t.points > score), None)
    return {"score": score, "violation_points": violation_points, "gross": gross, "deduction": deduction,
            "reward": reward, "commission": max(0, gross - deduction + reward), "next_target": next_target,
            "target_progress": min(100, int(score * 100 / next_target.points)) if next_target else 100,
            "approved_count": approved.count()}
