# pyright: standard
import os
from pathlib import Path

from pytest_mock import MockerFixture

from aico.core.trust import (
    is_project_trusted,
    list_trusted_projects,
    trust_project,
    untrust_project,
)


def test_trust_flow(tmp_path: Path, mocker: MockerFixture) -> None:
    # SETUP: Mock trust file location to tmp_path
    trust_file = tmp_path / "trust.json"
    mocker.patch("aico.core.trust._get_trust_file", return_value=trust_file)

    project_path = Path("/tmp/my-project").resolve()

    # 1. Default state: not trusted
    assert not is_project_trusted(project_path)
    assert list_trusted_projects() == []

    # 2. Trust project
    trust_project(project_path)
    assert is_project_trusted(project_path)
    assert list_trusted_projects() == [str(project_path)]

    # 3. Verify file permissions (0o600)
    if os.name == "posix":
        mode = trust_file.stat().st_mode & 0o777
        assert mode == 0o600

    # 4. Untrust project
    assert untrust_project(project_path) is True
    assert not is_project_trusted(project_path)
    assert list_trusted_projects() == []

    # 5. Untrust non-existent
    assert untrust_project(project_path) is False
