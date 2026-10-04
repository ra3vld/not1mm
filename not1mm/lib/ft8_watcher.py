"""
WSJT-x UDP Packet Watcher
Email: michael.bridak@gmail.com
https://github.com/mbridak/not1mm
GPL V3
"""

import logging
import struct

from PyQt6 import QtNetwork

logger = logging.getLogger(__name__)


class FT8Watcher:
    """Main Window"""

    def __init__(self, *args, **kwargs):
        """Initialize"""
        super().__init__(*args, **kwargs)
        self.multicast_group = "224.0.0.1"
        self.multicast_port = 2237
        self.interface_ip = "0.0.0.0"
        self.udp_socket = QtNetwork.QUdpSocket()
        b_result = self.udp_socket.bind(
            QtNetwork.QHostAddress.SpecialAddress.AnyIPv4,
            int(self.multicast_port),
            QtNetwork.QAbstractSocket.BindFlag.ReuseAddressHint,
        )
        logger.info(f"multicast bind {b_result}")
        join_result = self.udp_socket.joinMulticastGroup(
            QtNetwork.QHostAddress(self.multicast_group)
        )
        logger.info(f"joinMulticastGroup result {join_result}")

        self.callback = None
        self.datadict = {}
        self.udp_socket.readyRead.connect(self.on_udp_socket_ready_read)

    def set_callback(self, callback):
        """Set callback"""
        self.callback = callback

    @staticmethod
    def getint(bytestring):
        """
        Returns an int from a bigendian signed 4 byte string
        """
        return int.from_bytes(bytestring, byteorder="big", signed=True)

    @staticmethod
    def getuint(bytestring):
        """
        Returns an int from a bigendian unsigned 4 byte string
        """
        return int.from_bytes(bytestring, byteorder="big", signed=False)

    @staticmethod
    def getbool(bytestring):
        """
        Returns a bool from a 1 byte string
        """
        return bool.from_bytes(bytestring, byteorder="big", signed=False)

    def getvalue(self, item):
        """I don't remember what this does."""
        if item in self.datadict:
            return self.datadict[item]
        return "NOT_FOUND"

    @staticmethod
    def logged_adif(datagram):
        """Read WSJT-X type 12, including fields that precede CALL.

        NetworkMessage.hpp defines two length-prefixed UTF-8 byte arrays:
        instance ID and ADIF. Extra future fields are ignored.
        """
        import adif_io

        if len(datagram) < 16:
            return None
        magic, schema, packettype, id_size = struct.unpack(">IIII", datagram[:16])
        if magic != 0xADBCCBDA or schema not in (2, 3) or packettype != 12:
            return None
        offset = 16 + id_size
        if offset + 4 > len(datagram):
            return None
        size = int.from_bytes(datagram[offset : offset + 4], "big")
        if size == 0xFFFFFFFF or offset + 4 + size > len(datagram):
            return None
        try:
            records, _ = adif_io.read_from_string(
                datagram[offset + 4 : offset + 4 + size].decode("utf-8")
            )
            if len(records) != 1:
                return None
            record = dict(records[0])
            return record if record.get("CALL") else None
        except (UnicodeError, ValueError, IndexError):
            logger.warning("Invalid WSJT-X logged ADIF packet")
            return None

    def on_udp_socket_ready_read(self):
        """Drain queued datagrams; only complete logged ADIF messages log QSOs."""
        while self.udp_socket.hasPendingDatagrams():
            datagram, _sender_host, _sender_port = self.udp_socket.readDatagram(
                self.udp_socket.pendingDatagramSize()
            )
            record = self.logged_adif(datagram)
            if record is not None:
                self.datadict = record
                if self.callback:
                    self.callback(record)
