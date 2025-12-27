from django.contrib.admin import AdminSite
from django.utils.translation import gettext_lazy as _


class Web3dAdminSite(AdminSite):
    site_header = _("Web3D Admin")
    site_title = _("Web3D Admin")
    index_title = _("Management")
    site_url = "/"
    enable_nav_sidebar = True
