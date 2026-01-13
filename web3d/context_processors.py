from django.conf import settings
from django.templatetags.static import static
from django.utils.translation import gettext as _


def adsense(request):
    return {
        "ADSENSE_CLIENT": getattr(settings, "ADSENSE_CLIENT", ""),
        "ADSENSE_SLOT_HOME": getattr(settings, "ADSENSE_SLOT_HOME", ""),
        "ADSENSE_SLOT_DETAIL": getattr(settings, "ADSENSE_SLOT_DETAIL", ""),
        "ADSENSE_SLOT_PAGE": getattr(settings, "ADSENSE_SLOT_PAGE", ""),
    }


def site_meta(request):
    site_name = getattr(settings, "SITE_NAME", "V+ STEAM LAB Library")
    site_url = getattr(settings, "SITE_URL", "")
    if not site_url:
        site_url = f"{request.scheme}://{request.get_host()}"
    base_url = site_url.rstrip("/")
    return {
        "SITE_NAME": site_name,
        "SITE_URL": base_url,
        "LEGO_THREE_BASE_URL": getattr(settings, "LEGO_THREE_BASE_URL", ""),
        "BLOCKLY_QUIZ_BLOCKLY_JS_URL": getattr(settings, "BLOCKLY_QUIZ_BLOCKLY_JS_URL", ""),
        "BLOCKLY_QUIZ_BLOCKLY_JS_URLS": getattr(settings, "BLOCKLY_QUIZ_BLOCKLY_JS_URLS", []),
        "BLOCKLY_QUIZ_BLOCKLY_MEDIA_URL": getattr(settings, "BLOCKLY_QUIZ_BLOCKLY_MEDIA_URL", ""),
        "BLOCKLY_QUIZ_SCRATCHBLOCKS_JS_URL": getattr(
            settings, "BLOCKLY_QUIZ_SCRATCHBLOCKS_JS_URL", ""
        ),
        "DEFAULT_META_TITLE": _("%(site)s | V for tech, V for future")
        % {"site": site_name},
        "DEFAULT_META_DESCRIPTION": _(
            "V+ STEAM LAB Library is a learning resource library from Vietnam. "
            "V for tech, V for future. "
            "Share and discover lessons, PDFs, and 3D LEGO builds for robotics competitions."
        ),
        "DEFAULT_OG_IMAGE": f"{base_url}{static('img/logoV+.png')}",
    }
