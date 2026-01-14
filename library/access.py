from __future__ import annotations

from django.db.models import Q, QuerySet

from .models import ContentItem


def filter_content_queryset_for_user(queryset: QuerySet[ContentItem], user) -> QuerySet[ContentItem]:
    if user.is_authenticated and (user.is_staff or user.is_superuser):
        return queryset

    access_q = Q(allowed_groups__isnull=True)
    if user.is_authenticated:
        group_ids = list(user.groups.values_list("id", flat=True))
        if group_ids:
            access_q |= Q(allowed_groups__in=group_ids)
        access_q |= Q(owner_id=user.id)

    return queryset.filter(access_q).distinct()


def user_can_access_content(user, content: ContentItem) -> bool:
    if not content:
        return False
    if user.is_authenticated and (user.is_staff or user.is_superuser):
        return True
    if user.is_authenticated and content.owner_id == user.id:
        return True
    if not content.allowed_groups.exists():
        return True
    if not user.is_authenticated:
        return False
    return user.groups.filter(id__in=content.allowed_groups.values("id")).exists()

