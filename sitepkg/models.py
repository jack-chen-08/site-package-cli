"""一期最小表结构的 SQLAlchemy 2.0 ORM 映射（与 sitepkg/ddl.sql 一一对应）。

说明：这些表代表「一期已存在」的表，本单只做最小字段建模，
apply 通过 ORM 写入，plan 通过只读事务比对。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有一期表的基类。"""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class Site(Base, TimestampMixin):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("org_code", "site_code", name="uq_sites_org_code_site_code"),)

    id: Mapped[uuid.UUID] = _pk()
    org_code: Mapped[str] = mapped_column(Text, nullable=False)
    site_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="Asia/Shanghai")
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="zh-CN")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    contact: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    branding: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    package_version: Mapped[str | None] = mapped_column(Text, nullable=True)


class Space(Base, TimestampMixin):
    __tablename__ = "spaces"
    __table_args__ = (UniqueConstraint("site_id", "space_code", name="uq_spaces_site_id_space_code"),)

    id: Mapped[uuid.UUID] = _pk()
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    space_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    reservation_rule_code: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class RoleBinding(Base, TimestampMixin):
    __tablename__ = "role_bindings"
    __table_args__ = (
        UniqueConstraint(
            "site_id", "role_code", "permission_template_code", name="uq_role_bindings_site_role_pt"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    role_code: Mapped[str] = mapped_column(Text, nullable=False)
    role_name: Mapped[str] = mapped_column(Text, nullable=False)
    permission_template_code: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, server_default="site")


class SopTemplateEnable(Base, TimestampMixin):
    __tablename__ = "sop_template_enables"
    __table_args__ = (
        UniqueConstraint(
            "site_id", "template_code", "template_version",
            name="uq_sop_template_enables_site_code_ver",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    template_code: Mapped[str] = mapped_column(Text, nullable=False)
    template_version: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default="all")


class KbScope(Base, TimestampMixin):
    __tablename__ = "kb_scopes"
    __table_args__ = (UniqueConstraint("site_id", "kb_code", name="uq_kb_scopes_site_id_kb_code"),)

    id: Mapped[uuid.UUID] = _pk()
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    kb_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default="site")
    space_codes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class PriceBookItem(Base, TimestampMixin):
    __tablename__ = "price_book"
    __table_args__ = (UniqueConstraint("site_id", "item_code", name="uq_price_book_site_id_item_code"),)

    id: Mapped[uuid.UUID] = _pk()
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    item_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit_amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="CNY")
    billing_period: Mapped[str] = mapped_column(Text, nullable=False, server_default="month")
    tax_included: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class MiniappConfig(Base, TimestampMixin):
    __tablename__ = "miniapp_config"

    id: Mapped[uuid.UUID] = _pk()
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    app_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    entry_path: Mapped[str] = mapped_column(Text, nullable=False)
    theme_color: Mapped[str] = mapped_column(Text, nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class AppliedPackage(Base, TimestampMixin):
    __tablename__ = "applied_packages"
    __table_args__ = (
        UniqueConstraint(
            "site_code", "package_version", name="uq_applied_packages_site_code_version"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    org_code: Mapped[str] = mapped_column(Text, nullable=False)
    site_code: Mapped[str] = mapped_column(Text, nullable=False)
    package_version: Mapped[str] = mapped_column(Text, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "Base",
    "Site",
    "Space",
    "RoleBinding",
    "SopTemplateEnable",
    "KbScope",
    "PriceBookItem",
    "MiniappConfig",
    "AppliedPackage",
]
