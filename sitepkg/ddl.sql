-- 会员空间平台 —— 配置包 CLI 依赖的一期「最小表结构」（虚构示例）
-- 说明：本文件仅代表一期已存在的表，用于在临时库中复现 apply/plan 的对接点。
--       所有表统一含 id(UUID) / created_at / updated_at。

CREATE TABLE IF NOT EXISTS sites (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_code        text NOT NULL,
    site_code       text NOT NULL,
    name            text NOT NULL,
    timezone        text NOT NULL DEFAULT 'Asia/Shanghai',
    locale          text NOT NULL DEFAULT 'zh-CN',
    status          text NOT NULL DEFAULT 'active',
    contact         jsonb NOT NULL DEFAULT '{}'::jsonb,
    branding        jsonb NOT NULL DEFAULT '{}'::jsonb,
    package_version text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_sites_org_code_site_code UNIQUE (org_code, site_code)
);

CREATE TABLE IF NOT EXISTS spaces (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id               uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    space_code            text NOT NULL,
    name                  text NOT NULL,
    capacity              integer NOT NULL DEFAULT 1 CHECK (capacity > 0),
    reservation_rule_code text NOT NULL,
    enabled               boolean NOT NULL DEFAULT true,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_spaces_site_id_space_code UNIQUE (site_id, space_code)
);

CREATE TABLE IF NOT EXISTS role_bindings (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id                  uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    role_code                text NOT NULL,
    role_name                text NOT NULL,
    permission_template_code text NOT NULL,
    scope                    text NOT NULL DEFAULT 'site',
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_role_bindings_site_role_pt UNIQUE (site_id, role_code, permission_template_code)
);

CREATE TABLE IF NOT EXISTS sop_template_enables (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id          uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    template_code    text NOT NULL,
    template_version text NOT NULL,
    enabled          boolean NOT NULL DEFAULT true,
    channel          text NOT NULL DEFAULT 'all',
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_sop_template_enables_site_code_ver UNIQUE (site_id, template_code, template_version)
);

CREATE TABLE IF NOT EXISTS kb_scopes (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id      uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    kb_code      text NOT NULL,
    name         text NOT NULL,
    visibility   text NOT NULL DEFAULT 'site',
    space_codes  jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_kb_scopes_site_id_kb_code UNIQUE (site_id, kb_code)
);

CREATE TABLE IF NOT EXISTS price_book (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id          uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    item_code        text NOT NULL,
    name             text NOT NULL,
    unit_amount_fen  bigint NOT NULL CHECK (unit_amount_fen >= 0),
    currency         text NOT NULL DEFAULT 'CNY',
    billing_period   text NOT NULL DEFAULT 'month',
    tax_included     boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_price_book_site_id_item_code UNIQUE (site_id, item_code)
);

CREATE TABLE IF NOT EXISTS miniapp_config (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id     uuid NOT NULL UNIQUE REFERENCES sites(id) ON DELETE CASCADE,
    app_id      text NOT NULL,
    name        text NOT NULL,
    entry_path  text NOT NULL,
    theme_color text NOT NULL,
    features    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS applied_packages (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_code        text NOT NULL,
    site_code       text NOT NULL,
    package_version text NOT NULL,
    payload_digest  text NOT NULL,
    applied_at      timestamptz NOT NULL DEFAULT now(),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_applied_packages_site_code_version UNIQUE (site_code, package_version)
);

CREATE INDEX IF NOT EXISTS ix_applied_packages_site_code ON applied_packages (site_code);
