from django.contrib.admin.apps import AdminConfig


class Web3dAdminConfig(AdminConfig):
    default_site = "web3d.admin_site.Web3dAdminSite"
