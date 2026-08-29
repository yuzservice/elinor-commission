from datetime import date
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from .forms import ActivityForm
from .models import Activity, ActivityCategory, ActivityStatusHistory, ActivityType, AuditLog, CommissionLevel, Department, Employee, EmployeeLevelHistory, Violation, ViolationRule
from .services import employee_metrics

class BaseEmployeeTest(TestCase):
    def setUp(self):
        self.level_a=CommissionLevel.objects.create(code="A",performance_rate=1400,violation_rate=6000)
        self.level_b=CommissionLevel.objects.create(code="B",performance_rate=1000,violation_rate=4000)
        self.department=Department.objects.create(name="لاین وسط")
        self.manager_user=User.objects.create_user("manager",password="StrongPass123!",is_staff=True)
        self.manager=Employee.objects.create(user=self.manager_user,employee_code="M001",first_name="مدیر",last_name="سیستم",mobile="09120000001",role=Employee.Role.MANAGER,commission_level=self.level_a,primary_department=self.department)
        self.manager.departments.add(self.department)
        self.employee_user=User.objects.create_user("E001",password="StrongPass123!")
        self.employee=Employee.objects.create(user=self.employee_user,employee_code="E001",first_name="کارمند",last_name="اول",mobile="09120000002",commission_level=self.level_a,primary_department=self.department)
        self.employee.departments.add(self.department)

class CommissionTests(BaseEmployeeTest):
    def setUp(self):
        super().setUp(); self.category=ActivityCategory.objects.create(code="MAIN",title="عملکرد اصلی"); self.kind=ActivityType.objects.create(code="M1",title="فعالیت",category=self.category,scoring_method=ActivityType.ScoringMethod.QUANTITY_MULTIPLIER,multiplier=10,requires_quantity=True,all_departments=True)
    def test_only_approved_activity_counts(self):
        for status in [Activity.Status.APPROVED,Activity.Status.PENDING]: Activity.objects.create(employee=self.employee,activity_type=self.kind,activity_date=date.today(),value=2,definition_score_snapshot=1,multiplier_snapshot=10,calculated_score=20,final_score=20,status=status,submitted_by=self.employee_user)
        m=employee_metrics(self.employee,date.today(),date.today()); self.assertEqual(m["score"],20); self.assertEqual(m["gross"],28000)
    def test_violation_is_deduction(self):
        rule=ViolationRule.objects.create(code="V1",title="تست",first_points=2,second_points=4,third_points=8)
        Violation.objects.create(employee=self.employee,rule=rule,violation_date=date.today(),occurrence=1,points_snapshot=2,description="x",recorded_by=self.manager_user)
        m=employee_metrics(self.employee,date.today(),date.today()); self.assertEqual(m["deduction"],12000); self.assertEqual(m["commission"],0)
    def test_jalali_date_input_is_stored_as_gregorian(self):
        form=ActivityForm(data={"activity_type":self.kind.pk,"activity_date":"۱۴۰۵/۰۶/۰۷","start_time":"09:00","end_time":"10:00","value":"1","employee_note":""},employee=self.employee)
        self.assertTrue(form.is_valid(),form.errors); self.assertEqual(form.cleaned_data["activity_date"],date(2026,8,29))

