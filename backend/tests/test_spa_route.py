"""The SPA catch-all must only ever serve files from the frontend build."""
from app.main import spa_file


def _build(tmp_path):
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("shell")
    (dist / "logo.png").write_text("png")
    (tmp_path / "secret.txt").write_text("nope")
    return dist


def test_serves_build_files(tmp_path):
    dist = _build(tmp_path)
    assert spa_file(dist, "logo.png") == (dist / "logo.png").resolve()


def test_unknown_paths_get_the_shell(tmp_path):
    dist = _build(tmp_path)
    assert spa_file(dist, "dashboard/sales").name == "index.html"


def test_traversal_and_absolute_paths_get_the_shell(tmp_path):
    dist = _build(tmp_path)
    for path in ("../../secret.txt", "/etc/passwd", "//etc/passwd",
                 "/proc/self/environ", str(tmp_path / "secret.txt")):
        assert spa_file(dist, path) == dist.resolve() / "index.html", path


def test_symlink_out_of_the_build_is_refused(tmp_path):
    dist = _build(tmp_path)
    (dist / "link.txt").symlink_to(tmp_path / "secret.txt")
    assert spa_file(dist, "link.txt").name == "index.html"
