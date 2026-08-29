from .models import SystemSettings

def system_settings(request):
    try:
        return {"system_settings": SystemSettings.load()}
    except Exception:
        return {"system_settings": None}
