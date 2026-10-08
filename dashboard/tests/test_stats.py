"""Per-world CPU/RAM from Docker stats."""

from conftest import post

from mcdash.containers import parse_stats


def test_world_page_shows_stats_while_running(logged_in):
    post(logged_in, "/worlds", {"name": "survival"})
    assert "200.0" not in logged_in.get("/worlds/survival").get_data(as_text=True)
    post(logged_in, "/worlds/survival/start")
    page = logged_in.get("/worlds/survival").get_data(as_text=True)
    assert "200.0<small>%</small>" in page
    assert "1.5 <small>GB of 16.0</small>" in page


def test_no_stats_when_stopped(logged_in, app):
    post(logged_in, "/worlds", {"name": "survival"})
    post(logged_in, "/worlds/survival/start")
    post(logged_in, "/worlds/survival/stop")
    assert app.extensions["worlds"].containers.stats("survival") is None


def test_no_stats_when_docker_unreachable(app):
    from docker.errors import DockerException

    def broken():
        raise DockerException("socket missing")

    containers = app.extensions["worlds"].containers
    containers._client_factory = broken
    assert containers.stats("survival") is None


def test_parse_stats_cgroup_v1():
    raw = {
        "cpu_stats": {"cpu_usage": {"total_usage": 500, "percpu_usage": [250, 250]}, "system_cpu_usage": 2000},
        "precpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 0},
        "memory_stats": {"usage": 1000, "limit": 4000, "stats": {"total_inactive_file": 200}},
    }
    assert parse_stats(raw) == {"cpu_percent": 50.0, "memory_bytes": 800, "memory_limit_bytes": 4000}


def test_parse_stats_first_sample_and_partial():
    # The very first sample has an empty precpu_stats.
    raw = {
        "cpu_stats": {"cpu_usage": {"total_usage": 500}, "online_cpus": 2},
        "precpu_stats": {},
        "memory_stats": {"usage": 1000, "limit": 4000},
    }
    assert parse_stats(raw)["cpu_percent"] == 0.0
    assert parse_stats({"cpu_stats": {}, "memory_stats": {}}) is None
