from vibeplay.desktop.release_gate import run_release_gate_checks, validate_loopback_host


def test_validate_loopback_host():
    assert validate_loopback_host("127.0.0.1") is True
    assert validate_loopback_host("localhost") is True
    assert validate_loopback_host("::1") is True
    assert validate_loopback_host("0.0.0.0") is False
    assert validate_loopback_host("192.168.1.1") is False
    assert validate_loopback_host("example.com") is False


def test_run_release_gate_checks_basic(tmp_path):
    report = run_release_gate_checks(db_path=tmp_path / "mock.db", settings_path=tmp_path / "mock.json")
    assert report.passed is True
    assert len(report.checks) >= 1
    assert report.checks[0].name == "Loopback Security Invariant"
    assert report.checks[0].passed is True


def test_run_release_gate_checks_settings(tmp_path):
    settings_path = tmp_path / "test_settings.json"
    report = run_release_gate_checks(db_path=tmp_path / "mock.db", settings_path=settings_path)

    # Verify both checks passed
    assert report.passed is True
    assert len(report.checks) >= 2
    assert report.checks[1].name == "Settings Persistence & Permissions"
    assert report.checks[1].passed is True

    # Verify settings_path was actually written
    assert settings_path.exists()

    # Verify required failure if no settings path given
    report2 = run_release_gate_checks()
    assert report2.passed is False
    assert report2.checks[1].passed is False
    assert "must be provided" in report2.checks[1].detail


def test_run_release_gate_checks_theme(tmp_path):
    settings_path = tmp_path / "test_settings_theme.json"
    report = run_release_gate_checks(db_path=tmp_path / "mock.db", settings_path=settings_path)

    assert report.passed is True
    assert len(report.checks) >= 3

    theme_check = next(c for c in report.checks if c.name == "Theme Engine & WCAG Contrast")
    assert theme_check.passed is True
    assert "Verified WCAG compliance" in theme_check.detail


def test_run_release_gate_checks_assets(tmp_path):
    settings_path = tmp_path / "test_settings_assets.json"
    report = run_release_gate_checks(db_path=tmp_path / "mock.db", settings_path=settings_path)

    assert report.passed is True
    assert len(report.checks) >= 4

    asset_check = next(c for c in report.checks if c.name == "Template & Asset Integrity")
    assert asset_check.passed is True
    assert "All required assets exist" in asset_check.detail


def test_run_release_gate_checks_api(tmp_path):
    settings_path = tmp_path / "test_settings_api.json"
    db_path = tmp_path / "test_api.db"
    report = run_release_gate_checks(db_path=db_path, settings_path=settings_path)

    assert report.passed is True
    assert len(report.checks) >= 5

    api_check = next(c for c in report.checks if c.name == "API Smoke Gate")
    assert api_check.passed is True

    # Test failure when db_path is missing
    report_fail = run_release_gate_checks(settings_path=settings_path)
    api_check_fail = next(c for c in report_fail.checks if c.name == "API Smoke Gate")
    assert api_check_fail.passed is False
    assert "db_path must be provided" in api_check_fail.detail


def test_run_release_gate_checks_supervisor(tmp_path):
    settings_path = tmp_path / "test_settings_supervisor.json"
    db_path = tmp_path / "test_supervisor.db"
    report = run_release_gate_checks(db_path=db_path, settings_path=settings_path)

    assert report.passed is True
    assert len(report.checks) >= 6

    supervisor_check = next(c for c in report.checks if c.name == "Supervisor Clean Teardown")
    assert supervisor_check.passed is True
    assert "no orphans" in supervisor_check.detail
