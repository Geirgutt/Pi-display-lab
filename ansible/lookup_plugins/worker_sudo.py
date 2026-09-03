"""Fetch a worker's sudo password from the installer's private local socket."""

import json
import socket

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        path = kwargs.get("socket_path")
        if not isinstance(path, str) or not path:
            raise AnsibleError("Mangler lokal sudo-passordtjeneste. Kjør scripts/install-cluster.sh.")
        passwords = []
        for host in terms:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(10)
                    connection.connect(path)
                    connection.sendall(json.dumps(host).encode("utf-8") + b"\n")
                    with connection.makefile("rb") as response:
                        payload = json.loads(response.readline(1024 * 1024))
                password = payload.get("password")
                if not isinstance(password, str):
                    raise ValueError("Unknown worker")
                passwords.append(password)
            except (OSError, ValueError, AttributeError):
                raise AnsibleError("Kunne ikke hente workerens sudo-passord. Kjør installasjonen på nytt.") from None
        # Ansible treats lookup results as unsafe text, preserving literal passwords.
        return passwords
