from django.conf import settings


def site(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SHORT_DOMAIN": settings.SHORT_DOMAIN,
        "SITE_URL": settings.SITE_URL,
    }
