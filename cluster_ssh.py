"""Shared strict SSH transport for setup, preflight and sudo checks."""

from __future__ import annotations

import os
import subprocess


def ssh_options(identity_file: str = "", *, password_login: bool = False) -> list[str]:
    options = [
        "ssh", "-T", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=8",
        "-o", "LogLevel=ERROR", "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "-o", "BatchMode=no" if password_login else "BatchMode=yes",
    ]
    if password_login:
        options += ["-o", "PreferredAuthentications=password,keyboard-interactive",
                    "-o", "PubkeyAuthentication=no", "-o", "NumberOfPasswordPrompts=1"]
    elif identity_file:
        options += ["-i", identity_file, "-o", "IdentitiesOnly=yes"]
    return options


def ssh_run(user: str, host: str, remote: str, *, identity_file: str = "",
            login_password: str | None = None, stdin: str = "", timeout: int = 30):
    command = ssh_options(identity_file, password_login=login_password is not None)
    command += [f"{user}@{host}", remote]
    descriptors: tuple[int, ...] = ()
    read_fd = None
    try:
        if login_password is not None:
            # A dedicated inherited pipe lets stdin carry the public key or sudo data.
            encoded = login_password.encode("utf-8") + b"\n"
            if len(encoded) > 4096:
                raise RuntimeError("SSH-passordet er for langt (maks 4095 UTF-8-byte).")
            read_fd, write_fd = os.pipe()
            try:
                os.write(write_fd, encoded)
            finally:
                os.close(write_fd)
            descriptors = (read_fd,)
            command = ["sshpass", "-d", str(read_fd), *command]
        options = {"pass_fds": descriptors} if descriptors else {}
        return subprocess.run(command, input=stdin, capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout, **options)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(f"{host}: SSH mislyktes eller brukte for lang tid. Kontroller nettverk og SSH.") from None
    finally:
        if read_fd is not None:
            os.close(read_fd)


def require_ssh(result, host: str) -> None:
    if not result.returncode:
        return
    error = result.stderr or ""
    if "IDENTIFICATION HAS CHANGED" in error or "Host key verification failed" in error:
        raise RuntimeError(f"{host}: SSH-vertsnøkkelen er ukjent eller endret. Kontroller fingerprint; kjent nøkkel erstattes ikke automatisk.")
    if result.returncode == 255:
        raise RuntimeError(f"{host}: SSH-tilgang mangler. Kontroller bruker, nøkkel, aktivert SSH og nettverk.")
    raise RuntimeError(f"{host}: fjernkommandoen feilet (kode {result.returncode}).")
