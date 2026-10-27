-- All issuance transactions must UPDATE this single row first, which
-- serializes project-slot decisions on SQLite and transactional SQL backends.
create table if not exists worker_lease_serialization (
  id integer primary key,
  generation integer not null
);
insert into worker_lease_serialization (id, generation)
select 1, 0 where not exists (
  select 1 from worker_lease_serialization where id = 1
);
