-- ============================================================
-- LOST & FOUND  —  Full Supabase Database Schema
-- Run this in the Supabase SQL Editor to create all tables.
-- ============================================================

-- 1) USERS TABLE
create table if not exists public.users (
  id          text primary key,
  name        text not null,
  email       text not null unique,
  password    text not null,
  is_admin    boolean not null default false,
  points      integer not null default 0,
  created_at  timestamptz not null default now()
);

-- 2) ITEMS TABLE
create table if not exists public.items (
  id                            text primary key,
  title                         text not null,
  category                      text not null default '',
  location                      text not null default '',
  date_found                    text not null default '',
  description                   text not null default '',
  status                        text not null default 'found',
  image                         text,
  reported_by_id                text not null default '',
  reported_by_name              text not null default '',
  reported_by_email             text not null default '',
  date_submitted                text not null default '',
  submitted_to                  text not null default 'self',
  submitted_department          text not null default '',
  holder_contact                text not null default '',
  department_verification_status text not null default 'not_required',
  department_verified_by        text not null default '',
  department_verified_at        text not null default '',
  claim_status                  text not null default 'none',
  claim_requested_by            text not null default '',
  claim_requested_at            text not null default '',
  claim_description             text not null default '',
  claim_reviewed_by             text not null default '',
  claim_reviewed_at             text not null default '',
  claim_review_notes            text not null default '',
  created_at                    timestamptz not null default now()
);

-- 3) EMAIL SETTINGS TABLE (single-row config)
create table if not exists public.email_settings (
  id        text primary key default 'main',
  sender    text not null default '',
  password  text not null default '',
  enabled   boolean not null default false
);

-- Seed the email settings row so upserts always work
insert into public.email_settings (id) values ('main')
on conflict (id) do nothing;

-- 4) Enable Row Level Security (but allow all for service-role key)
alter table public.users enable row level security;
alter table public.items enable row level security;
alter table public.email_settings enable row level security;

-- Allow full access via service-role key (used by the Flask backend)
create policy "Service role full access" on public.users
  for all using (true) with check (true);

create policy "Service role full access" on public.items
  for all using (true) with check (true);

create policy "Service role full access" on public.email_settings
  for all using (true) with check (true);