class ActivityWorkflowTests(BaseEmployeeTest):
    def setUp(self):
        super().setUp()
        self.category=ActivityCategory.objects.create(code="OP",title="وظیفه عملیاتی")
        self.kind=ActivityType.objects.create(code="A01",title="کمک انبار",category=self.category,scoring_method=ActivityType.ScoringMethod.QUANTITY_MULTIPLIER,multiplier=2,requires_quantity=True,requires_time_tracking=True,requires_manager_approval=True,max_daily_submissions=1)
        self.kind.departments.add(self.department)
        self.jalali_today="۱۴۰۵/۰۶/۰۷"
    def payload(self,**overrides):
        data={"activity_type":self.kind.pk,"activity_date":self.jalali_today,"start_time":"09:15","end_time":"10:45","value":"3","employee_note":"انجام شد","action":"submit"}; data.update(overrides); return data
    def submit(self,**overrides):
        self.client.force_login(self.employee_user); return self.client.post(reverse("activity_create"),self.payload(**overrides))
    def test_employee_submission_calculates_score_on_server(self):
        response=self.submit(calculated_score="9999"); self.assertEqual(response.status_code,302)
        item=Activity.objects.get(); self.assertEqual(item.calculated_score,6); self.assertEqual(item.final_score,6); self.assertEqual(item.duration_minutes,90); self.assertEqual(item.status,Activity.Status.PENDING); self.assertEqual(item.employee,self.employee)
        self.assertTrue(ActivityStatusHistory.objects.filter(activity=item,new_status=Activity.Status.PENDING).exists()); self.assertTrue(AuditLog.objects.filter(action="activity.submitted").exists())
    def test_draft_can_be_edited_and_submitted(self):
        response=self.submit(action="draft"); item=Activity.objects.get(); self.assertEqual(item.status,Activity.Status.DRAFT)
        response=self.client.post(reverse("activity_edit",args=[item.pk]),self.payload(value="4")); self.assertEqual(response.status_code,302); item.refresh_from_db(); self.assertEqual(item.status,Activity.Status.PENDING); self.assertEqual(item.final_score,8)
    def test_employee_form_never_exposes_score_fields(self):
        form=ActivityForm(employee=self.employee)
        self.assertNotIn("calculated_score",form.fields)
        self.assertNotIn("final_score",form.fields)
        self.assertNotIn("definition_score_snapshot",form.fields)
        self.assertNotIn("multiplier_snapshot",form.fields)

    def test_score_post_tampering_is_ignored(self):
        response=self.submit(
            calculated_score="999999",
            final_score="999999",
            definition_score_snapshot="999999",
            multiplier_snapshot="999999",
        )
        self.assertEqual(response.status_code,302)
        item=Activity.objects.get()
        self.assertEqual(item.calculated_score,6)
        self.assertEqual(item.final_score,6)
        self.assertEqual(item.multiplier_snapshot,2)

    def test_end_time_must_be_after_start_time(self):
        response=self.submit(start_time="11:00",end_time="10:00")
        self.assertEqual(response.status_code,200)
        self.assertEqual(Activity.objects.count(),0)
        self.assertContains(response,"ساعت پایان باید بعد از ساعت شروع باشد")

    def test_quantity_is_required_only_when_definition_requires_it(self):
        response=self.submit(value="")
        self.assertEqual(response.status_code,200)
        self.assertEqual(Activity.objects.count(),0)
        self.assertContains(response,"ثبت مقدار")

        self.kind.requires_quantity=False
        self.kind.scoring_method=ActivityType.ScoringMethod.FIXED
        self.kind.score_value=7
        self.kind.save()

        response=self.submit(value="")
        self.assertEqual(response.status_code,302)

        item=Activity.objects.get()
        self.assertEqual(item.value,1)
        self.assertEqual(item.calculated_score,7)

    def test_time_is_required_only_when_definition_requires_it(self):
        response=self.submit(start_time="",end_time="")
        self.assertEqual(response.status_code,200)
        self.assertEqual(Activity.objects.count(),0)
        self.assertContains(response,"ثبت ساعت شروع")

        self.kind.requires_time_tracking=False
        self.kind.save()

        response=self.submit(start_time="",end_time="")
        self.assertEqual(response.status_code,302)

        item=Activity.objects.get()
        self.assertIsNone(item.start_time)
        self.assertIsNone(item.end_time)
        self.assertIsNone(item.duration_minutes)

    def test_duration_is_calculated_server_side(self):
        response=self.submit(
            start_time="08:10",
            end_time="11:25",
            duration_minutes="99999",
        )
        self.assertEqual(response.status_code,302)

        item=Activity.objects.get()
        self.assertEqual(item.duration_minutes,195)

    def test_daily_limit_is_enforced(self):
        self.submit(); response=self.submit(); self.assertEqual(response.status_code,200); self.assertEqual(Activity.objects.count(),1); self.assertContains(response,"حداکثر ثبت روزانه")
    def test_employee_cannot_view_another_employee_activity(self):
        item=Activity.objects.create(employee=self.manager,activity_type=self.kind,activity_date=date.today(),value=1,submitted_by=self.manager_user)
        self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("activity_detail",args=[item.pk])).status_code,404)
    def test_employee_cannot_open_manager_review(self):
        self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("management_activity_reviews")).status_code,403)
    def test_manager_approve_creates_history_and_audit(self):
        self.submit(); item=Activity.objects.get(); self.client.force_login(self.manager_user)
        response=self.client.post(reverse("management_activity_review_detail",args=[item.pk]),{"action":"APPROVED","manager_note":"مورد تأیید است"}); self.assertEqual(response.status_code,302); item.refresh_from_db(); self.assertEqual(item.status,Activity.Status.APPROVED); self.assertEqual(item.reviewed_by,self.manager_user)
        self.assertTrue(ActivityStatusHistory.objects.filter(activity=item,new_status="APPROVED").exists()); self.assertTrue(AuditLog.objects.filter(action="activity.approved").exists())
    def test_revision_requires_note_and_can_be_resubmitted(self):
        self.submit(); item=Activity.objects.get(); self.client.force_login(self.manager_user)
        response=self.client.post(reverse("management_activity_review_detail",args=[item.pk]),{"action":"NEEDS_REVISION","manager_note":""}); self.assertEqual(response.status_code,200); item.refresh_from_db(); self.assertEqual(item.status,Activity.Status.PENDING)
        self.client.post(reverse("management_activity_review_detail",args=[item.pk]),{"action":"NEEDS_REVISION","manager_note":"مدرک کامل نیست"}); item.refresh_from_db(); self.assertEqual(item.status,Activity.Status.NEEDS_REVISION)
        self.client.force_login(self.employee_user); self.client.post(reverse("activity_edit",args=[item.pk]),self.payload()); item.refresh_from_db(); self.assertEqual(item.status,Activity.Status.PENDING); self.assertTrue(AuditLog.objects.filter(action="activity.resubmitted").exists())
    def test_required_evidence_type_and_size_validation(self):
        self.kind.requires_evidence=True; self.kind.save(); response=self.submit(); self.assertEqual(response.status_code,200); self.assertContains(response,"بارگذاری مدرک الزامی")
        bad=SimpleUploadedFile("proof.exe",b"x",content_type="application/octet-stream"); response=self.submit(evidence=bad); self.assertEqual(response.status_code,200); self.assertEqual(Activity.objects.count(),0)
    def test_inactive_and_other_department_types_hidden(self):
        other=Department.objects.create(name="صندوق"); hidden=ActivityType.objects.create(code="A02",title="مخفی",category=self.category,active=True); hidden.departments.add(other)
        inactive=ActivityType.objects.create(code="A03",title="غیرفعال",category=self.category,all_departments=True,active=False)
        self.client.force_login(self.employee_user); response=self.client.get(reverse("activity_create")); self.assertNotContains(response,"مخفی"); self.assertNotContains(response,"غیرفعال")
    def test_non_commission_activity_does_not_count(self):
        self.kind.is_commission_eligible=False; self.kind.save(); self.submit(); item=Activity.objects.get(); item.status=Activity.Status.APPROVED; item.save()
        self.assertEqual(employee_metrics(self.employee,date(2026,8,1),date(2026,8,31))["score"],0)

