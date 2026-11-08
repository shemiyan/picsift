-- PicSift 初始表结构。在 Supabase 后台 SQL Editor 里整段执行一次即可。
-- 数据流：前端插入 crawl_jobs（pending）→ worker 用 claim_job() 领取（running）
--        → 抓取、分析，缩略图进 Storage、元数据进 images → 回写任务状态（done/failed）
--        → 前端通过 Realtime 实时看到任务进度和新图片。

-- ============ 任务表 ============
create table public.crawl_jobs (
  id           bigint generated always as identity primary key,
  user_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
  seed_url     text not null check (seed_url ~ '^https?://'),
  max_images   int  not null default 30 check (max_images between 1 and 200),
  status       text not null default 'pending'
               check (status in ('pending', 'running', 'done', 'failed')),
  stats        jsonb not null default '{}'::jsonb,
  error        text,
  created_at   timestamptz not null default now(),
  started_at   timestamptz,
  finished_at  timestamptz
);

-- worker 只找 pending 的任务，用部分索引，任务表再大这个索引也很小
create index crawl_jobs_pending_idx on public.crawl_jobs (created_at) where status = 'pending';
create index crawl_jobs_user_idx on public.crawl_jobs (user_id, created_at desc);

-- ============ 图片表 ============
create table public.images (
  id           bigint generated always as identity primary key,
  job_id       bigint not null references public.crawl_jobs (id) on delete cascade,
  user_id      uuid   not null references auth.users (id) on delete cascade,
  source_url   text   not null,
  page_url     text   not null,
  thumb_path   text   not null,           -- Storage 里的缩略图路径；原图不存，链接回源站
  width        int    not null,
  height       int    not null,
  bytes        int    not null,
  format       text,
  dhash        bigint not null,            -- 64 位差值哈希（有符号存储）
  blur_score   real   not null,            -- 拉普拉斯方差，越大越清晰
  brightness   real   not null,            -- 0~1
  colors       jsonb  not null default '[]'::jsonb,
  dup_of       bigint references public.images (id) on delete set null,  -- 近似重复时指向该组第一张
  created_at   timestamptz not null default now(),
  unique (user_id, source_url)
);

create index images_job_idx on public.images (job_id);
create index images_user_created_idx on public.images (user_id, created_at desc);
create index images_dup_of_idx on public.images (dup_of) where dup_of is not null;

-- ============ 函数（只给 worker 用） ============
-- 找近似重复：汉明距离 = 两个哈希异或后 1 的个数。
-- 当前是按用户全表比较，几千张图没问题；数据量大了可以把哈希切成若干段建索引（多索引哈希）。
create or replace function public.similar_images(p_user uuid, p_hash bigint, p_max_dist int default 6)
returns table (id bigint, distance int)
language sql stable
set search_path = ''
as $$
  select i.id, bit_count((i.dhash # p_hash)::bit(64))::int as distance
  from public.images i
  where i.user_id = p_user
    and i.dup_of is null
    and bit_count((i.dhash # p_hash)::bit(64)) <= p_max_dist
  order by distance, i.id
  limit 5;
$$;

-- 领取任务：FOR UPDATE SKIP LOCKED 保证多个 worker 并发时不会领到同一个任务
create or replace function public.claim_job()
returns setof public.crawl_jobs
language sql volatile
set search_path = ''
as $$
  update public.crawl_jobs j
     set status = 'running', started_at = now()
   where j.id = (
         select c.id from public.crawl_jobs c
          where c.status = 'pending'
          order by c.created_at
          limit 1
          for update skip locked)
  returning j.*;
$$;

-- Supabase 会把 public 下的函数暴露成 RPC，收回前端角色的执行权限，只留 service_role
revoke execute on function public.similar_images(uuid, bigint, int) from public, anon, authenticated;
revoke execute on function public.claim_job() from public, anon, authenticated;
grant execute on function public.similar_images(uuid, bigint, int) to service_role;
grant execute on function public.claim_job() to service_role;

-- ============ 行级安全（RLS）：每个用户只能看到自己的数据 ============
alter table public.crawl_jobs enable row level security;
alter table public.images enable row level security;

create policy "jobs_select_own" on public.crawl_jobs
  for select to authenticated using (user_id = (select auth.uid()));
-- 前端只能新建 pending 任务，状态由 worker 改
create policy "jobs_insert_own" on public.crawl_jobs
  for insert to authenticated with check (user_id = (select auth.uid()) and status = 'pending');

create policy "images_select_own" on public.images
  for select to authenticated using (user_id = (select auth.uid()));
create policy "images_delete_own" on public.images
  for delete to authenticated using (user_id = (select auth.uid()));

-- ============ Realtime：前端订阅任务进度和新图片 ============
alter publication supabase_realtime add table public.crawl_jobs, public.images;

-- ============ Storage：私有桶，路径第一段是用户 id ============
insert into storage.buckets (id, name, public)
values ('thumbs', 'thumbs', false)
on conflict (id) do nothing;

create policy "thumbs_read_own" on storage.objects
  for select to authenticated
  using (bucket_id = 'thumbs' and (storage.foldername(name))[1] = (select auth.uid())::text);
