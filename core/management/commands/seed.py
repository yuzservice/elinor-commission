from datetime import timedelta
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import *

class Command(BaseCommand):
    help = "ایجاد داده‌های اولیه و کاربران نمونه (قابل اجرای مجدد)"
    def handle(self, *args, **opts):
        levels={c:CommissionLevel.objects.update_or_create(code=c,defaults={"performance_rate":p,"violation_rate":v})[0] for c,p,v in [("A",1400,6000),("B",1000,4000),("C",650,4000),("D",500,4000)]}
        depts={name:Department.objects.get_or_create(name=name)[0] for name in ["لاین وسط","شلوار","اکسسوری","شال","صندوق","انبار","پرو"]}
        dept=depts["لاین وسط"]
        users=[("manager","مدیر","سیستم","MANAGER","A","E000","09110000000"),("supervisor","سرپرست","لاین وسط","MANAGER","A","E010","09110000010"),("fatemeh","فاطمه","ظاهری","EMPLOYEE","A","E001","09110000001"),("mahsa","مهسا","غفوری","EMPLOYEE","A","E002","09110000002"),("maryam","مریم","قلی نژاد","EMPLOYEE","C","E003","09110000003")]
        employees={}
        for username,first,last,role,level,code,mobile in users:
            user,created=User.objects.get_or_create(username=username,defaults={"first_name":first,"last_name":last,"is_staff":role=="MANAGER","is_active":True})
            if created:
                user.set_password("Elinor123!"); user.save()
            emp,emp_created=Employee.objects.get_or_create(user=user,defaults={"employee_code":code,"first_name":first,"last_name":last,"mobile":mobile,"role":role,"commission_level":levels[level],"primary_department":dept,"is_active":True})
            if emp_created: emp.departments.add(dept)
            user.is_staff=emp.role==Employee.Role.MANAGER; user.is_active=emp.is_active; user.save(update_fields=["is_staff","is_active"])
            employees[username]=emp
        category_specs=[("MAIN_PERFORMANCE","عملکرد اصلی",10),("OPERATIONAL_TASK","وظیفه عملیاتی",20),("DAILY_CHECKLIST","چک‌لیست روزانه",30),("OCCASIONAL_TASK","فعالیت موردی",40),("KPI_ONLY","شاخص بدون اثر مستقیم روی پورسانت",50)]
        categories={code:ActivityCategory.objects.get_or_create(code=code,defaults={"title":title,"sort_order":order})[0] for code,title,order in category_specs}
        types=[
            ("M01","فروش فردی","MAIN_PERFORMANCE",ActivityType.ScoringMethod.DIRECT_VALUE,1,1,"تعداد",True),
            ("M02","شلوار","KPI_ONLY",ActivityType.ScoringMethod.DIRECT_VALUE,1,1,"تعداد",False),
            ("M03","اکسسوری","KPI_ONLY",ActivityType.ScoringMethod.DIRECT_VALUE,1,1,"تعداد",False),
            ("M04","انبارگردانی","OPERATIONAL_TASK",ActivityType.ScoringMethod.FIXED,10,1,"مرتبه",True),
            ("M05","ثبت اکسل","OPERATIONAL_TASK",ActivityType.ScoringMethod.FIXED,10,1,"مرتبه",True),
            ("M06","نظافت و مرتب‌سازی","DAILY_CHECKLIST",ActivityType.ScoringMethod.FIXED,5,1,"بدون واحد",True),
            ("M07","کمک به انبار","OCCASIONAL_TASK",ActivityType.ScoringMethod.QUANTITY_MULTIPLIER,1,2,"تعداد",True),
        ]
        activity_types=[]
        for code,title,cat,method,score,multiplier,unit,commission in types:
            item,created=ActivityType.objects.get_or_create(code=code,defaults={"title":title,"category":categories[cat],"scoring_method":method,"score_value":score,"multiplier":multiplier,"unit":unit,"is_commission_eligible":commission,"requires_manager_approval":True,"recurrence_type":ActivityType.RecurrenceType.OCCASIONAL,"active":True})
            if created or not item.all_departments: item.departments.add(dept)
            activity_types.append(item)
        rules=[("V01","استفاده از تلفن همراه در محیط کار",5,10,20),("V02","رفتار نامناسب با مشتری",5,10,20),("V03","صحبت با همکاران در حضور مشتری",3,6,12),("V04","رعایت نکردن پوشش سازمانی",2,4,8),("V05","ایجاد حاشیه با همکاران",2,4,8),("V06","توقف بیش از حد در بخش دیگر",2,4,8),("V07","تأخیر یا تعجیل بدون اطلاع",3,6,12),("V08","نظافت و مرتب‌سازی بخش",2,4,8)]
        for code,title,a,b,c in rules: ViolationRule.objects.update_or_create(code=code,defaults={"title":title,"first_points":a,"second_points":b,"third_points":c})
        for title,points,reward in [("تارگت ۱",1200,200000),("تارگت ۲",1450,350000),("تارگت ۳",1850,500000)]: Target.objects.update_or_create(title=title,defaults={"points":points,"reward":reward})
        SystemSettings.load()
        today=timezone.localdate(); submitter=employees["supervisor"].user
        if not Activity.objects.exists():
            samples=[("fatemeh",0,30),("fatemeh",3,1),("mahsa",0,42),("mahsa",4,1),("maryam",0,55),("maryam",1,18)]
            for uname,idx,qty in samples:
                kind=activity_types[idx]; score=kind.calculate_score(qty)
                item=Activity.objects.create(employee=employees[uname],activity_type=kind,activity_date=today-timedelta(days=idx),value=qty,definition_score_snapshot=kind.score_value,multiplier_snapshot=kind.multiplier,calculated_score=score,final_score=score,employee_note="داده نمونه اولیه",status=Activity.Status.APPROVED if idx%2==0 else Activity.Status.PENDING,submitted_by=submitter,submitted_at=timezone.now())
                ActivityStatusHistory.objects.create(activity=item,previous_status="",new_status=item.status,actor=submitter,note="داده نمونه اولیه")
        self.stdout.write(self.style.SUCCESS("Seed completed. Initial password for newly created development users: Elinor123! Existing passwords were not changed."))