class ActivityDefinitionTests(BaseEmployeeTest):
    def setUp(self): super().setUp(); self.category=ActivityCategory.objects.create(code="DAILY",title="روزانه")
    def payload(self): return {"title":"چک صندوق","code":"D01","category":self.category.pk,"description":"","unit":"مرتبه","scoring_method":"FIXED","score_value":"10","multiplier":"1","is_commission_eligible":"on","requires_manager_approval":"on","allow_employee_note":"on","recurrence_type":"DAILY","max_daily_submissions":"1","all_departments":"on","active":"on","sort_order":"1"}
    def test_manager_can_create_definition_and_audit(self):
        self.client.force_login(self.manager_user); response=self.client.post(reverse("management_activity_type_create"),self.payload()); self.assertEqual(response.status_code,302); self.assertTrue(ActivityType.objects.filter(code="D01").exists()); self.assertTrue(AuditLog.objects.filter(action="activity_type.created").exists())
    def test_employee_cannot_manage_definitions(self):
        self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("management_activity_types")).status_code,403)

class EmployeePermissionTests(BaseEmployeeTest):
    def test_manager_can_list_employees(self): self.client.force_login(self.manager_user); self.assertEqual(self.client.get(reverse("management_employees")).status_code,200)
    def test_employee_cannot_list_employees(self): self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("management_employees")).status_code,403)
    def test_employee_cannot_access_another_employee_idor(self): self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("management_employee_detail",args=[self.manager.pk])).status_code,403)
    def test_inactive_employee_cannot_login(self):
        self.employee.is_active=False; self.employee.save(); self.employee_user.refresh_from_db(); self.assertFalse(self.employee_user.is_active); self.assertFalse(self.client.login(username="E001",password="StrongPass123!"))
    def test_user_without_employee_does_not_500(self):
        user=User.objects.create_user("standalone",password="StrongPass123!"); self.client.force_login(user); self.assertEqual(self.client.get(reverse("dashboard")).status_code,403)
    def test_employee_can_access_own_profile(self):
        self.client.force_login(self.employee_user); response=self.client.get(reverse("profile")); self.assertEqual(response.status_code,200); self.assertContains(response,self.employee.full_name)
    def test_employee_cannot_change_own_level(self): self.client.force_login(self.employee_user); self.assertEqual(self.client.post(reverse("management_employee_edit",args=[self.employee.pk]),{}).status_code,403)
    def test_branding_only_manager(self):
        self.client.force_login(self.employee_user); self.assertEqual(self.client.get(reverse("branding_settings")).status_code,403)
        self.client.force_login(self.manager_user); self.assertEqual(self.client.get(reverse("branding_settings")).status_code,200)

