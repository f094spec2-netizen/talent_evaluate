import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.agents.collection import collect
from app.database import Base, Batch, Receipt, SourceFile
from app.queue import claim, enqueue
from app.supervisor import finalize_collection


@pytest.fixture
def postgres_sessions():
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL to run PostgreSQL concurrency checks (enabled in CI)")
    # Every test owns a random isolated schema; no existing application tables are modified.
    schema = "test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def test_parallel_workers_claim_distinct_jobs(postgres_sessions):
    with postgres_sessions.begin() as session:
        for index in range(8):
            enqueue(session, f"synthetic:{index}", "collect", {})
    with ThreadPoolExecutor(max_workers=4) as pool:
        leases = list(pool.map(lambda _: claim(postgres_sessions, 300), range(8)))
    assert len({lease.id for lease in leases}) == 8
    assert claim(postgres_sessions, 300) is None


def test_concurrent_duplicate_versions(postgres_sessions, sample):
    with postgres_sessions.begin() as session:
        receipts = [
            Receipt(
                delivery_key=f"synthetic:{n}",
                company_code="DEMO",
                officer_code="OFFICER01",
                filename="DEMO_OFFICER01_weekly_2026-W35_v01.html",
                status="queued",
                sha256="a" * 64,
                object_key="raw/" + "b" * 32 + "/" + "a" * 64,
            )
            for n in range(2)
        ]
        session.add_all(receipts)
        session.flush()
        ids = [r.id for r in receipts]

    def finish(receipt_id):
        with postgres_sessions.begin() as session:
            receipt = session.get(Receipt, receipt_id)
            finalize_collection(session, receipt, collect(receipt.filename, sample))

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(finish, ids))
    with postgres_sessions() as session:
        assert sorted(session.scalars(select(Receipt.status)).all()) == ["duplicate", "normalized"]
        assert len(session.scalars(select(SourceFile)).all()) == 1
        assert session.scalar(select(Batch)).latest_version == 1
