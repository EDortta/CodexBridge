import json
import subprocess
import sys


def test_list_users_does_not_prompt_or_expose_password_hash(tmp_path):
    registry = tmp_path / "users.json"
    registry.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "esteban",
                        "email": "esteban@example.test",
                        "password_hash": "secret-hash",
                        "roles": ["admin"],
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "tools/codexbridge-user.py", "--registry", str(registry), "--list"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "esteban\testeban@example.test\tyes\tadmin\n"
    assert "secret-hash" not in result.stdout
    assert "password" not in result.stderr.lower()
