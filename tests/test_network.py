"""Offline SSRF protection tests."""

from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import network  # noqa: E402


def answer(address: str):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, 443))]


class NetworkSafety(unittest.TestCase):
    def test_refuse_schemas_identifiants_et_ports_non_standards(self):
        for url in ("file:///etc/passwd", "http://user@example.com", "http://example.com:8080"):
            with self.subTest(url=url), self.assertRaises(network.UnsafeUrl):
                network.validate_url(url)

    def test_refuse_toutes_les_destinations_non_globales(self):
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.2", "::1", "fe80::1"):
            with self.subTest(address=address), mock.patch.object(
                socket, "getaddrinfo", return_value=answer(address)
            ), self.assertRaises(network.UnsafeUrl):
                network.validate_url("https://jobs.example.test/offre")

    def test_accepte_une_destination_publique(self):
        with mock.patch.object(socket, "getaddrinfo", return_value=answer("93.184.216.34")):
            target = network.validate_url("https://Example.com/job?q=1#fragment")
        self.assertEqual(target.host, "example.com")
        self.assertEqual(target.addresses, ("93.184.216.34",))
        self.assertNotIn("fragment", target.url)

    def test_refuse_si_une_des_adresses_dns_est_privee(self):
        mixed = answer("93.184.216.34") + answer("127.0.0.1")
        with mock.patch.object(socket, "getaddrinfo", return_value=mixed), self.assertRaises(network.UnsafeUrl):
            network.validate_url("https://jobs.example.test")

    def test_redirection_est_revalidee(self):
        def dns(host, port, **_kwargs):
            return answer("127.0.0.1" if host == "internal.test" else "93.184.216.34")
        with mock.patch.object(socket, "getaddrinfo", side_effect=dns), mock.patch.object(
            network, "_request_once", return_value=(302, {"location": "http://internal.test/secret"}, b"")
        ), self.assertRaises(network.UnsafeUrl):
            network.fetch_bytes("https://public.test/job")

    def test_interdit_la_degradation_https_vers_http(self):
        with mock.patch.object(socket, "getaddrinfo", return_value=answer("93.184.216.34")), mock.patch.object(
            network, "_request_once", return_value=(302, {"location": "http://public.test/job"}, b"")
        ), self.assertRaises(network.UnsafeUrl):
            network.fetch_bytes("https://public.test/job")

    def test_connexion_http_utilise_l_adresse_resolue(self):
        target = network.SafeTarget("http://example.test/", "http", "example.test", 80, "/", ("93.184.216.34",))
        fake_socket = object()
        with mock.patch.object(socket, "create_connection", return_value=fake_socket) as connect:
            connection = network._PinnedHTTPConnection(target, "93.184.216.34", 3)
            connection.connect()
        connect.assert_called_once_with(("93.184.216.34", 80), 3)
        self.assertIs(connection.sock, fake_socket)


if __name__ == "__main__":
    unittest.main(verbosity=2)
