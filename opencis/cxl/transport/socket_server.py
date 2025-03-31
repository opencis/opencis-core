"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import traceback
from typing import List
import socket
from opencis.util.logger import logger


class SocketServerTransport:
    def __init__(self, host="0.0.0.0", port=8000):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((host, port))
        server_socket.listen(5)
        server_socket.setblocking(False)
        self._server_socket = server_socket
        self._incoming_connections = set()
        self._claimed_connections = set()

        logger.info(f"Socket server started at {host}:{port}")

    def check_incoming_connections(self):
        try:
            connection, _ = self._server_socket.accept()
            logger.info("Client connected")
            connection.setblocking(False)
            self._incoming_connections.add(connection)
        except Exception as e:
            logger.error(f"check_incoming_connections error: {str(e)}: {traceback.format_exc()}")

    def get_incoming_connections(self) -> List[socket.socket]:
        return list(self._incoming_connections)

    def claim_connection(self, connection: socket.socket) -> bool:
        if connection in self._claimed_connections:
            return False
        if connection not in self._incoming_connections:
            return False
        self._incoming_connections.remove(connection)
        self._claimed_connections.add(connection)
        return False

    @staticmethod
    def is_active_connection(connection: socket.socket) -> bool:
        try:
            error_code = connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            return error_code == 0
        except Exception as e:
            logger.error(f"is_active_connection error: {str(e)}: {traceback.format_exc()}")
            return False

    def unclaim_connection(self, connection: socket.socket) -> bool:
        if self.is_active_connection(connection):
            logger.info("Cannot unclaim an active connection")
            return False
        if connection not in self._claimed_connections:
            return False
        connection.close()
        self._claimed_connections.remove(connection)
        return True
