import shutil
import socket
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection


def _has_value(value):
    text = str(value or "").strip()
    if not text:
        return False
    return "CHANGE_ME" not in text and "XXXXXXXXX" not in text


class Command(BaseCommand):
    help = "Report local integration readiness for chat, blog automation, and OpenClaw."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=float,
            default=1.5,
            help="Socket timeout in seconds for gateway reachability checks.",
        )

    def handle(self, *args, **options):
        timeout = max(0.2, float(options["timeout"]))
        rows = []

        try:
            connection.ensure_connection()
            rows.append(("OK", "Database", connection.settings_dict.get("NAME", "")))
        except Exception as exc:
            rows.append(("FAIL", "Database", str(exc)))

        user_model = get_user_model()
        admin_exists = user_model.objects.filter(username="admin", is_superuser=True).exists()
        rows.append(("OK" if admin_exists else "WARN", "Admin user", "admin" if admin_exists else "Missing"))

        rows.append(
            (
                "OK" if settings.SUPPORT_CHAT_ENABLED else "WARN",
                "Support chat feature",
                f"enabled={settings.SUPPORT_CHAT_ENABLED}",
            )
        )
        rows.append(
            (
                "OK" if settings.BLOG_AUTOMATION_ENABLED else "WARN",
                "Blog automation feature",
                f"enabled={settings.BLOG_AUTOMATION_ENABLED}",
            )
        )

        rows.append(
            (
                "OK" if _has_value(settings.SUPPORT_CHAT_OPERATOR_TOKEN) else "WARN",
                "Support chat operator token",
                "configured" if _has_value(settings.SUPPORT_CHAT_OPERATOR_TOKEN) else "missing",
            )
        )
        rows.append(
            (
                "OK" if _has_value(settings.BLOG_AUTOMATION_TOKEN) else "WARN",
                "Blog automation token",
                "configured" if _has_value(settings.BLOG_AUTOMATION_TOKEN) else "missing",
            )
        )
        rows.append(
            (
                "OK" if _has_value(settings.SUPPORT_CHAT_OPENCLAW_HOOK_TOKEN) else "WARN",
                "OpenClaw hook token",
                "configured" if _has_value(settings.SUPPORT_CHAT_OPENCLAW_HOOK_TOKEN) else "missing",
            )
        )
        rows.append(
            (
                "OK" if _has_value(settings.SUPPORT_CHAT_OWNER_WHATSAPP) else "WARN",
                "WhatsApp owner number",
                settings.SUPPORT_CHAT_OWNER_WHATSAPP or "missing",
            )
        )

        author_username = str(settings.BLOG_AUTOMATION_DEFAULT_AUTHOR_USERNAME or "").strip()
        if author_username:
            author_exists = user_model.objects.filter(username=author_username).exists()
            rows.append(
                (
                    "OK" if author_exists else "WARN",
                    "Blog automation default author",
                    author_username if author_exists else f"{author_username} (not found)",
                )
            )
        else:
            rows.append(("WARN", "Blog automation default author", "missing"))

        openclaw_cli = shutil.which("openclaw")
        rows.append(("OK" if openclaw_cli else "WARN", "OpenClaw CLI", openclaw_cli or "not installed"))

        node_cli = shutil.which("node")
        rows.append(("OK" if node_cli else "WARN", "Node.js", node_cli or "not installed"))

        workspace_files = [
            settings.BASE_DIR / "openclaw" / "workspace-main" / "AGENTS.md",
            settings.BASE_DIR / "openclaw" / "workspace-main" / "WHATSAPP_COMMANDS.md",
        ]
        missing_workspace = [str(path.name) for path in workspace_files if not path.exists()]
        rows.append(
            (
                "OK" if not missing_workspace else "WARN",
                "OpenClaw workspace docs",
                "ready" if not missing_workspace else f"missing: {', '.join(missing_workspace)}",
            )
        )

        base_url = str(settings.SUPPORT_CHAT_OPENCLAW_BASE_URL or "").strip()
        if base_url:
            parsed = urlsplit(base_url)
            host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    rows.append(("OK", "OpenClaw gateway reachability", f"{host}:{port}"))
            except Exception as exc:
                rows.append(("WARN", "OpenClaw gateway reachability", f"{host}:{port} ({exc})"))
        else:
            rows.append(("WARN", "OpenClaw gateway reachability", "missing base URL"))

        self.stdout.write("")
        self.stdout.write("Integration Status")
        for level, label, detail in rows:
            if level == "OK":
                prefix = self.style.SUCCESS("OK  ")
            elif level == "FAIL":
                prefix = self.style.ERROR("FAIL")
            else:
                prefix = self.style.WARNING("WARN")
            self.stdout.write(f"{prefix} {label}: {detail}")

        missing_actions = []
        if not openclaw_cli:
            missing_actions.append("Install OpenClaw CLI/gateway on this machine.")
        if not _has_value(settings.SUPPORT_CHAT_OPENCLAW_HOOK_TOKEN):
            missing_actions.append("Fill SUPPORT_CHAT_OPENCLAW_HOOK_TOKEN in .env_local.")
        if not _has_value(settings.SUPPORT_CHAT_OWNER_WHATSAPP):
            missing_actions.append("Fill SUPPORT_CHAT_OWNER_WHATSAPP with the operator number.")
        if not author_username:
            missing_actions.append("Set BLOG_AUTOMATION_DEFAULT_AUTHOR_USERNAME.")

        self.stdout.write("")
        if missing_actions:
            self.stdout.write("Next Actions")
            for item in missing_actions:
                self.stdout.write(f"- {item}")
        else:
            self.stdout.write(self.style.SUCCESS("No obvious configuration gaps detected."))
