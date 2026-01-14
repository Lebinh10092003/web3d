from __future__ import annotations

from django.contrib.auth.models import Group

from .models import User


ROLE_GROUP_NAME_BY_ROLE: dict[str, str] = {
    User.Role.STUDENT: "Student",
    User.Role.TEACHER: "Teacher",
    User.Role.PARENT: "Parent",
}
ROLE_GROUP_NAMES = set(ROLE_GROUP_NAME_BY_ROLE.values())
ROLE_BY_GROUP_NAME: dict[str, str] = {
    group_name: role for role, group_name in ROLE_GROUP_NAME_BY_ROLE.items()
}

INTERNAL_STUDENT_GROUP_NAME = "Student nội bộ"


def _groups(using: str | None = None):
    return Group.objects.using(using) if using else Group.objects


def ensure_default_groups(*, using: str | None = None) -> dict[str, Group]:
    qs = _groups(using)
    groups: dict[str, Group] = {}
    for name in [*ROLE_GROUP_NAME_BY_ROLE.values(), INTERNAL_STUDENT_GROUP_NAME]:
        group, _created = qs.get_or_create(name=name)
        groups[name] = group
    return groups


def _preferred_role_group_name(role_group_names: set[str], *, preferred_role: str | None = None):
    if preferred_role:
        expected = ROLE_GROUP_NAME_BY_ROLE.get(preferred_role)
        if expected and expected in role_group_names:
            return expected
    for role in (User.Role.STUDENT, User.Role.TEACHER, User.Role.PARENT):
        name = ROLE_GROUP_NAME_BY_ROLE.get(role)
        if name and name in role_group_names:
            return name
    return None


def sync_user_role_from_groups(
    user: User,
    *,
    using: str | None = None,
    add_missing_group_from_role: bool = True,
) -> None:
    if not getattr(user, "pk", None):
        return

    ensure_default_groups(using=using)
    user_groups = user.groups.using(using) if using else user.groups
    role_group_names = set(
        user_groups.filter(name__in=ROLE_GROUP_NAMES).values_list("name", flat=True)
    )

    chosen_group_name = _preferred_role_group_name(
        role_group_names, preferred_role=(user.role or "").strip() or None
    )
    if not chosen_group_name and add_missing_group_from_role:
        expected = ROLE_GROUP_NAME_BY_ROLE.get((user.role or "").strip() or "")
        if expected:
            user_groups.add(_groups(using).get(name=expected))
            chosen_group_name = expected
            role_group_names.add(expected)

    if chosen_group_name:
        other_group_names = ROLE_GROUP_NAMES - {chosen_group_name}
        if other_group_names:
            user_groups.remove(*_groups(using).filter(name__in=other_group_names))
        expected_role = ROLE_BY_GROUP_NAME.get(chosen_group_name, "")
        if user.role != expected_role:
            user.role = expected_role
            user.save(update_fields=["role"])
    else:
        if user.role:
            user.role = ""
            user.save(update_fields=["role"])


def sync_user_role_group(user: User, *, using: str | None = None) -> None:
    if not getattr(user, "pk", None):
        return

    role = (user.role or "").strip()
    role_group_name = ROLE_GROUP_NAME_BY_ROLE.get(role)
    if not role_group_name:
        return

    groups = ensure_default_groups(using=using)
    expected_group = groups[role_group_name]

    user_groups = user.groups.using(using) if using else user.groups
    other_group_names = ROLE_GROUP_NAMES - {role_group_name}
    if other_group_names:
        user_groups.remove(*_groups(using).filter(name__in=other_group_names))

    user_groups.add(expected_group)
