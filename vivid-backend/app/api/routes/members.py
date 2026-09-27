"""Sharing a project with other people.

The owner invites by email; the invite is a single-use link, sent by email
(and shown to the owner to pass on some other way). Whoever opens it signed
in becomes an editor or a viewer. Editors build, hand-edit and publish on
the owner's plan; viewers read. Only the owner manages people.
"""
import html
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.routes.builder import _owned, _present, _writable
from app.core.config import settings
from app.core.errors import APIError
from app.db.models import BuilderInvite, BuilderMember, BuilderProject, User
from app.schemas.builder import (InviteOut, InvitePreviewOut, MemberInviteIn, MemberOut, MemberRoleIn,
                                 MembersOut, PersonOut, ProjectOut)
from app.services import mail, push

log = logging.getLogger("vivid.members")

router = APIRouter(prefix="/builder", tags=["builder-members"])


def _person(user: User | None, user_id: str) -> PersonOut:
    return PersonOut(user_id=user_id, name=user.name if user else None,
                     avatar_url=user.avatar_url if user else None)


def _expires(invite: BuilderInvite) -> datetime:
    created = invite.created_at if invite.created_at.tzinfo else invite.created_at.replace(tzinfo=timezone.utc)
    return created + timedelta(days=settings.BUILDER_INVITE_DAYS)


def _invite_url(invite: BuilderInvite) -> str:
    return f"{settings.WEB_BASE_URL.rstrip('/')}/invite/{invite.token}"


def _invite_out(invite: BuilderInvite, emailed: bool | None = None) -> InviteOut:
    return InviteOut(id=invite.id, email=invite.email, role=invite.role, created_at=invite.created_at,
                     expires_at=_expires(invite), url=_invite_url(invite), emailed=emailed)


