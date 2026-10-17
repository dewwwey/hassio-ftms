# Copyright 2024, Sergey Dudanov
# SPDX-License-Identifier: Apache-2.0

import logging
from typing import Any, cast

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from ...models import RealtimeData
from ...serializer import ModelSerializer, get_serializer
from .event import FtmsCallback, UpdateEvent, UpdateEventData

_LOGGER = logging.getLogger(__name__)


class DataUpdater:
    _serializer: ModelSerializer[RealtimeData]

    def __init__(
        self, model: type[RealtimeData], callback: FtmsCallback
    ) -> None:
        self._cb = callback
        self._serializer = get_serializer(model)
        self._prev: dict[str, Any] = {}
        self._result: dict[str, Any] = {}

    def reset(self) -> None:
        """Resetting state. Call while disconnection event."""
        self._prev.clear()
        self._result.clear()

    async def subscribe(self, cli: BleakClient, uuid: str) -> None:
        """Subscribe for notification."""
        self.reset()
        await cli.start_notify(uuid, self._on_notify)

    def _on_notify(self, c: BleakGATTCharacteristic, data: bytearray) -> None:
        _LOGGER.debug("Received notify: %s", data.hex(" ").upper())
        try:
            data_ = self._serializer.deserialize(data)._asdict()
        except (ValueError, AssertionError, EOFError, TypeError, IndexError):
            self._result.clear()
            self._cb(UpdateEvent(event_id="update", event_data={"packet_error": 1}))
            return
        _LOGGER.debug("Received notify dict: %s", data_)
        self._result |= data_

        # If `More Data` bit is set - we must wait for other messages.
        if data[0] & 1:
            _LOGGER.debug("'More Data' bit is set. Waiting for next data.")
            return

        # Every complete frame is evidence, including repeated and all-zero frames.
        self._cb(UpdateEvent(event_id="update", event_data=self._result.copy()))
        self._result.clear()
