import abc
import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class DriverClosedError(RuntimeError):
    """Raised when a caller tries to use a driver that is closing or closed."""


class BaseRadioDriver(abc.ABC):
    """
    Abstract base class defining the required interface for all radio hardware
    drivers (e.g., Meshtastic, Mesh Core).
    """

    @property
    @abc.abstractmethod
    def bbs_nodes(self):
        """Returns known peer BBS nodes for sync and keepalive logic."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def allowed_nodes(self):
        """Returns nodes that are authorized for administrative actions."""
        raise NotImplementedError

    @abc.abstractmethod
    def send_text(self, text, destination_id, want_ack=True):
        """
        Sends a text message to a specific destination.

        Args:
            text (str): The message content.
            destination_id (str): The destination node's ID.
            want_ack (bool): Whether to request a delivery acknowledgment.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_nodes(self):
        """
        Retrieves the list of all known nodes in the mesh.

        Returns:
            dict: Node data keyed by node_id.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_node_by_num(self, node_num):
        """
        Finds a node's data based on its numeric identifier.

        Args:
            node_num (int): The numeric ID of the node.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_my_node_id(self):
        """
        Retrieves the unique string ID of the local node.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_my_node_num(self):
        """
        Retrieves the numeric ID of the local node.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_short_name(self, node_id):
        """
        Retrieves the short name (alias) of a given node.

        Args:
            node_id (str): The unique string ID of the node.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def close(self):
        """
        Gracefully shuts down the radio hardware interface.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def getNode(self, node_id):
        """
        Retrieves a node object for direct interaction (e.g., keepalives).

        Args:
            node_id (str): The unique string ID of the node.
        """
        raise NotImplementedError


class MeshtasticDriver(BaseRadioDriver):
    """
    Adapter for the Meshtastic Python library, mapping the standard BBS driver
    interface to Meshtastic-specific method calls.
    """

    def __init__(self, interface, bbs_nodes=None, allowed_nodes=None):
        """
        Initializes the driver with an active Meshtastic interface.

        Args:
            interface: An initialized meshtastic.stream_interface.StreamInterface.
            bbs_nodes (list, optional): Known peer BBS nodes for sync logic.
            allowed_nodes (list, optional): Nodes with administrative permissions.
        """
        self.interface = interface
        self._bbs_nodes = bbs_nodes if bbs_nodes is not None else []
        self._allowed_nodes = allowed_nodes if allowed_nodes is not None else []
        self._lifecycle = threading.Condition()
        self._active_calls = 0
        self._closing = False
        self._closed = False

    @contextmanager
    def _driver_call(self):
        """
        Serializes driver shutdown against in-flight operations.

        New callers are fenced out as soon as close() begins, while the closer
        waits for already-running driver calls to drain before the underlying
        Meshtastic interface is torn down.
        """
        with self._lifecycle:
            if self._closing or self._closed:
                raise DriverClosedError("Radio driver is closing or already closed")
            self._active_calls += 1

        try:
            yield self.interface
        finally:
            with self._lifecycle:
                self._active_calls -= 1
                if self._active_calls == 0:
                    self._lifecycle.notify_all()

    @property
    def bbs_nodes(self):
        """Immutable list of peer BBS nodes for this session."""
        return self._bbs_nodes

    @property
    def allowed_nodes(self):
        """Immutable list of authorized administrator nodes for this session."""
        return self._allowed_nodes

    @property
    def myInfo(self):
        # Maintained for backward compatibility with the legacy server watchdog logic.
        with self._driver_call() as interface:
            return interface.myInfo

    @property
    def nodes(self):
        # Maintained for legacy code that performs direct dictionary access on node lists.
        with self._driver_call() as interface:
            return interface.nodes

    def send_text(self, text, destination_id, want_ack=True):
        with self._driver_call() as interface:
            return interface.sendText(
                text=text,
                destinationId=destination_id,
                wantAck=want_ack,
                wantResponse=False,
            )

    def get_nodes(self):
        with self._driver_call() as interface:
            return interface.nodes

    def get_node_by_num(self, node_num):
        for _, node in self.get_nodes().items():
            if node["num"] == node_num:
                return node
        return None

    def get_my_node_id(self):
        with self._driver_call() as interface:
            return interface.myInfo.my_node_id

    def get_my_node_num(self):
        with self._driver_call() as interface:
            return interface.myInfo.my_node_num

    def get_short_name(self, node_id):
        node_info = self.get_nodes().get(node_id)
        if node_info and node_info.get("user"):
            return node_info["user"].get("shortName")
        return None

    def getNode(self, node_id):
        with self._driver_call() as interface:
            return interface.getNode(node_id)

    def close(self):
        with self._lifecycle:
            if self._closed:
                return None

            if self._closing:
                while not self._closed:
                    self._lifecycle.wait()
                return None

            self._closing = True
            while self._active_calls > 0:
                self._lifecycle.wait()

        try:
            return self.interface.close()
        finally:
            with self._lifecycle:
                self._closed = True
                self._closing = False
                self._lifecycle.notify_all()


class MeshCoreStubDriver(BaseRadioDriver):
    """
    Placeholder driver for future Mesh Core integration. Provides a safe
    no-op environment for development without active radio hardware.
    """

    def __init__(self, config):
        """
        Args:
            config: The system configuration dictionary.
        """
        self.config = config
        logger.info("Mesh Core Driver Stub initialized (Hardware not yet connected)")

    @property
    def bbs_nodes(self):
        return []

    @property
    def allowed_nodes(self):
        return []

    def send_text(self, text, destination_id, want_ack=True):
        logger.info(f"MESH CORE STUB: Sending '{text}' to {destination_id}")
        return True

    def get_nodes(self):
        return {}

    def get_node_by_num(self, node_num):
        return None

    def get_my_node_id(self):
        return "MC-STUB"

    def get_my_node_num(self):
        return 0

    def get_short_name(self, node_id):
        return "Stub"

    def close(self):
        pass

    def getNode(self, node_id):
        return None