@router.get("/projects/{project_id}/members", response_model=MembersOut)
async def list_members(project_id: str, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    project = await _owned(project_id, user, db, "viewer")
    owner = await db.get(User, project.owner_id)
    rows = (await db.execute(select(BuilderMember, User).join(User, User.id == BuilderMember.user_id)
                             .where(BuilderMember.project_id == project_id)
                             .order_by(BuilderMember.created_at))).all()
    members = [MemberOut(**_person(u, m.user_id).model_dump(), role=m.role, created_at=m.created_at)
               for m, u in rows if u.deleted_at is None]
    invites = []
    if project.role == "owner":
        now = datetime.now(timezone.utc)
        pending = (await db.execute(select(BuilderInvite).where(
            BuilderInvite.project_id == project_id, BuilderInvite.accepted_at.is_(None))
            .order_by(BuilderInvite.created_at))).scalars()
        invites = [_invite_out(i) for i in pending if _expires(i) > now]
    return MembersOut(owner=_person(owner, project.owner_id), members=members, invites=invites)


@router.post("/projects/{project_id}/members", response_model=InviteOut, status_code=201)
async def invite_member(project_id: str, body: MemberInviteIn, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Invite someone by email. Answers the invite with its link (`url`) and
    whether the email went out (`emailed`); inviting the same address again
    sends a fresh link and replaces the old one."""
    project = await _owned(project_id, user, db, "owner")
    email = body.email.strip().lower()
    if not mail.valid_address(email):
        raise APIError(400, "bad_email", "That doesn't look like an email address.")
    members = (await db.execute(select(func.count()).select_from(BuilderMember)
                                .where(BuilderMember.project_id == project_id))).scalar_one()
    pending = (await db.execute(select(func.count()).select_from(BuilderInvite).where(
        BuilderInvite.project_id == project_id, BuilderInvite.accepted_at.is_(None),
        BuilderInvite.email != email))).scalar_one()
    if members + pending >= settings.BUILDER_MAX_MEMBERS:
        raise APIError(409, "too_many_members",
                       f"A project can have {settings.BUILDER_MAX_MEMBERS} people. Remove someone first.")
    invite = (await db.execute(select(BuilderInvite).where(
        BuilderInvite.project_id == project_id, BuilderInvite.email == email))).scalar_one_or_none()
    if invite is None:
        invite = BuilderInvite(project_id=project_id, email=email)
        db.add(invite)
    invite.token = secrets.token_urlsafe(24)
    invite.role = body.role
    invite.invited_by = user.id
    invite.created_at = datetime.now(timezone.utc)
    invite.accepted_at = None
    await db.commit()

    inviter = user.name or "Someone"
    what = "build and edit" if body.role == "editor" else "see"
    text = (f"{inviter} invited you to {what} \"{project.name}\" on Vivid.\n\n"
            f"Open this link to join (it works once, for {settings.BUILDER_INVITE_DAYS} days):\n"
            f"{_invite_url(invite)}\n")
    page = mail.layout(f"{inviter} invited you to {project.name}",
                       f"<p>You're invited to {what} <b>{html.escape(project.name)}</b> on Vivid.</p>"
                       f"<p style=\"color:#6b6880;font-size:13px\">The link works once, for "
                       f"{settings.BUILDER_INVITE_DAYS} days.</p>",
                       ("Join the project", _invite_url(invite)))
    emailed = await mail.send(email, f"{inviter} invited you to {project.name} on Vivid", text, page)
    return _invite_out(invite, emailed)


@router.delete("/projects/{project_id}/invites/{invite_id}", status_code=204)
async def cancel_invite(project_id: str, invite_id: str, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db, "owner")
    invite = await db.get(BuilderInvite, invite_id)
    if invite is None or invite.project_id != project_id:
        raise APIError(404, "not_found", "No such invite")
    await db.delete(invite)
    await db.commit()
    return Response(status_code=204)


@router.patch("/projects/{project_id}/members/{member_id}", response_model=MemberOut)
async def change_role(project_id: str, member_id: str, body: MemberRoleIn,
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db, "owner")
    member = await db.get(BuilderMember, (project_id, member_id))
    if member is None:
        raise APIError(404, "not_found", "Not a member of this project")
    member.role = body.role
    await db.commit()
    return MemberOut(**_person(await db.get(User, member_id), member_id).model_dump(),
                     role=member.role, created_at=member.created_at)


@router.delete("/projects/{project_id}/members/{member_id}", status_code=204)
async def remove_member(project_id: str, member_id: str, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """The owner removes anyone; a member may remove themselves (leave)."""
    await _owned(project_id, user, db, "owner" if member_id != user.id else "viewer")
    member = await db.get(BuilderMember, (project_id, member_id))
    if member is None:
        raise APIError(404, "not_found", "Not a member of this project")
    await db.delete(member)
    await db.commit()
    return Response(status_code=204)


async def _invite_by_token(token: str, db: AsyncSession) -> BuilderInvite:
    invite = (await db.execute(select(BuilderInvite).where(BuilderInvite.token == token))).scalar_one_or_none()
    if invite is None:
        raise APIError(404, "not_found", "This invite link is not valid. Ask for a new one.")
    return invite


@router.get("/invites/{token}", response_model=InvitePreviewOut)
async def preview_invite(token: str, db: AsyncSession = Depends(get_db)):
    """What the invite page shows before sign-in: whose project, which role."""
    invite = await _invite_by_token(token, db)
    project = await db.get(BuilderProject, invite.project_id)
    inviter = await db.get(User, invite.invited_by) if invite.invited_by else None
    status = ("used" if invite.accepted_at else
              "expired" if _expires(invite) <= datetime.now(timezone.utc) else "ok")
    return InvitePreviewOut(project_name=project.name, inviter=inviter.name if inviter else None,
                            role=invite.role, status=status)


@router.post("/invites/{token}/accept", response_model=ProjectOut)
async def accept_invite(token: str, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Join the project. 410 once used or expired; the owner opening their
    own link just gets the project."""
    invite = await _invite_by_token(token, db)
    project = await db.get(BuilderProject, invite.project_id)
    if project.owner_id != user.id:
        if invite.accepted_at or _expires(invite) <= datetime.now(timezone.utc):
            raise APIError(410, "invite_gone", "This invite was already used or has expired. Ask for a new one.")
        member = await db.get(BuilderMember, (project.id, user.id))
        if member is None:
            db.add(BuilderMember(project_id=project.id, user_id=user.id, role=invite.role,
                                 invited_by=invite.invited_by))
        elif invite.role == "editor":
            member.role = "editor"
        invite.accepted_at = datetime.now(timezone.utc)
        await db.commit()
        push.send_later(project.owner_id, project.name,
                        f"{user.name or 'Someone'} joined as {'an editor' if invite.role == 'editor' else 'a viewer'}.",
                        {"type": "project_member", "project_id": project.id})
    project = await _owned(project.id, user, db, "viewer")
    return _present(project, await _writable(db, project.owner_id))
