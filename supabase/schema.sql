-- The sync store (see sync.py). Paste into the Supabase dashboard's SQL Editor and run;
-- running it again is harmless.
--
-- One row per synced record, per account. Row-level security limits every account to its
-- own rows, which is what makes it safe for the app to ship the publishable key.
-- seq numbers every write, so a device pulls "everything after the last seq I saw".
-- ponytail: seq comes from a sequence, so two pushes committing out of order could hide one from a pull running between them; fine for one person's devices

create sequence if not exists public.records_seq;

create table if not exists public.records (
    user_id uuid not null default auth.uid() references auth.users on delete cascade,
    tbl text not null,
    uid text not null,
    updated_at text not null,
    deleted boolean not null default false,
    data jsonb,
    seq bigint not null,
    primary key (user_id, tbl, uid)
);
create index if not exists records_pull on public.records (user_id, seq);

alter table public.records enable row level security;
drop policy if exists "own records" on public.records;
create policy "own records" on public.records for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

revoke all on public.records from anon;
grant select, insert, update on public.records to authenticated;
grant usage on sequence public.records_seq to authenticated;

-- Stores records, keeping whichever version of each row is newest
create or replace function public.push_records(records jsonb) returns void
language sql security invoker set search_path = '' as $$
    insert into public.records (user_id, tbl, uid, updated_at, deleted, data, seq)
    select auth.uid(), r->>'tbl', r->>'uid', r->>'updated_at', (r->>'deleted')::boolean, r->'data',
           nextval('public.records_seq')
    from jsonb_array_elements(records) r
    on conflict (user_id, tbl, uid) do update
        set updated_at = excluded.updated_at, deleted = excluded.deleted, data = excluded.data, seq = excluded.seq
        where excluded.updated_at > public.records.updated_at;
$$;
revoke execute on function public.push_records(jsonb) from public, anon;
grant execute on function public.push_records(jsonb) to authenticated;
