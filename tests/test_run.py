import datetime

import run

UTC = datetime.timezone.utc


def test_parse_state_reads_sequence_number():
    text = ("# original OSM minutely replication sequence number 7348838\n"
            "timestamp=2026-10-28T21\\:21\\:02Z\nsequenceNumber=3869\n")
    assert run.parse_state(text) == 3869
    assert run.parse_state("timestamp=x\n") is None


def _fake_extract(monkeypatch, tmp_path, local, remote):
    pbf = tmp_path / "gcc.osm.pbf"
    pbf.write_bytes(b"")
    monkeypatch.setattr(run, "PBF_PATH", str(pbf))
    monkeypatch.setattr(run, "replication_header", lambda path: (local, "https://example.org/updates/"))
    if isinstance(remote, Exception):
        def fail(url):
            raise remote
        monkeypatch.setattr(run, "remote_sequence", fail)
    else:
        monkeypatch.setattr(run, "remote_sequence", lambda url: remote)


def test_update_available_only_when_geofabrik_is_ahead(monkeypatch, tmp_path):
    _fake_extract(monkeypatch, tmp_path, 3868, 3869)
    assert run.update_available() is True
    _fake_extract(monkeypatch, tmp_path, 3869, 3869)
    assert run.update_available() is False


def test_update_available_falls_back_to_a_run_when_the_check_fails(monkeypatch, tmp_path):
    _fake_extract(monkeypatch, tmp_path, 3869, OSError("network down"))
    assert run.update_available() is True


def test_update_available_without_an_extract(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "PBF_PATH", str(tmp_path / "missing.pbf"))
    assert run.update_available() is True


def test_failed_run_is_retried_after_six_hours():
    now = datetime.datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    failed = {"last_result": "failed", "last_attempt": "2026-10-30T05:30:00+00:00"}
    assert run.failed_run_due(failed, now) is True
    recent = {"last_result": "failed", "last_attempt": "2026-10-30T09:00:00+00:00"}
    assert run.failed_run_due(recent, now) is False
    assert run.failed_run_due({"last_result": "no new data", "last_attempt": "2026-10-29T00:00:00+00:00"}, now) is False
    assert run.failed_run_due({}, now) is False
