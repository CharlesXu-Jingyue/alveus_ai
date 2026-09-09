from alveus.agent.loop import _SUDO, Agent
from mcp_servers.files_shell import with_sudo_password


class _Info:
    def __init__(self, name):
        self.name, self.destructive = name, False


def test_sudo_detection():
    assert _SUDO.search("sudo apt update")
    assert _SUDO.search("cd /tmp && sudo systemctl restart foo")
    assert _SUDO.search("echo hi | sudo tee /etc/x")
    assert not _SUDO.search("echo sudoku")
    assert not _SUDO.search("ls -la")
    assert Agent._needs_sudo(_Info("run_command"), {"command": "sudo ls"})
    assert not Agent._needs_sudo(_Info("read_file"), {"path": "sudo"})


def test_password_rewrite():
    cmd, stdin = with_sudo_password("sudo apt update && sudo apt upgrade -y", "pw")
    assert cmd == "sudo -S -p '' apt update && sudo apt upgrade -y"
    assert stdin == "pw\n"
    # already reading from stdin: left alone
    assert with_sudo_password("sudo -S true", "pw")[0] == "sudo -S true"
    # no password, or no sudo: untouched, nothing on stdin
    assert with_sudo_password("sudo true", "") == ("sudo true", None)
    assert with_sudo_password("ls", "pw") == ("ls", None)