class EmployeeManagementTests(BaseEmployeeTest):
    def setUp(self): super().setUp(); self.client.force_login(self.manager_user)
    def employee_payload(self,**overrides):
        data={"first_name":"نیروی","last_name":"جدید","mobile":"09120000003","employee_code":"E002","start_date":"۱۴۰۵/۰۶/۰۷","primary_department":self.department.pk,"departments":[self.department.pk],"commission_level":self.level_a.pk,"is_active":"on","role":Employee.Role.EMPLOYEE,"initial_password":"AnotherStrong123!"}; data.update(overrides); return data
    def test_employee_code_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): Employee.objects.create(user=User.objects.create_user("duplicate1"),employee_code="E001",first_name="الف",last_name="ب",mobile="09120000004",commission_level=self.level_a)
    def test_mobile_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): Employee.objects.create(user=User.objects.create_user("duplicate2"),employee_code="E099",first_name="الف",last_name="ب",mobile="09120000002",commission_level=self.level_a)
    def test_manager_can_create_employee_atomically(self):
        response=self.client.post(reverse("management_employee_create"),self.employee_payload()); self.assertEqual(response.status_code,302)
        obj=Employee.objects.get(employee_code="E002"); self.assertEqual(obj.user.username,"E002"); self.assertTrue(AuditLog.objects.filter(action="employee.created",entity_id=str(obj.pk)).exists())
    def test_manager_can_edit_and_level_change_creates_history_and_audit(self):
        payload=self.employee_payload(first_name="ویرایش",mobile=self.employee.mobile,employee_code=self.employee.employee_code,commission_level=self.level_b.pk,level_reason="ارتقای آزمایشی"); payload.pop("initial_password"); payload.pop("role")
        response=self.client.post(reverse("management_employee_edit",args=[self.employee.pk]),payload); self.assertEqual(response.status_code,302)
        self.employee.refresh_from_db(); self.assertEqual(self.employee.first_name,"ویرایش"); self.assertEqual(self.employee.commission_level,self.level_b)
        self.assertTrue(EmployeeLevelHistory.objects.filter(employee=self.employee,previous_level=self.level_a,new_level=self.level_b).exists()); self.assertTrue(AuditLog.objects.filter(action="employee.level_changed",entity_id=str(self.employee.pk)).exists())
    def test_deactivation_syncs_login_and_audits(self):
        payload=self.employee_payload(mobile=self.employee.mobile,employee_code=self.employee.employee_code,commission_level=self.level_a.pk); payload.pop("initial_password"); payload.pop("role"); payload.pop("is_active")
        self.client.post(reverse("management_employee_edit",args=[self.employee.pk]),payload); self.employee_user.refresh_from_db(); self.assertFalse(self.employee_user.is_active); self.assertTrue(AuditLog.objects.filter(action="employee.deactivated").exists())
    def test_manager_password_reset_and_plaintext_not_logged(self):
        password="NewSecurePass456!"; response=self.client.post(reverse("management_employee_password",args=[self.employee.pk]),{"new_password1":password,"new_password2":password})
        self.assertEqual(response.status_code,302); self.employee_user.refresh_from_db(); self.assertTrue(self.employee_user.check_password(password)); log=AuditLog.objects.get(action="employee.password_reset"); self.assertNotIn(password,str(log.old_values)+str(log.new_values)+log.description)
    def test_employee_can_change_own_password(self):
        self.client.force_login(self.employee_user); new="EmployeeNewPass789!"; response=self.client.post(reverse("profile_password"),{"old_password":"StrongPass123!","new_password1":new,"new_password2":new})
        self.assertEqual(response.status_code,302); self.employee_user.refresh_from_db(); self.assertTrue(self.employee_user.check_password(new))
